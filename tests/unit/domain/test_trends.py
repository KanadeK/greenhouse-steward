"""Calendar and numeric tests for trend aggregation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from greenhouse_steward.domain import (
    Metric,
    PeriodAggregate,
    SensorReading,
    TrendDirection,
    build_trends,
)


def _reading(
    metric: Metric,
    value: float,
    observed_at: datetime,
) -> SensorReading:
    return SensorReading(
        sensor_id=f"{metric.value}-sensor",
        metric=metric,
        value=value,
        observed_at=observed_at,
    )


def test_empty_input_returns_empty_real_report() -> None:
    report = build_trends([])

    assert report.timezone == "UTC"
    assert report.daily == ()
    assert report.weekly == ()


def test_daily_statistics_and_direction_are_order_independent() -> None:
    readings = [
        _reading(
            Metric.TEMPERATURE,
            24.0,
            datetime(2026, 1, 2, 12, tzinfo=UTC),
        ),
        _reading(
            Metric.TEMPERATURE,
            20.0,
            datetime(2026, 1, 1, 20, tzinfo=UTC),
        ),
        _reading(
            Metric.TEMPERATURE,
            22.0,
            datetime(2026, 1, 1, 8, tzinfo=UTC),
        ),
        _reading(
            Metric.TEMPERATURE,
            26.0,
            datetime(2026, 1, 2, 20, tzinfo=UTC),
        ),
    ]

    report = build_trends(readings)

    assert len(report.daily) == 2
    first, second = report.daily
    assert (first.count, first.minimum, first.maximum, first.mean) == (
        2,
        20.0,
        22.0,
        21.0,
    )
    assert first.change_from_previous is None
    assert first.direction == TrendDirection.INSUFFICIENT_DATA
    assert second.mean == 25.0
    assert second.change_from_previous == 4.0
    assert second.direction == TrendDirection.UP


def test_stable_epsilon_prevents_noise_from_becoming_trend() -> None:
    readings = [
        _reading(
            Metric.HUMIDITY,
            50.0,
            datetime(2026, 1, 1, 12, tzinfo=UTC),
        ),
        _reading(
            Metric.HUMIDITY,
            50.5,
            datetime(2026, 1, 2, 12, tzinfo=UTC),
        ),
    ]

    report = build_trends(
        readings,
        stable_epsilon={Metric.HUMIDITY: 1.0},
    )

    assert report.daily[1].change_from_previous == 0.5
    assert report.daily[1].direction == TrendDirection.STABLE


def test_decreasing_period_mean_is_downward() -> None:
    readings = [
        _reading(
            Metric.HUMIDITY,
            60.0,
            datetime(2026, 1, 1, 12, tzinfo=UTC),
        ),
        _reading(
            Metric.HUMIDITY,
            50.0,
            datetime(2026, 1, 2, 12, tzinfo=UTC),
        ),
    ]

    report = build_trends(readings)

    assert report.daily[1].change_from_previous == -10.0
    assert report.daily[1].direction == TrendDirection.DOWN


def test_week_starts_on_local_monday() -> None:
    readings = [
        _reading(
            Metric.SOIL_MOISTURE,
            40.0,
            datetime(2026, 1, 4, 12, tzinfo=UTC),
        ),
        _reading(
            Metric.SOIL_MOISTURE,
            50.0,
            datetime(2026, 1, 5, 12, tzinfo=UTC),
        ),
    ]

    report = build_trends(readings)

    assert len(report.weekly) == 2
    assert report.weekly[0].period_start.date().isoformat() == "2025-12-29"
    assert report.weekly[1].period_start.date().isoformat() == "2026-01-05"
    assert report.weekly[1].direction == TrendDirection.UP


def test_cross_year_week_groups_by_monday_date() -> None:
    readings = [
        _reading(
            Metric.LIGHT,
            1_000.0,
            datetime(2025, 12, 31, 12, tzinfo=UTC),
        ),
        _reading(
            Metric.LIGHT,
            2_000.0,
            datetime(2026, 1, 1, 12, tzinfo=UTC),
        ),
    ]

    report = build_trends(readings)

    assert len(report.weekly) == 1
    assert report.weekly[0].period_start.date().isoformat() == "2025-12-29"
    assert report.weekly[0].count == 2
    assert report.weekly[0].mean == 1_500.0


def test_local_timezone_controls_calendar_day() -> None:
    readings = [
        _reading(
            Metric.TEMPERATURE,
            20.0,
            datetime(2026, 1, 1, 16, 30, tzinfo=UTC),
        ),
        _reading(
            Metric.TEMPERATURE,
            22.0,
            datetime(2026, 1, 2, 15, 30, tzinfo=UTC),
        ),
    ]

    report = build_trends(readings, timezone="+08:00")

    assert len(report.daily) == 1
    assert report.daily[0].period_start.date().isoformat() == "2026-01-02"
    assert report.daily[0].count == 2


def test_dst_days_use_local_midnight_boundaries() -> None:
    readings = [
        _reading(
            Metric.TEMPERATURE,
            20.0,
            datetime(2026, 3, 8, 6, 30, tzinfo=UTC),
        ),
        _reading(
            Metric.TEMPERATURE,
            22.0,
            datetime(2026, 3, 9, 3, 30, tzinfo=UTC),
        ),
    ]

    report = build_trends(readings, timezone="America/New_York")

    assert len(report.daily) == 1
    aggregate = report.daily[0]
    assert aggregate.count == 2
    assert aggregate.period_start.utcoffset() != aggregate.period_end.utcoffset()
    assert aggregate.period_end.astimezone(UTC) - aggregate.period_start.astimezone(
        UTC
    ) == timedelta(hours=23)


def test_fall_dst_day_spans_25_real_hours() -> None:
    readings = [
        _reading(
            Metric.TEMPERATURE,
            20.0,
            datetime(2026, 11, 1, 5, 30, tzinfo=UTC),
        ),
        _reading(
            Metric.TEMPERATURE,
            22.0,
            datetime(2026, 11, 2, 4, 30, tzinfo=UTC),
        ),
    ]

    report = build_trends(readings, timezone="America/New_York")

    aggregate = report.daily[0]
    assert aggregate.count == 2
    assert aggregate.period_end.astimezone(UTC) - aggregate.period_start.astimezone(
        UTC
    ) == timedelta(hours=25)


def test_midnight_dst_gap_resolves_to_first_valid_local_instant() -> None:
    reading = _reading(
        Metric.TEMPERATURE,
        20.0,
        datetime(2025, 9, 7, 5, tzinfo=UTC),
    )

    report = build_trends([reading], timezone="America/Santiago")

    aggregate = report.daily[0]
    assert aggregate.period_start.date().isoformat() == "2025-09-07"
    assert aggregate.period_start.hour == 1
    assert aggregate.period_start.utcoffset() == timedelta(hours=-3)
    assert (
        aggregate.period_start.astimezone(UTC).astimezone(aggregate.period_start.tzinfo)
        == aggregate.period_start
    )


def test_metrics_have_independent_previous_periods() -> None:
    readings = [
        _reading(
            Metric.TEMPERATURE,
            20.0,
            datetime(2026, 1, 1, tzinfo=UTC),
        ),
        _reading(
            Metric.HUMIDITY,
            50.0,
            datetime(2026, 1, 2, tzinfo=UTC),
        ),
    ]

    report = build_trends(readings)

    assert all(
        aggregate.direction == TrendDirection.INSUFFICIENT_DATA for aggregate in report.daily
    )


def test_invalid_timezone_and_epsilon_are_rejected() -> None:
    with pytest.raises(ValueError, match="unknown timezone"):
        build_trends([], timezone="Mars/Olympus")
    with pytest.raises(ValueError, match="invalid UTC offset"):
        build_trends([], timezone="+15:00")
    with pytest.raises(ValueError, match="non-negative"):
        build_trends([], stable_epsilon={Metric.LIGHT: -1.0})


def test_period_aggregate_rejects_incoherent_statistics() -> None:
    with pytest.raises(ValidationError, match="between"):
        PeriodAggregate(
            metric=Metric.TEMPERATURE,
            period_start=datetime(2026, 1, 1, tzinfo=UTC),
            period_end=datetime(2026, 1, 2, tzinfo=UTC),
            count=1,
            minimum=20.0,
            maximum=21.0,
            mean=22.0,
            change_from_previous=None,
            direction=TrendDirection.INSUFFICIENT_DATA,
        )
    with pytest.raises(ValidationError, match="after period_start"):
        PeriodAggregate(
            metric=Metric.TEMPERATURE,
            period_start=datetime(2026, 1, 2, tzinfo=UTC),
            period_end=datetime(2026, 1, 1, tzinfo=UTC),
            count=1,
            minimum=20.0,
            maximum=20.0,
            mean=20.0,
            change_from_previous=None,
            direction=TrendDirection.INSUFFICIENT_DATA,
        )
    with pytest.raises(ValidationError, match="first period"):
        PeriodAggregate(
            metric=Metric.TEMPERATURE,
            period_start=datetime(2026, 1, 1, tzinfo=UTC),
            period_end=datetime(2026, 1, 2, tzinfo=UTC),
            count=1,
            minimum=20.0,
            maximum=20.0,
            mean=20.0,
            change_from_previous=None,
            direction=TrendDirection.STABLE,
        )
    with pytest.raises(ValidationError, match="directional"):
        PeriodAggregate(
            metric=Metric.TEMPERATURE,
            period_start=datetime(2026, 1, 1, tzinfo=UTC),
            period_end=datetime(2026, 1, 2, tzinfo=UTC),
            count=1,
            minimum=20.0,
            maximum=20.0,
            mean=20.0,
            change_from_previous=0.0,
            direction=TrendDirection.INSUFFICIENT_DATA,
        )
    with pytest.raises(ValidationError, match="finite"):
        PeriodAggregate(
            metric=Metric.TEMPERATURE,
            period_start=datetime(2026, 1, 1, tzinfo=UTC),
            period_end=datetime(2026, 1, 2, tzinfo=UTC),
            count=1,
            minimum=20.0,
            maximum=20.0,
            mean=float("inf"),
            change_from_previous=None,
            direction=TrendDirection.INSUFFICIENT_DATA,
        )
