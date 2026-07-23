"""Pure, offline-testable greenhouse domain core."""

from greenhouse_steward.domain.anomaly import detect_anomalies
from greenhouse_steward.domain.clock import Clock, FrozenClock, SystemClock
from greenhouse_steward.domain.models import (
    Action,
    Anomaly,
    AnomalyPolicy,
    CropProfile,
    EvaluationResult,
    Metric,
    MetricAnomalyLimits,
    NumericRange,
    RuleExplanation,
    SafetyPolicy,
    SensorReading,
    Severity,
    SystemMode,
    ThresholdEvidence,
    WateringDecision,
    WateringPolicy,
)
from greenhouse_steward.domain.relay import RelaySimulator, RelaySnapshot, RelayState
from greenhouse_steward.domain.rules import RuleEngine
from greenhouse_steward.domain.trends import (
    PeriodAggregate,
    TrendDirection,
    TrendReport,
    build_trends,
)

__all__ = [
    "Action",
    "Anomaly",
    "AnomalyPolicy",
    "Clock",
    "CropProfile",
    "EvaluationResult",
    "FrozenClock",
    "Metric",
    "MetricAnomalyLimits",
    "NumericRange",
    "PeriodAggregate",
    "RelaySimulator",
    "RelaySnapshot",
    "RelayState",
    "RuleEngine",
    "RuleExplanation",
    "SafetyPolicy",
    "SensorReading",
    "Severity",
    "SystemClock",
    "SystemMode",
    "ThresholdEvidence",
    "TrendDirection",
    "TrendReport",
    "WateringDecision",
    "WateringPolicy",
    "build_trends",
    "detect_anomalies",
]
