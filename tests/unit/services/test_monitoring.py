"""Monitoring service orchestration and fail-safe tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from greenhouse_steward.adapters.profile_store import JsonProfileStore, ProfileNotFoundError
from greenhouse_steward.adapters.sqlite_repository import SQLiteObservationRepository
from greenhouse_steward.domain import Action, FrozenClock, Metric, SensorReading, SystemMode
from greenhouse_steward.ports import ReadingSnapshot
from greenhouse_steward.services.monitoring import MonitoringService


def _snapshot(at: datetime, *, soil: float = 45.0) -> ReadingSnapshot:
    values = {
        Metric.TEMPERATURE: 22.0,
        Metric.HUMIDITY: 65.0,
        Metric.SOIL_MOISTURE: soil,
        Metric.LIGHT: 20_000.0,
    }
    return ReadingSnapshot(
        device_id="device-1",
        observed_at=at,
        readings=tuple(
            SensorReading(
                sensor_id=f"device-1:{metric.value}",
                metric=metric,
                value=values[metric],
                observed_at=at,
            )
            for metric in Metric
        ),
    )


def _service(clock: FrozenClock) -> tuple[MonitoringService, SQLiteObservationRepository]:
    repository = SQLiteObservationRepository(":memory:", clock=clock)
    return (
        MonitoringService(repository, JsonProfileStore(), clock=clock),
        repository,
    )


def test_ingest_returns_real_rule_evaluation_and_trends() -> None:
    now = datetime(2026, 1, 5, 12, tzinfo=UTC)
    clock = FrozenClock(now)
    service, _repo = _service(clock)

    result = service.ingest(
        _snapshot(now, soil=30.0),
        profile_slug="tomato",
        source_kind="test",
    )

    assert result.evaluation.mode == SystemMode.ADVISORY
    assert result.evaluation.watering.action == Action.WATER
    assert result.evaluation.rules[0].observed_value is not None
    assert result.history_reading_count == 4
    assert result.trends.daily


def test_stale_latest_readings_force_safe_no_watering() -> None:
    now = datetime(2026, 1, 5, 12, tzinfo=UTC)
    clock = FrozenClock(now)
    service, _repo = _service(clock)
    service.ingest(
        _snapshot(now, soil=30.0),
        profile_slug="tomato",
        source_kind="test",
    )
    clock.advance(timedelta(seconds=301))

    result = service.current_status("device-1", profile_slug="tomato")

    assert result.evaluation.mode == SystemMode.SAFE
    assert result.evaluation.watering.safety_lock
    assert not result.evaluation.watering.relay_permitted
    assert set(result.evaluation.offline_metrics) == set(Metric)


def test_invalid_profile_and_timezone_are_validated_before_storage() -> None:
    now = datetime(2026, 1, 5, 12, tzinfo=UTC)
    clock = FrozenClock(now)
    service, repository = _service(clock)

    with pytest.raises(ProfileNotFoundError):
        service.ingest(
            _snapshot(now),
            profile_slug="missing",
            source_kind="test",
        )
    with pytest.raises(ValueError, match="timezone"):
        service.ingest(
            _snapshot(now),
            profile_slug="tomato",
            source_kind="test",
            trend_timezone="Mars/Olympus",
        )
    assert repository.count() == 0
