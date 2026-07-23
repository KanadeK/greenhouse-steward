"""Pure greenhouse safety and crop rule evaluation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime

from greenhouse_steward.domain.anomaly import detect_anomalies
from greenhouse_steward.domain.clock import Clock, require_aware_utc
from greenhouse_steward.domain.models import (
    Action,
    Anomaly,
    AnomalyPolicy,
    CropProfile,
    EvaluationResult,
    Metric,
    RuleExplanation,
    SafetyPolicy,
    SensorReading,
    Severity,
    SystemMode,
    ThresholdEvidence,
    WateringDecision,
)


class RuleEngine:
    """Resolve sensor trust, crop guidance, and irrigation authorization."""

    def __init__(self, clock: Clock) -> None:
        """Create an evaluator with an injectable clock."""

        self._clock = clock

    def evaluate(
        self,
        readings: Sequence[SensorReading],
        profile: CropProfile,
        safety: SafetyPolicy,
        anomaly_policy: AnomalyPolicy | None = None,
    ) -> EvaluationResult:
        """Evaluate all current readings using deterministic fail-safe precedence."""

        now = require_aware_utc(self._clock.now())
        policy = anomaly_policy or AnomalyPolicy()
        latest, conflicts = _select_latest(readings)
        safety_rules: list[RuleExplanation] = []
        offline_metrics: list[Metric] = []
        untrusted_metrics: set[Metric] = set()

        for metric in sorted(profile.required_metrics, key=lambda item: item.value):
            reading = latest.get(metric)
            if reading is None:
                offline_metrics.append(metric)
                untrusted_metrics.add(metric)
                safety_rules.append(_missing_rule(metric))
                continue

            age_seconds = (now - reading.observed_at).total_seconds()
            if age_seconds > safety.offline_after_seconds:
                offline_metrics.append(metric)
                untrusted_metrics.add(metric)
                safety_rules.append(
                    _stale_rule(metric, reading, age_seconds, safety.offline_after_seconds)
                )
                continue
            if age_seconds < -safety.future_tolerance_seconds:
                untrusted_metrics.add(metric)
                safety_rules.append(_future_rule(metric, reading, safety.future_tolerance_seconds))

        for metric, candidates in sorted(conflicts.items(), key=lambda item: item[0].value):
            untrusted_metrics.add(metric)
            safety_rules.append(_conflict_rule(metric, candidates, now))

        for metric, reading in sorted(latest.items(), key=lambda item: item[0].value):
            hard_range = safety.hard_ranges[metric]
            if not hard_range.contains(reading.value):
                untrusted_metrics.add(metric)
                safety_rules.append(
                    RuleExplanation(
                        rule_id=f"sensor.{metric.value}.hard_range",
                        metric=metric,
                        severity=Severity.CRITICAL,
                        observed_value=reading.value,
                        observed_at=reading.observed_at,
                        observed_age_seconds=max(
                            0.0,
                            (now - reading.observed_at).total_seconds(),
                        ),
                        threshold=ThresholdEvidence(
                            kind="outside",
                            low=hard_range.low,
                            high=hard_range.high,
                        ),
                        recommendation=(
                            f"Treat {metric.value} as untrusted and inspect the sensor; "
                            f"the hardware-safe range is {hard_range.low:g} to "
                            f"{hard_range.high:g} {metric.unit}."
                        ),
                        action=Action.CHECK_SENSOR,
                    )
                )

        anomaly_candidates = {
            metric: reading for metric, reading in latest.items() if metric not in untrusted_metrics
        }
        anomalies = detect_anomalies(readings, anomaly_candidates, policy)
        for anomaly in anomalies:
            untrusted_metrics.add(anomaly.metric)
            safety_rules.append(_anomaly_rule(anomaly, latest[anomaly.metric], now))

        if safety_rules:
            reasons = tuple(rule.rule_id for rule in safety_rules)
            watering = WateringDecision(
                action=Action.STOP_WATER,
                suggested_duration_seconds=None,
                relay_permitted=False,
                safety_lock=True,
                reason_codes=reasons,
            )
            return EvaluationResult(
                evaluated_at=now,
                mode=SystemMode.SAFE,
                latest_readings=latest,
                offline_metrics=tuple(offline_metrics),
                anomalies=anomalies,
                rules=tuple(safety_rules),
                watering=watering,
            )

        advisory_rules = _crop_rules(latest, profile, now)
        watering = _watering_decision(latest[Metric.SOIL_MOISTURE], profile)
        mode = SystemMode.ADVISORY if advisory_rules else SystemMode.NORMAL
        return EvaluationResult(
            evaluated_at=now,
            mode=mode,
            latest_readings=latest,
            offline_metrics=(),
            anomalies=anomalies,
            rules=tuple(advisory_rules),
            watering=watering,
        )


def _select_latest(
    readings: Sequence[SensorReading],
) -> tuple[dict[Metric, SensorReading], dict[Metric, tuple[SensorReading, ...]]]:
    """Select current readings and expose ambiguous equal-time observations."""

    grouped: defaultdict[Metric, list[SensorReading]] = defaultdict(list)
    for reading in readings:
        grouped[reading.metric].append(reading)

    latest: dict[Metric, SensorReading] = {}
    conflicts: dict[Metric, tuple[SensorReading, ...]] = {}
    for metric, metric_readings in grouped.items():
        latest_time = max(reading.observed_at for reading in metric_readings)
        candidates = tuple(
            sorted(
                (reading for reading in metric_readings if reading.observed_at == latest_time),
                key=lambda reading: (reading.sensor_id, reading.value),
            )
        )
        latest[metric] = candidates[0]
        if len({reading.value for reading in candidates}) > 1:
            conflicts[metric] = candidates
    return latest, conflicts


def _missing_rule(metric: Metric) -> RuleExplanation:
    """Explain a required metric with no observations."""

    return RuleExplanation(
        rule_id=f"sensor.{metric.value}.missing",
        metric=metric,
        severity=Severity.CRITICAL,
        observed_value=None,
        observed_at=None,
        observed_age_seconds=None,
        threshold=ThresholdEvidence(kind="missing"),
        recommendation=(
            f"Keep irrigation off and restore the {metric.value} sensor before acting."
        ),
        action=Action.CHECK_SENSOR,
    )


def _stale_rule(
    metric: Metric,
    reading: SensorReading,
    age_seconds: float,
    max_age_seconds: int,
) -> RuleExplanation:
    """Explain a stale observation."""

    return RuleExplanation(
        rule_id=f"sensor.{metric.value}.stale",
        metric=metric,
        severity=Severity.CRITICAL,
        observed_value=reading.value,
        observed_at=reading.observed_at,
        observed_age_seconds=age_seconds,
        threshold=ThresholdEvidence(
            kind="stale",
            max_age_seconds=float(max_age_seconds),
        ),
        recommendation=(
            f"Keep irrigation off and restore {metric.value}; the last reading is "
            f"{age_seconds:g} seconds old and the limit is {max_age_seconds} seconds."
        ),
        action=Action.CHECK_SENSOR,
    )


def _future_rule(
    metric: Metric,
    reading: SensorReading,
    tolerance_seconds: int,
) -> RuleExplanation:
    """Explain an implausibly future-dated observation."""

    return RuleExplanation(
        rule_id=f"sensor.{metric.value}.future",
        metric=metric,
        severity=Severity.CRITICAL,
        observed_value=reading.value,
        observed_at=reading.observed_at,
        observed_age_seconds=0.0,
        threshold=ThresholdEvidence(
            kind="future",
            future_tolerance_seconds=float(tolerance_seconds),
        ),
        recommendation=(
            f"Keep irrigation off and correct the clock for {metric.value}; its timestamp "
            f"is beyond the allowed {tolerance_seconds}-second future tolerance."
        ),
        action=Action.CHECK_SENSOR,
    )


def _conflict_rule(
    metric: Metric,
    candidates: tuple[SensorReading, ...],
    now: datetime,
) -> RuleExplanation:
    """Explain contradictory readings at one latest timestamp."""

    selected = candidates[0]
    values = tuple(sorted({reading.value for reading in candidates}))
    return RuleExplanation(
        rule_id=f"sensor.{metric.value}.conflict",
        metric=metric,
        severity=Severity.CRITICAL,
        observed_value=selected.value,
        observed_at=selected.observed_at,
        observed_age_seconds=max(0.0, (now - selected.observed_at).total_seconds()),
        threshold=ThresholdEvidence(
            kind="conflict",
            conflicting_values=values,
        ),
        recommendation=(
            f"Keep irrigation off and reconcile conflicting {metric.value} values "
            f"reported at the same timestamp: {values}."
        ),
        action=Action.CHECK_SENSOR,
    )


def _anomaly_rule(
    anomaly: Anomaly,
    reading: SensorReading,
    now: datetime,
) -> RuleExplanation:
    """Convert anomaly math into the common explanation contract."""

    descriptor = {
        "zscore": "z-score",
        "flat_baseline_jump": "absolute change from a flat baseline",
        "rate_of_change": "rate of change per minute",
    }[anomaly.kind]
    return RuleExplanation(
        rule_id=f"sensor.{anomaly.metric.value}.anomaly.{anomaly.kind}",
        metric=anomaly.metric,
        severity=Severity.CRITICAL,
        observed_value=anomaly.observed_value,
        observed_at=reading.observed_at,
        observed_age_seconds=max(0.0, (now - reading.observed_at).total_seconds()),
        threshold=ThresholdEvidence(
            kind="anomaly",
            baseline=anomaly.baseline_value,
            deviation_limit=anomaly.threshold_value,
        ),
        recommendation=(
            f"Keep irrigation off and inspect {anomaly.metric.value}; its {descriptor} "
            f"met the configured anomaly threshold {anomaly.threshold_value:g}."
        ),
        action=Action.CHECK_SENSOR,
    )


def _crop_rules(
    latest: Mapping[Metric, SensorReading],
    profile: CropProfile,
    now: datetime,
) -> list[RuleExplanation]:
    """Generate crop guidance after all readings have been trusted."""

    rules: list[RuleExplanation] = []
    temperature = latest[Metric.TEMPERATURE]
    temperature_target = profile.targets[Metric.TEMPERATURE]
    if temperature.value < temperature_target.low:
        rules.append(
            _crop_rule(
                "crop.temperature.low",
                temperature,
                now,
                "below",
                temperature_target.low,
                (
                    f"Warm the greenhouse toward at least {temperature_target.low:g} "
                    f"{Metric.TEMPERATURE.unit} for {profile.display_name}."
                ),
                Action.HEAT,
            )
        )
    elif temperature.value > temperature_target.high:
        rules.append(
            _crop_rule(
                "crop.temperature.high",
                temperature,
                now,
                "above",
                temperature_target.high,
                (
                    f"Ventilate or shade until temperature is at most "
                    f"{temperature_target.high:g} {Metric.TEMPERATURE.unit}."
                ),
                Action.VENTILATE,
            )
        )

    humidity = latest[Metric.HUMIDITY]
    humidity_target = profile.targets[Metric.HUMIDITY]
    if humidity.value < humidity_target.low:
        rules.append(
            _crop_rule(
                "crop.humidity.low",
                humidity,
                now,
                "below",
                humidity_target.low,
                (
                    f"Raise humidity toward at least {humidity_target.low:g} "
                    f"{Metric.HUMIDITY.unit}; do not use the irrigation relay for misting."
                ),
                Action.MIST,
            )
        )
    elif humidity.value > humidity_target.high:
        rules.append(
            _crop_rule(
                "crop.humidity.high",
                humidity,
                now,
                "above",
                humidity_target.high,
                (
                    f"Ventilate until humidity is at most {humidity_target.high:g} "
                    f"{Metric.HUMIDITY.unit}."
                ),
                Action.VENTILATE,
            )
        )

    light = latest[Metric.LIGHT]
    light_target = profile.targets[Metric.LIGHT]
    if light.value < light_target.low:
        rules.append(
            _crop_rule(
                "crop.light.low",
                light,
                now,
                "below",
                light_target.low,
                (
                    f"Add light until illumination reaches at least {light_target.low:g} "
                    f"{Metric.LIGHT.unit}."
                ),
                Action.ADD_LIGHT,
            )
        )
    elif light.value > light_target.high:
        rules.append(
            _crop_rule(
                "crop.light.high",
                light,
                now,
                "above",
                light_target.high,
                (
                    f"Add shade until illumination is at most {light_target.high:g} "
                    f"{Metric.LIGHT.unit}."
                ),
                Action.SHADE,
            )
        )

    soil = latest[Metric.SOIL_MOISTURE]
    if soil.value < profile.watering.trigger_below_pct:
        rules.append(
            _crop_rule(
                "crop.soil_moisture.low",
                soil,
                now,
                "below",
                profile.watering.trigger_below_pct,
                (
                    f"Water for up to {profile.watering.suggested_duration_seconds} seconds, "
                    f"subject to the relay safety cap; observed {soil.value:g} "
                    f"{Metric.SOIL_MOISTURE.unit} is below "
                    f"{profile.watering.trigger_below_pct:g} "
                    f"{Metric.SOIL_MOISTURE.unit}."
                ),
                Action.WATER,
            )
        )
    elif soil.value >= profile.watering.stop_at_pct:
        rules.append(
            _crop_rule(
                "crop.soil_moisture.stop",
                soil,
                now,
                "above",
                profile.watering.stop_at_pct,
                (
                    f"Keep irrigation off because soil moisture is at or above "
                    f"{profile.watering.stop_at_pct:g} {Metric.SOIL_MOISTURE.unit}."
                ),
                Action.STOP_WATER,
            )
        )
    return rules


def _crop_rule(
    rule_id: str,
    reading: SensorReading,
    now: datetime,
    comparison: str,
    threshold: float,
    recommendation: str,
    action: Action,
) -> RuleExplanation:
    """Build one low/high crop rule with common evidence."""

    evidence = (
        ThresholdEvidence(kind="below", low=threshold)
        if comparison == "below"
        else ThresholdEvidence(kind="above", high=threshold)
    )
    return RuleExplanation(
        rule_id=rule_id,
        metric=reading.metric,
        severity=Severity.WARNING,
        observed_value=reading.value,
        observed_at=reading.observed_at,
        observed_age_seconds=max(0.0, (now - reading.observed_at).total_seconds()),
        threshold=evidence,
        recommendation=recommendation,
        action=action,
    )


def _watering_decision(
    soil: SensorReading,
    profile: CropProfile,
) -> WateringDecision:
    """Resolve one non-conflicting watering recommendation."""

    if soil.value < profile.watering.trigger_below_pct:
        return WateringDecision(
            action=Action.WATER,
            suggested_duration_seconds=profile.watering.suggested_duration_seconds,
            relay_permitted=True,
            safety_lock=False,
            reason_codes=("soil_below_watering_trigger",),
        )
    if soil.value >= profile.watering.stop_at_pct:
        return WateringDecision(
            action=Action.STOP_WATER,
            suggested_duration_seconds=None,
            relay_permitted=False,
            safety_lock=False,
            reason_codes=("soil_at_or_above_stop_threshold",),
        )
    return WateringDecision(
        action=Action.MONITOR,
        suggested_duration_seconds=None,
        relay_permitted=False,
        safety_lock=False,
        reason_codes=("soil_moisture_in_hold_band",),
    )
