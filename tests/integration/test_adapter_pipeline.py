"""End-to-end adapter, repository, and monitoring pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from greenhouse_steward.adapters.csv_source import StrictCsvSource
from greenhouse_steward.adapters.profile_store import JsonProfileStore
from greenhouse_steward.adapters.sqlite_repository import SQLiteObservationRepository
from greenhouse_steward.domain import FrozenClock
from greenhouse_steward.services.monitoring import MonitoringService


def test_packaged_csv_to_sqlite_to_historical_evaluation(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    sample = root / "src" / "greenhouse_steward" / "sample_data" / "data" / "tomato-7d.csv"
    snapshots = StrictCsvSource().read_path(sample, device_id="sample-tomato")
    clock = FrozenClock(datetime(2026, 1, 12, tzinfo=UTC))
    repository = SQLiteObservationRepository(tmp_path / "data.sqlite3", clock=clock)
    service = MonitoringService(repository, JsonProfileStore(), clock=clock)

    result = service.ingest_many(
        snapshots,
        profile_slug="tomato",
        source_kind="csv",
        source_ref="tomato-7d.csv",
        evaluated_at=snapshots[-1].observed_at,
    )

    assert result.storage.inserted == 672
    assert result.monitoring.history_reading_count == 2688
    assert len(result.monitoring.trends.daily) == 28
    assert result.monitoring.evaluation.latest_readings
