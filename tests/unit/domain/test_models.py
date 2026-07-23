"""Validation tests for domain data contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from greenhouse_steward.domain import (
    Action,
    Anomaly,
    AnomalyPolicy,
    CropProfile,
    FrozenClock,
    Metric,
    MetricAnomalyLimits,
    NumericRange,
    RuleExplanation,
    SafetyPolicy,
    SensorReading,
    Severity,
    SystemClock,
    ThresholdEvidence,
    WateringDecision,
    WateringPolicy,
)


def test_reading_normalizes_identifier_and_timestamp() -> None:
    reading = SensorReading(
        sensor_id="  sensor-a  ",
        metric=Metric.TEMPERATURE,
        value=20.5,
        observed_at=datetime(2026, 1, 1, 20, tzinfo=timezone(timedelta(hours=8))),
    )

    assert reading.sensor_id == "sensor-a"
    assert reading.observed_at == datetime(2026, 1, 1, 12, tzinfo=UTC)
    assert reading.metric.unit == "°C"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_reading_rejects_non_finite_values(value: float) -> None:
    with pytest.raises(ValidationError, match="finite"):
        SensorReading(
            sensor_id="sensor",
            metric=Metric.HUMIDITY,
            value=value,
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


@pytest.mark.parametrize("value", [True, False])
def test_reading_rejects_boolean_before_numeric_coercion(value: bool) -> None:
    with pytest.raises(ValidationError, match="not boolean"):
        SensorReading(
            sensor_id="sensor",
            metric=Metric.SOIL_MOISTURE,
            value=value,
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_reading_rejects_naive_timestamp_and_blank_identifier() -> None:
    with pytest.raises(ValidationError):
        SensorReading(
            sensor_id=" ",
            metric=Metric.HUMIDITY,
            value=50.0,
            observed_at=datetime(2026, 1, 1),
        )


def test_out_of_range_reading_remains_explainable_domain_input() -> None:
    reading = SensorReading(
        sensor_id="humidity",
        metric=Metric.HUMIDITY,
        value=150.0,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert reading.value == 150.0


def test_numeric_range_is_inclusive_and_rejects_empty_range() -> None:
    value_range = NumericRange(low=1.0, high=2.0)

    assert value_range.contains(1.0)
    assert value_range.contains(2.0)
    assert not value_range.contains(2.1)
    with pytest.raises(ValidationError, match="less than"):
        NumericRange(low=2.0, high=2.0)
    with pytest.raises(ValidationError, match="finite"):
        NumericRange(low=1.0, high=float("inf"))


def test_profile_requires_all_targets(tomato_profile: CropProfile) -> None:
    incomplete = dict(tomato_profile.targets)
    incomplete.pop(Metric.LIGHT)

    with pytest.raises(ValidationError, match="every metric"):
        tomato_profile.model_copy(update={"targets": incomplete}).model_validate(
            {
                **tomato_profile.model_dump(),
                "targets": incomplete,
            }
        )


def test_profile_rejects_incoherent_watering_thresholds(
    tomato_profile: CropProfile,
) -> None:
    with pytest.raises(ValidationError, match="soil target"):
        CropProfile(
            slug="tomato",
            display_name="Tomato",
            targets=tomato_profile.targets,
            watering=WateringPolicy(
                trigger_below_pct=45.0,
                stop_at_pct=55.0,
                suggested_duration_seconds=60,
            ),
        )
    with pytest.raises(ValidationError, match="below the stop"):
        WateringPolicy(
            trigger_below_pct=55.0,
            stop_at_pct=55.0,
            suggested_duration_seconds=60,
        )
    with pytest.raises(ValidationError, match="display_name"):
        CropProfile(
            slug="tomato",
            display_name=" ",
            targets=tomato_profile.targets,
            watering=tomato_profile.watering,
        )
    with pytest.raises(ValidationError, match="required_metrics"):
        CropProfile(
            slug="tomato",
            display_name="Tomato",
            targets=tomato_profile.targets,
            watering=tomato_profile.watering,
            required_metrics=frozenset(),
        )
    with pytest.raises(ValidationError, match="every metric"):
        CropProfile(
            slug="tomato",
            display_name="Tomato",
            targets=tomato_profile.targets,
            watering=tomato_profile.watering,
            required_metrics=frozenset({Metric.SOIL_MOISTURE}),
        )
    with pytest.raises(ValidationError, match="high bound"):
        CropProfile(
            slug="tomato",
            display_name="Tomato",
            targets=tomato_profile.targets,
            watering=WateringPolicy(
                trigger_below_pct=40.0,
                stop_at_pct=75.0,
                suggested_duration_seconds=60,
            ),
        )
    with pytest.raises(ValidationError, match="below the soil target low bound"):
        CropProfile(
            slug="tomato",
            display_name="Tomato",
            targets=tomato_profile.targets,
            watering=WateringPolicy(
                trigger_below_pct=30.0,
                stop_at_pct=35.0,
                suggested_duration_seconds=60,
            ),
        )


def test_safety_and_anomaly_policies_require_every_metric() -> None:
    hard_ranges = SafetyPolicy().hard_ranges.copy()
    hard_ranges.pop(Metric.LIGHT)
    with pytest.raises(ValidationError, match="every metric"):
        SafetyPolicy(hard_ranges=hard_ranges)

    anomaly_limits = AnomalyPolicy().metrics.copy()
    anomaly_limits.pop(Metric.LIGHT)
    with pytest.raises(ValidationError, match="every metric"):
        AnomalyPolicy(metrics=anomaly_limits)


def test_anomaly_limits_require_sufficient_window() -> None:
    with pytest.raises(ValidationError, match="at least min_samples"):
        MetricAnomalyLimits(
            min_samples=5,
            window_size=4,
            flat_baseline_delta=2.0,
            max_rate_per_minute=2.0,
        )
    with pytest.raises(ValidationError, match="finite"):
        MetricAnomalyLimits(
            flat_baseline_delta=float("inf"),
            max_rate_per_minute=2.0,
        )


def test_threshold_evidence_requires_kind_specific_values() -> None:
    with pytest.raises(ValidationError, match="requires low"):
        ThresholdEvidence(kind="below")
    with pytest.raises(ValidationError, match="at least two"):
        ThresholdEvidence(kind="conflict", conflicting_values=(1.0,))
    missing_inputs = [
        ("above", "requires high"),
        ("outside", "requires low and high"),
        ("stale", "requires max_age_seconds"),
        ("future", "requires future_tolerance_seconds"),
        ("anomaly", "requires baseline and deviation_limit"),
    ]
    for kind, message in missing_inputs:
        with pytest.raises(ValidationError, match=message):
            ThresholdEvidence.model_validate({"kind": kind})
    with pytest.raises(ValidationError, match="finite"):
        ThresholdEvidence(kind="below", low=float("inf"))
    with pytest.raises(ValidationError, match="finite"):
        ThresholdEvidence(
            kind="conflict",
            conflicting_values=(1.0, float("inf")),
        )


def test_watering_decision_rejects_contradictions() -> None:
    with pytest.raises(ValidationError, match="suggested duration"):
        WateringDecision(
            action=Action.WATER,
            relay_permitted=True,
            reason_codes=("dry",),
        )
    with pytest.raises(ValidationError, match="must not include"):
        WateringDecision(
            action=Action.MONITOR,
            suggested_duration_seconds=10,
            relay_permitted=False,
            reason_codes=("hold",),
        )
    with pytest.raises(ValidationError, match="irrigation action"):
        WateringDecision(
            action=Action.HEAT,
            relay_permitted=False,
            reason_codes=("cold",),
        )
    with pytest.raises(ValidationError, match="both permitted and safety locked"):
        WateringDecision(
            action=Action.WATER,
            suggested_duration_seconds=10,
            relay_permitted=True,
            safety_lock=True,
            reason_codes=("conflict",),
        )
    with pytest.raises(ValidationError, match="only watering"):
        WateringDecision(
            action=Action.STOP_WATER,
            relay_permitted=True,
            reason_codes=("wet",),
        )
    with pytest.raises(ValidationError, match="reason codes"):
        WateringDecision(
            action=Action.MONITOR,
            relay_permitted=False,
            reason_codes=(" ",),
        )


def test_rule_and_anomaly_evidence_reject_invalid_values() -> None:
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    base = {
        "rule_id": "crop.temperature.low",
        "metric": Metric.TEMPERATURE,
        "severity": Severity.WARNING,
        "observed_value": 10.0,
        "observed_at": observed_at,
        "observed_age_seconds": 0.0,
        "threshold": ThresholdEvidence(kind="below", low=18.0),
        "recommendation": "Warm the greenhouse.",
        "action": Action.HEAT,
    }
    with pytest.raises(ValidationError, match="rule text"):
        RuleExplanation.model_validate({**base, "recommendation": " "})
    with pytest.raises(ValidationError, match="observed evidence"):
        RuleExplanation.model_validate({**base, "observed_value": float("inf")})
    with pytest.raises(ValidationError, match="require observed_value"):
        RuleExplanation.model_validate({**base, "observed_value": None})
    with pytest.raises(ValidationError, match="must not be negative"):
        RuleExplanation.model_validate({**base, "observed_age_seconds": -1.0})
    with pytest.raises(ValidationError, match="anomaly evidence"):
        Anomaly(
            metric=Metric.TEMPERATURE,
            kind="zscore",
            observed_value=float("inf"),
            baseline_value=20.0,
            score=4.0,
            threshold_value=3.5,
        )


def test_frozen_clock_is_aware_and_can_advance_or_rollback() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    clock = FrozenClock(start)

    clock.advance(timedelta(seconds=10))
    assert clock.now() == start + timedelta(seconds=10)
    clock.set(start - timedelta(seconds=1))
    assert clock.now() == start - timedelta(seconds=1)
    with pytest.raises(ValueError, match="timezone-aware"):
        FrozenClock(datetime(2026, 1, 1))


def test_system_clock_returns_aware_utc() -> None:
    current = SystemClock().now()

    assert current.tzinfo is UTC
