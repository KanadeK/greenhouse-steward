"""Shared deterministic domain fixtures."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from greenhouse_steward.domain import (
    CropProfile,
    FrozenClock,
    Metric,
    NumericRange,
    SafetyPolicy,
    SensorReading,
    WateringPolicy,
)


@pytest.fixture
def now() -> datetime:
    """Fixed instant used by time-sensitive tests."""

    return datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def clock(now: datetime) -> FrozenClock:
    """Frozen domain clock."""

    return FrozenClock(now)


@pytest.fixture
def tomato_profile() -> CropProfile:
    """Complete educational tomato profile."""

    return CropProfile(
        slug="tomato",
        display_name="Tomato",
        targets={
            Metric.TEMPERATURE: NumericRange(low=18.0, high=28.0),
            Metric.HUMIDITY: NumericRange(low=55.0, high=75.0),
            Metric.SOIL_MOISTURE: NumericRange(low=40.0, high=70.0),
            Metric.LIGHT: NumericRange(low=10_000.0, high=50_000.0),
        },
        watering=WateringPolicy(
            trigger_below_pct=40.0,
            stop_at_pct=55.0,
            suggested_duration_seconds=180,
        ),
    )


@pytest.fixture
def safety_policy() -> SafetyPolicy:
    """Default fail-safe limits."""

    return SafetyPolicy()


@pytest.fixture
def fresh_readings(now: datetime) -> list[SensorReading]:
    """One trusted in-range reading for every metric."""

    return [
        SensorReading(
            sensor_id="temperature-1",
            metric=Metric.TEMPERATURE,
            value=23.0,
            observed_at=now,
        ),
        SensorReading(
            sensor_id="humidity-1",
            metric=Metric.HUMIDITY,
            value=65.0,
            observed_at=now,
        ),
        SensorReading(
            sensor_id="soil-1",
            metric=Metric.SOIL_MOISTURE,
            value=47.0,
            observed_at=now,
        ),
        SensorReading(
            sensor_id="light-1",
            metric=Metric.LIGHT,
            value=25_000.0,
            observed_at=now,
        ),
    ]
