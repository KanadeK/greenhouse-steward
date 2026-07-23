"""Boundary and precedence tests for the greenhouse rule engine."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from greenhouse_steward.domain import (
    Action,
    AnomalyPolicy,
    CropProfile,
    FrozenClock,
    Metric,
    MetricAnomalyLimits,
    RuleEngine,
    SafetyPolicy,
    SensorReading,
    SystemMode,
)


def _replace_reading(
    readings: list[SensorReading],
    metric: Metric,
    *,
    value: float | None = None,
    observed_at: datetime | None = None,
    sensor_id: str | None = None,
) -> list[SensorReading]:
    result: list[SensorReading] = []
    for reading in readings:
        if reading.metric != metric:
            result.append(reading)
            continue
        result.append(
            SensorReading(
                sensor_id=sensor_id or reading.sensor_id,
                metric=metric,
                value=reading.value if value is None else value,
                observed_at=observed_at or reading.observed_at,
            )
        )
    return result


def test_dry_soil_rule_contains_observation_threshold_and_recommendation(
    clock: FrozenClock,
    fresh_readings: list[SensorReading],
    tomato_profile: CropProfile,
    safety_policy: SafetyPolicy,
) -> None:
    readings = _replace_reading(fresh_readings, Metric.SOIL_MOISTURE, value=39.0)

    result = RuleEngine(clock).evaluate(readings, tomato_profile, safety_policy)

    hit = next(rule for rule in result.rules if rule.rule_id == "crop.soil_moisture.low")
    assert result.mode == SystemMode.ADVISORY
    assert result.watering.action == Action.WATER
    assert result.watering.relay_permitted
    assert result.watering.suggested_duration_seconds == 180
    assert hit.observed_value == 39.0
    assert hit.threshold.low == 40.0
    assert hit.recommendation
    serialized = hit.model_dump(mode="json")
    assert serialized["observed_value"] == 39.0
    assert serialized["threshold"]["low"] == 40.0
    assert serialized["recommendation"]


def test_watering_trigger_boundary_is_strictly_below(
    clock: FrozenClock,
    fresh_readings: list[SensorReading],
    tomato_profile: CropProfile,
    safety_policy: SafetyPolicy,
) -> None:
    readings = _replace_reading(fresh_readings, Metric.SOIL_MOISTURE, value=40.0)

    result = RuleEngine(clock).evaluate(readings, tomato_profile, safety_policy)

    assert result.mode == SystemMode.NORMAL
    assert result.watering.action == Action.MONITOR
    assert result.rules == ()


def test_stop_threshold_is_inclusive(
    clock: FrozenClock,
    fresh_readings: list[SensorReading],
    tomato_profile: CropProfile,
    safety_policy: SafetyPolicy,
) -> None:
    readings = _replace_reading(fresh_readings, Metric.SOIL_MOISTURE, value=55.0)

    result = RuleEngine(clock).evaluate(readings, tomato_profile, safety_policy)

    hit = next(rule for rule in result.rules if rule.rule_id == "crop.soil_moisture.stop")
    assert result.watering.action == Action.STOP_WATER
    assert not result.watering.relay_permitted
    assert hit.observed_value == 55.0
    assert hit.threshold.high == 55.0


@pytest.mark.parametrize(
    ("metric", "value", "rule_id", "action"),
    [
        (Metric.TEMPERATURE, 17.0, "crop.temperature.low", Action.HEAT),
        (Metric.TEMPERATURE, 29.0, "crop.temperature.high", Action.VENTILATE),
        (Metric.HUMIDITY, 54.0, "crop.humidity.low", Action.MIST),
        (Metric.HUMIDITY, 76.0, "crop.humidity.high", Action.VENTILATE),
        (Metric.LIGHT, 9_999.0, "crop.light.low", Action.ADD_LIGHT),
        (Metric.LIGHT, 50_001.0, "crop.light.high", Action.SHADE),
    ],
)
def test_environmental_crop_threshold_actions(
    metric: Metric,
    value: float,
    rule_id: str,
    action: Action,
    clock: FrozenClock,
    fresh_readings: list[SensorReading],
    tomato_profile: CropProfile,
    safety_policy: SafetyPolicy,
) -> None:
    readings = _replace_reading(fresh_readings, metric, value=value)

    result = RuleEngine(clock).evaluate(readings, tomato_profile, safety_policy)

    hit = next(rule for rule in result.rules if rule.rule_id == rule_id)
    assert result.mode == SystemMode.ADVISORY
    assert hit.action == action
    assert hit.observed_value == value
    assert hit.recommendation


def test_missing_required_sensor_enters_safe_state(
    clock: FrozenClock,
    fresh_readings: list[SensorReading],
    tomato_profile: CropProfile,
    safety_policy: SafetyPolicy,
) -> None:
    readings = [reading for reading in fresh_readings if reading.metric != Metric.LIGHT]

    result = RuleEngine(clock).evaluate(readings, tomato_profile, safety_policy)

    assert result.mode == SystemMode.SAFE
    assert result.offline_metrics == (Metric.LIGHT,)
    assert result.watering.action == Action.STOP_WATER
    assert not result.watering.relay_permitted
    assert result.watering.safety_lock
    hit = next(rule for rule in result.rules if rule.metric == Metric.LIGHT)
    assert hit.threshold.kind == "missing"
    assert hit.observed_value is None


def test_empty_input_reports_every_required_metric_offline(
    clock: FrozenClock,
    tomato_profile: CropProfile,
    safety_policy: SafetyPolicy,
) -> None:
    result = RuleEngine(clock).evaluate([], tomato_profile, safety_policy)

    assert set(result.offline_metrics) == set(Metric)
    assert len(result.rules) == len(Metric)
    assert result.latest_readings == {}


def test_freshness_boundary_is_inclusive(
    now: datetime,
    clock: FrozenClock,
    fresh_readings: list[SensorReading],
    tomato_profile: CropProfile,
    safety_policy: SafetyPolicy,
) -> None:
    exactly_fresh = [
        SensorReading(
            sensor_id=reading.sensor_id,
            metric=reading.metric,
            value=reading.value,
            observed_at=now - timedelta(seconds=300),
        )
        for reading in fresh_readings
    ]
    stale = _replace_reading(
        exactly_fresh,
        Metric.LIGHT,
        observed_at=now - timedelta(seconds=300, microseconds=1),
    )

    fresh_result = RuleEngine(clock).evaluate(
        exactly_fresh,
        tomato_profile,
        safety_policy,
    )
    stale_result = RuleEngine(clock).evaluate(stale, tomato_profile, safety_policy)

    assert fresh_result.mode == SystemMode.NORMAL
    assert stale_result.mode == SystemMode.SAFE
    stale_hit = next(
        rule for rule in stale_result.rules if rule.rule_id == "sensor.light_lux.stale"
    )
    assert stale_hit.observed_age_seconds == pytest.approx(300.000001)
    assert stale_hit.threshold.max_age_seconds == 300.0


def test_input_order_does_not_change_latest_selection(
    now: datetime,
    clock: FrozenClock,
    fresh_readings: list[SensorReading],
    tomato_profile: CropProfile,
    safety_policy: SafetyPolicy,
) -> None:
    older_dry_soil = SensorReading(
        sensor_id="soil-old",
        metric=Metric.SOIL_MOISTURE,
        value=10.0,
        observed_at=now - timedelta(seconds=10),
    )
    first = [older_dry_soil, *fresh_readings]
    second = [*reversed(fresh_readings), older_dry_soil]

    first_result = RuleEngine(clock).evaluate(first, tomato_profile, safety_policy)
    second_result = RuleEngine(clock).evaluate(second, tomato_profile, safety_policy)

    assert first_result.watering.action == Action.MONITOR
    assert second_result.watering == first_result.watering
    assert first_result.latest_readings[Metric.SOIL_MOISTURE].value == 47.0


def test_same_timestamp_conflict_is_fail_safe(
    now: datetime,
    clock: FrozenClock,
    fresh_readings: list[SensorReading],
    tomato_profile: CropProfile,
    safety_policy: SafetyPolicy,
) -> None:
    conflict = SensorReading(
        sensor_id="soil-conflict",
        metric=Metric.SOIL_MOISTURE,
        value=20.0,
        observed_at=now,
    )

    result = RuleEngine(clock).evaluate(
        [*fresh_readings, conflict],
        tomato_profile,
        safety_policy,
    )

    assert result.mode == SystemMode.SAFE
    hit = next(rule for rule in result.rules if rule.rule_id == "sensor.soil_moisture_pct.conflict")
    assert hit.threshold.conflicting_values == (20.0, 47.0)
    assert result.watering.safety_lock


def test_hard_range_violation_preserves_bad_observed_value(
    clock: FrozenClock,
    fresh_readings: list[SensorReading],
    tomato_profile: CropProfile,
    safety_policy: SafetyPolicy,
) -> None:
    readings = _replace_reading(fresh_readings, Metric.HUMIDITY, value=101.0)

    result = RuleEngine(clock).evaluate(readings, tomato_profile, safety_policy)

    hit = next(rule for rule in result.rules if rule.rule_id == "sensor.humidity_pct.hard_range")
    assert result.mode == SystemMode.SAFE
    assert hit.observed_value == 101.0
    assert hit.threshold.low == 0.0
    assert hit.threshold.high == 100.0


def test_future_tolerance_boundary_and_excess(
    now: datetime,
    clock: FrozenClock,
    fresh_readings: list[SensorReading],
    tomato_profile: CropProfile,
    safety_policy: SafetyPolicy,
) -> None:
    at_limit = _replace_reading(
        fresh_readings,
        Metric.LIGHT,
        observed_at=now + timedelta(seconds=30),
    )
    beyond_limit = _replace_reading(
        fresh_readings,
        Metric.LIGHT,
        observed_at=now + timedelta(seconds=30, microseconds=1),
    )

    accepted = RuleEngine(clock).evaluate(at_limit, tomato_profile, safety_policy)
    rejected = RuleEngine(clock).evaluate(beyond_limit, tomato_profile, safety_policy)

    assert accepted.mode == SystemMode.NORMAL
    assert rejected.mode == SystemMode.SAFE
    hit = next(rule for rule in rejected.rules if rule.rule_id == "sensor.light_lux.future")
    assert hit.observed_age_seconds == 0.0
    assert hit.threshold.future_tolerance_seconds == 30.0


def test_safe_state_overrides_dry_soil_watering(
    clock: FrozenClock,
    fresh_readings: list[SensorReading],
    tomato_profile: CropProfile,
    safety_policy: SafetyPolicy,
) -> None:
    readings = _replace_reading(fresh_readings, Metric.SOIL_MOISTURE, value=20.0)
    readings = [reading for reading in readings if reading.metric != Metric.LIGHT]

    result = RuleEngine(clock).evaluate(readings, tomato_profile, safety_policy)

    assert result.mode == SystemMode.SAFE
    assert result.watering.action == Action.STOP_WATER
    assert not any(rule.action == Action.WATER for rule in result.rules)


def test_anomaly_enters_safe_state_with_explainable_evidence(
    now: datetime,
    clock: FrozenClock,
    fresh_readings: list[SensorReading],
    tomato_profile: CropProfile,
    safety_policy: SafetyPolicy,
) -> None:
    baseline = [
        SensorReading(
            sensor_id="temperature-1",
            metric=Metric.TEMPERATURE,
            value=20.0,
            observed_at=now - timedelta(minutes=minute),
        )
        for minute in (4, 3, 2)
    ]
    current = _replace_reading(fresh_readings, Metric.TEMPERATURE, value=25.0)
    permissive = MetricAnomalyLimits(
        min_samples=3,
        window_size=3,
        flat_baseline_delta=5.0,
        max_rate_per_minute=1_000.0,
    )
    anomaly_policy = AnomalyPolicy(metrics={metric: permissive for metric in Metric})

    result = RuleEngine(clock).evaluate(
        [*baseline, *current],
        tomato_profile,
        safety_policy,
        anomaly_policy,
    )

    assert result.mode == SystemMode.SAFE
    assert result.anomalies[0].kind == "flat_baseline_jump"
    hit = next(rule for rule in result.rules if ".anomaly." in rule.rule_id)
    assert hit.observed_value == 25.0
    assert hit.threshold.baseline == 20.0
    assert hit.threshold.deviation_limit == 5.0


def test_multiple_advisories_are_retained_with_one_watering_decision(
    clock: FrozenClock,
    fresh_readings: list[SensorReading],
    tomato_profile: CropProfile,
    safety_policy: SafetyPolicy,
) -> None:
    readings = _replace_reading(fresh_readings, Metric.TEMPERATURE, value=10.0)
    readings = _replace_reading(readings, Metric.HUMIDITY, value=90.0)
    readings = _replace_reading(readings, Metric.LIGHT, value=1_000.0)
    readings = _replace_reading(readings, Metric.SOIL_MOISTURE, value=30.0)

    result = RuleEngine(clock).evaluate(readings, tomato_profile, safety_policy)

    assert result.mode == SystemMode.ADVISORY
    assert {rule.action for rule in result.rules} == {
        Action.HEAT,
        Action.VENTILATE,
        Action.ADD_LIGHT,
        Action.WATER,
    }
    assert result.watering.action == Action.WATER
