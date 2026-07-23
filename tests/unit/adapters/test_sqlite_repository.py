"""SQLite atomicity, idempotency, query, and export tests."""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta

import pytest

from greenhouse_steward.adapters.csv_source import StrictCsvSource
from greenhouse_steward.adapters.sqlite_repository import (
    ObservationConflictError,
    SQLiteObservationRepository,
)
from greenhouse_steward.domain import FrozenClock, Metric, SensorReading
from greenhouse_steward.ports import ReadingSnapshot, StoreOutcome


def _snapshot(minute: int, *, temperature: float = 20.0) -> ReadingSnapshot:
    observed_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minute)
    values = {
        Metric.TEMPERATURE: temperature,
        Metric.HUMIDITY: 60.0,
        Metric.SOIL_MOISTURE: 45.0,
        Metric.LIGHT: 1000.0,
    }
    return ReadingSnapshot(
        device_id="device-1",
        observed_at=observed_at,
        readings=tuple(
            SensorReading(
                sensor_id=f"device-1:{metric.value}",
                metric=metric,
                value=values[metric],
                observed_at=observed_at,
            )
            for metric in Metric
        ),
    )


def test_memory_repository_survives_connections_and_is_idempotent() -> None:
    repo = SQLiteObservationRepository(
        ":memory:",
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    snapshot = _snapshot(0)

    assert repo.save_snapshot(snapshot, source_kind="test") == StoreOutcome.INSERTED
    assert repo.save_snapshot(snapshot, source_kind="test") == StoreOutcome.UNCHANGED
    assert repo.count() == 1
    assert repo.latest("device-1") == snapshot


def test_memory_repositories_never_share_a_named_cache() -> None:
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    repositories = [SQLiteObservationRepository(":memory:", clock=clock) for _ in range(16)]
    repositories[0].save_snapshot(_snapshot(0), source_kind="test")

    assert repositories[0].count() == 1
    assert all(repository.count() == 0 for repository in repositories[1:])
    assert len({repository._path for repository in repositories}) == len(repositories)


def test_conflicting_batch_rolls_back_and_does_not_replace() -> None:
    repo = SQLiteObservationRepository(
        ":memory:",
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    original = _snapshot(0)
    repo.save_snapshot(original, source_kind="test")

    with pytest.raises(ObservationConflictError):
        repo.save_many(
            (_snapshot(15), _snapshot(0, temperature=99.0)),
            source_kind="test",
        )

    assert repo.count() == 1
    assert repo.latest("device-1") == original


def test_query_limit_returns_newest_window_in_ascending_order() -> None:
    repo = SQLiteObservationRepository(
        ":memory:",
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    repo.save_many((_snapshot(0), _snapshot(15), _snapshot(30)), source_kind="test")

    result = repo.query("device-1", limit=2)

    assert [item.observed_at.minute for item in result] == [15, 30]


def test_export_round_trips_through_strict_csv() -> None:
    repo = SQLiteObservationRepository(
        ":memory:",
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    repo.save_many((_snapshot(0), _snapshot(15)), source_kind="test")
    output = io.StringIO(newline="")

    assert repo.export_csv(output, device_id="device-1") == 2
    parsed = StrictCsvSource().read_text(output.getvalue(), device_id="device-1")
    assert parsed == (_snapshot(0), _snapshot(15))
