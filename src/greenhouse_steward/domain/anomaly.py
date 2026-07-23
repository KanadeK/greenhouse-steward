"""Deterministic, explainable anomaly detection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from statistics import fmean, pstdev

from greenhouse_steward.domain.models import (
    Anomaly,
    AnomalyPolicy,
    Metric,
    SensorReading,
)

_FLAT_EPSILON = 1e-12


def detect_anomalies(
    history: Sequence[SensorReading],
    current: Mapping[Metric, SensorReading],
    policy: AnomalyPolicy,
) -> tuple[Anomaly, ...]:
    """Compare each current reading with earlier values from the same metric.

    The current point is excluded from its own baseline even if callers pass a
    combined history. Statistical and rate anomalies are reported separately
    so downstream explanations retain the exact threshold that fired.
    """

    anomalies: list[Anomaly] = []
    for metric in sorted(current, key=lambda item: item.value):
        current_reading = current[metric]
        limits = policy.metrics[metric]
        candidates = sorted(
            (
                reading
                for reading in history
                if reading.metric == metric
                and reading.sensor_id == current_reading.sensor_id
                and reading.observed_at < current_reading.observed_at
            ),
            key=lambda reading: (reading.observed_at, reading.sensor_id, reading.value),
        )
        window = candidates[-limits.window_size :]
        if len(window) < limits.min_samples:
            continue

        values = [reading.value for reading in window]
        baseline = fmean(values)
        deviation = pstdev(values)
        delta = abs(current_reading.value - baseline)
        if deviation > _FLAT_EPSILON:
            score = abs(current_reading.value - baseline) / deviation
            if score >= limits.zscore_threshold:
                anomalies.append(
                    Anomaly(
                        metric=metric,
                        kind="zscore",
                        observed_value=current_reading.value,
                        baseline_value=baseline,
                        score=score,
                        threshold_value=limits.zscore_threshold,
                    )
                )
        elif delta >= limits.flat_baseline_delta:
            anomalies.append(
                Anomaly(
                    metric=metric,
                    kind="flat_baseline_jump",
                    observed_value=current_reading.value,
                    baseline_value=baseline,
                    score=None,
                    threshold_value=limits.flat_baseline_delta,
                )
            )

        previous = window[-1]
        elapsed_minutes = (
            current_reading.observed_at - previous.observed_at
        ).total_seconds() / 60.0
        if elapsed_minutes > 0:
            rate = abs(current_reading.value - previous.value) / elapsed_minutes
            if rate >= limits.max_rate_per_minute:
                anomalies.append(
                    Anomaly(
                        metric=metric,
                        kind="rate_of_change",
                        observed_value=current_reading.value,
                        baseline_value=previous.value,
                        score=rate,
                        threshold_value=limits.max_rate_per_minute,
                    )
                )

    return tuple(anomalies)
