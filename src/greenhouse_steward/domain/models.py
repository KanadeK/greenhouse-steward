"""Validated data contracts for the greenhouse domain."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class DomainModel(BaseModel):
    """Immutable base model used by the pure domain layer."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Metric(StrEnum):
    """Canonical measurements understood by Greenhouse Steward."""

    TEMPERATURE = "temperature_c"
    HUMIDITY = "humidity_pct"
    SOIL_MOISTURE = "soil_moisture_pct"
    LIGHT = "light_lux"

    @property
    def unit(self) -> str:
        """Return the canonical unit stored for the metric."""

        return {
            Metric.TEMPERATURE: "°C",
            Metric.HUMIDITY: "%",
            Metric.SOIL_MOISTURE: "%",
            Metric.LIGHT: "lux",
        }[self]


class Action(StrEnum):
    """Actions that a rule may recommend."""

    MONITOR = "monitor"
    WATER = "water"
    STOP_WATER = "stop_water"
    VENTILATE = "ventilate"
    HEAT = "heat"
    MIST = "mist"
    SHADE = "shade"
    ADD_LIGHT = "add_light"
    CHECK_SENSOR = "check_sensor"


class SystemMode(StrEnum):
    """Trust and safety mode of an evaluated greenhouse snapshot."""

    NORMAL = "normal"
    ADVISORY = "advisory"
    SAFE = "safe"


class Severity(StrEnum):
    """Severity attached to a rule explanation."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class SensorReading(DomainModel):
    """One timestamped reading in its metric's canonical unit."""

    sensor_id: str = Field(min_length=1, max_length=128)
    metric: Metric
    value: float
    observed_at: AwareDatetime

    @field_validator("value", mode="before")
    @classmethod
    def reject_boolean_value(cls, value: object) -> object:
        """Reject booleans before Pydantic can coerce them to zero or one."""

        if isinstance(value, bool):
            raise ValueError("reading value must be numeric, not boolean")
        return value

    @field_validator("sensor_id")
    @classmethod
    def normalize_sensor_id(cls, value: str) -> str:
        """Reject identifiers that contain only whitespace."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("sensor_id must not be blank")
        return normalized

    @field_validator("value")
    @classmethod
    def validate_finite_value(cls, value: float) -> float:
        """Reject non-finite values while retaining explainable out-of-range values."""

        if not isfinite(value):
            raise ValueError("reading value must be finite")
        return value

    @field_validator("observed_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        """Store all sensor timestamps in UTC."""

        return value.astimezone(UTC)


class NumericRange(DomainModel):
    """Inclusive numeric range used for targets and hard safety limits."""

    low: float
    high: float

    @field_validator("low", "high")
    @classmethod
    def validate_finite_bound(cls, value: float) -> float:
        """Require finite bounds."""

        if not isfinite(value):
            raise ValueError("range bounds must be finite")
        return value

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        """Require a non-empty range."""

        if self.low >= self.high:
            raise ValueError("range low must be less than range high")
        return self

    def contains(self, value: float) -> bool:
        """Return whether a value lies inside the inclusive range."""

        return self.low <= value <= self.high


class WateringPolicy(DomainModel):
    """Crop-specific soil moisture rules."""

    trigger_below_pct: float = Field(ge=0.0, le=100.0)
    stop_at_pct: float = Field(ge=0.0, le=100.0)
    suggested_duration_seconds: int = Field(ge=1, le=86_400)

    @model_validator(mode="after")
    def validate_threshold_order(self) -> Self:
        """Ensure the stop threshold is above the start threshold."""

        if self.trigger_below_pct >= self.stop_at_pct:
            raise ValueError("watering trigger must be below the stop threshold")
        return self


class CropProfile(DomainModel):
    """Editable crop target ranges and watering behavior."""

    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    targets: dict[Metric, NumericRange]
    watering: WateringPolicy
    required_metrics: frozenset[Metric] = Field(default_factory=lambda: frozenset(Metric))

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        """Reject display names that contain only whitespace."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("display_name must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        """Require complete targets and internally coherent soil thresholds."""

        expected = set(Metric)
        if set(self.targets) != expected:
            missing = sorted(metric.value for metric in expected - set(self.targets))
            extra = sorted(metric.value for metric in set(self.targets) - expected)
            raise ValueError(f"targets must contain every metric; missing={missing}, extra={extra}")
        if set(self.required_metrics) != expected:
            raise ValueError("required_metrics must contain every metric")
        soil_target = self.targets[Metric.SOIL_MOISTURE]
        if self.watering.trigger_below_pct > soil_target.low:
            raise ValueError("watering trigger must not exceed the soil target low bound")
        if self.watering.stop_at_pct < soil_target.low:
            raise ValueError("watering stop threshold must not be below the soil target low bound")
        if self.watering.stop_at_pct > soil_target.high:
            raise ValueError("watering stop threshold must not exceed the soil target high bound")
        return self


def default_hard_ranges() -> dict[Metric, NumericRange]:
    """Return conservative, editable input trust boundaries."""

    return {
        Metric.TEMPERATURE: NumericRange(low=-20.0, high=60.0),
        Metric.HUMIDITY: NumericRange(low=0.0, high=100.0),
        Metric.SOIL_MOISTURE: NumericRange(low=0.0, high=100.0),
        Metric.LIGHT: NumericRange(low=0.0, high=200_000.0),
    }


class SafetyPolicy(DomainModel):
    """Fail-safe limits that override crop preferences."""

    offline_after_seconds: int = Field(default=300, ge=1, le=86_400)
    future_tolerance_seconds: int = Field(default=30, ge=0, le=3_600)
    relay_max_on_seconds: int = Field(default=120, ge=1, le=3_600)
    hard_ranges: dict[Metric, NumericRange] = Field(default_factory=default_hard_ranges)

    @model_validator(mode="after")
    def validate_hard_ranges(self) -> Self:
        """Require a hard range for every supported metric."""

        if set(self.hard_ranges) != set(Metric):
            raise ValueError("hard_ranges must contain every metric")
        return self


class MetricAnomalyLimits(DomainModel):
    """Deterministic anomaly limits for one metric."""

    min_samples: int = Field(default=6, ge=2, le=10_000)
    window_size: int = Field(default=24, ge=2, le=10_000)
    zscore_threshold: float = Field(default=3.5, gt=0.0)
    flat_baseline_delta: float = Field(gt=0.0)
    max_rate_per_minute: float = Field(gt=0.0)

    @field_validator("zscore_threshold", "flat_baseline_delta", "max_rate_per_minute")
    @classmethod
    def validate_finite_limit(cls, value: float) -> float:
        """Reject infinite anomaly limits."""

        if not isfinite(value):
            raise ValueError("anomaly limits must be finite")
        return value

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        """Ensure the rolling window can satisfy the minimum sample count."""

        if self.window_size < self.min_samples:
            raise ValueError("window_size must be at least min_samples")
        return self


def default_anomaly_limits() -> dict[Metric, MetricAnomalyLimits]:
    """Return transparent defaults suitable for the bundled synthetic data."""

    return {
        Metric.TEMPERATURE: MetricAnomalyLimits(
            flat_baseline_delta=5.0,
            max_rate_per_minute=4.0,
        ),
        Metric.HUMIDITY: MetricAnomalyLimits(
            flat_baseline_delta=15.0,
            max_rate_per_minute=15.0,
        ),
        Metric.SOIL_MOISTURE: MetricAnomalyLimits(
            flat_baseline_delta=15.0,
            max_rate_per_minute=12.0,
        ),
        Metric.LIGHT: MetricAnomalyLimits(
            flat_baseline_delta=20_000.0,
            max_rate_per_minute=30_000.0,
        ),
    }


class AnomalyPolicy(DomainModel):
    """Per-metric rolling anomaly configuration."""

    metrics: dict[Metric, MetricAnomalyLimits] = Field(default_factory=default_anomaly_limits)

    @model_validator(mode="after")
    def validate_metrics(self) -> Self:
        """Require anomaly limits for every metric."""

        if set(self.metrics) != set(Metric):
            raise ValueError("anomaly policy must contain every metric")
        return self


ThresholdKind = Literal[
    "below",
    "above",
    "outside",
    "stale",
    "missing",
    "future",
    "conflict",
    "anomaly",
]


class ThresholdEvidence(DomainModel):
    """Machine-readable threshold evidence behind an explanation."""

    kind: ThresholdKind
    low: float | None = None
    high: float | None = None
    max_age_seconds: float | None = None
    future_tolerance_seconds: float | None = None
    baseline: float | None = None
    deviation_limit: float | None = None
    conflicting_values: tuple[float, ...] = ()

    @field_validator(
        "low",
        "high",
        "max_age_seconds",
        "future_tolerance_seconds",
        "baseline",
        "deviation_limit",
    )
    @classmethod
    def validate_optional_finite_value(cls, value: float | None) -> float | None:
        """Require finite evidence values when present."""

        if value is not None and not isfinite(value):
            raise ValueError("threshold evidence must be finite")
        return value

    @field_validator("conflicting_values")
    @classmethod
    def validate_conflicting_values(cls, values: tuple[float, ...]) -> tuple[float, ...]:
        """Require finite conflicting observations."""

        if any(not isfinite(value) for value in values):
            raise ValueError("conflicting values must be finite")
        return values

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> Self:
        """Make each evidence kind carry the threshold needed to explain it."""

        if self.kind == "below" and self.low is None:
            raise ValueError("below evidence requires low")
        if self.kind == "above" and self.high is None:
            raise ValueError("above evidence requires high")
        if self.kind == "outside" and (self.low is None or self.high is None):
            raise ValueError("outside evidence requires low and high")
        if self.kind == "stale" and self.max_age_seconds is None:
            raise ValueError("stale evidence requires max_age_seconds")
        if self.kind == "future" and self.future_tolerance_seconds is None:
            raise ValueError("future evidence requires future_tolerance_seconds")
        if self.kind == "conflict" and len(self.conflicting_values) < 2:
            raise ValueError("conflict evidence requires at least two values")
        if self.kind == "anomaly" and (self.baseline is None or self.deviation_limit is None):
            raise ValueError("anomaly evidence requires baseline and deviation_limit")
        return self


class RuleExplanation(DomainModel):
    """One rule hit with its observed input, threshold, and recommendation."""

    rule_id: str = Field(min_length=1, max_length=128)
    metric: Metric
    severity: Severity
    observed_value: float | None
    observed_at: AwareDatetime | None
    observed_age_seconds: float | None
    threshold: ThresholdEvidence
    recommendation: str = Field(min_length=1, max_length=512)
    action: Action

    @field_validator("rule_id", "recommendation")
    @classmethod
    def normalize_non_blank_text(cls, value: str) -> str:
        """Reject explanations that are visually empty."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("rule text must not be blank")
        return normalized

    @field_validator("observed_value", "observed_age_seconds")
    @classmethod
    def validate_optional_observation(cls, value: float | None) -> float | None:
        """Require finite observed values and ages."""

        if value is not None and not isfinite(value):
            raise ValueError("observed evidence must be finite")
        return value

    @field_validator("observed_at")
    @classmethod
    def normalize_optional_timestamp(cls, value: datetime | None) -> datetime | None:
        """Store explanation timestamps in UTC."""

        return None if value is None else value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_observation_presence(self) -> Self:
        """Only a truly missing reading may omit its observed value."""

        if self.threshold.kind != "missing" and self.observed_value is None:
            raise ValueError("non-missing rules require observed_value")
        if self.observed_age_seconds is not None and self.observed_age_seconds < 0:
            raise ValueError("observed age must not be negative")
        return self


AnomalyKind = Literal["zscore", "flat_baseline_jump", "rate_of_change"]


class Anomaly(DomainModel):
    """A reproducible anomaly calculation result."""

    metric: Metric
    kind: AnomalyKind
    observed_value: float
    baseline_value: float
    score: float | None
    threshold_value: float

    @field_validator("observed_value", "baseline_value", "score", "threshold_value")
    @classmethod
    def validate_anomaly_number(cls, value: float | None) -> float | None:
        """Reject non-finite anomaly evidence."""

        if value is not None and not isfinite(value):
            raise ValueError("anomaly evidence must be finite")
        return value


class WateringDecision(DomainModel):
    """Resolved irrigation guidance and relay authorization."""

    action: Action
    suggested_duration_seconds: int | None = Field(default=None, ge=1, le=86_400)
    relay_permitted: bool
    safety_lock: bool = False
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @field_validator("reason_codes")
    @classmethod
    def validate_reason_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Require stable, non-empty machine-readable reasons."""

        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("reason codes must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_watering_decision(self) -> Self:
        """Prevent contradictory relay authorizations."""

        permitted_actions = {Action.WATER, Action.STOP_WATER, Action.MONITOR}
        if self.action not in permitted_actions:
            raise ValueError("watering decision action is not an irrigation action")
        if self.action == Action.WATER:
            if self.suggested_duration_seconds is None:
                raise ValueError("watering decisions require a suggested duration")
            if not self.relay_permitted or self.safety_lock:
                raise ValueError("watering cannot be both permitted and safety locked")
        elif self.suggested_duration_seconds is not None:
            raise ValueError("non-watering decisions must not include a duration")
        if self.relay_permitted and self.action != Action.WATER:
            raise ValueError("only watering actions may permit the relay")
        return self


class EvaluationResult(DomainModel):
    """Complete output of one deterministic rule evaluation."""

    evaluated_at: AwareDatetime
    mode: SystemMode
    latest_readings: dict[Metric, SensorReading]
    offline_metrics: tuple[Metric, ...]
    anomalies: tuple[Anomaly, ...]
    rules: tuple[RuleExplanation, ...]
    watering: WateringDecision

    @field_validator("evaluated_at")
    @classmethod
    def normalize_evaluated_at(cls, value: datetime) -> datetime:
        """Store the evaluation time in UTC."""

        return value.astimezone(UTC)
