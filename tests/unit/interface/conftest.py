"""Deterministic fixtures for the shared CLI and web application facade."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from greenhouse_steward.adapters import (
    JsonProfileStore,
    SQLiteObservationRepository,
    StrictCsvSource,
)
from greenhouse_steward.application import GreenhouseApplication
from greenhouse_steward.domain import FrozenClock


@pytest.fixture
def fixed_now() -> datetime:
    """Clock instant shared by live-interface tests."""

    return datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def app_clock(fixed_now: datetime) -> FrozenClock:
    """Controllable clock for status and relay assertions."""

    return FrozenClock(fixed_now)


@pytest.fixture
def facade(tmp_path: Path, app_clock: FrozenClock) -> GreenhouseApplication:
    """Real facade composed from production local adapters."""

    repository = SQLiteObservationRepository(
        tmp_path / "interface.sqlite3",
        clock=app_clock,
    )
    return GreenhouseApplication(
        csv_source=StrictCsvSource(),
        profiles=JsonProfileStore(),
        repository=repository,
        clock=app_clock,
    )


@pytest.fixture
def dry_csv(fixed_now: datetime) -> bytes:
    """Two fresh, valid snapshots that produce dry-soil guidance."""

    first = fixed_now - timedelta(minutes=1)
    return (
        "timestamp,temperature_c,humidity_pct,soil_moisture_pct,light_lux\n"
        f"{first.isoformat()},22.0,65.0,30.0,20000.0\n"
        f"{fixed_now.isoformat()},22.5,64.0,31.0,21000.0\n"
    ).encode()
