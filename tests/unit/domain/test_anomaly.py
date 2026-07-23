"""Tests for deterministic anomaly math."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from greenhouse_steward.domain import (
    AnomalyPolicy,
    Metric,
    MetricAnomalyLimits,
    SensorReading,
    detect_anomalies,
)


def _reading(
    metric: Metric,
    value: float,
    minute: int,
    *,
    sensor_id: str | None = None,
) -> SensorReading:
    return SensorReading(
        sensor_id=sensor_id or f"{metric.value}-sensor",
        metric=metric,
        value=value,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minute),
    )


def _policy(
    *,
    min_samples: int = 3,
    window_size: int = 8,
    zscore: float = 3.5,
    flat_delta: float = 5.0,
    max_rate: float = 1_000.0,
) -> AnomalyPolicy:
    limit = MetricAnomalyLimits(
        min_samples=min_samples,
        window_size=window_size,
        zscore_threshold=zscore,
        flat_baseline_delta=flat_delta,
        max_rate_per_minute=max_rate,
    )
    return AnomalyPolicy(metrics={metric: limit for metric in Metric})


def test_insufficient_history_does_not_invent_anomaly() -> None:
    current = _reading(Metric.TEMPERATURE, 40.0, 3)
    history = [_reading(Metric.TEMPERATURE, 20.0, 1)]

    assert (
        detect_anomalies(
            history,
            {Metric.TEMPERATURE: current},
            _policy(),
        )
        == ()
    )


def test_flat_baseline_same_value_is_normal() -> None:
    current = _reading(Metric.TEMPERATURE, 20.0, 4)
    history = [_reading(Metric.TEMPERATURE, 20.0, minute) for minute in range(1, 4)]

    assert (
        detect_anomalies(
            history,
            {Metric.TEMPERATURE: current},
            _policy(),
        )
        == ()
    )


def test_flat_baseline_jump_is_explained_without_division_by_zero() -> None:
    current = _reading(Metric.TEMPERATURE, 25.0, 4)
    history = [_reading(Metric.TEMPERATURE, 20.0, minute) for minute in range(1, 4)]

    anomalies = detect_anomalies(
        history,
        {Metric.TEMPERATURE: current},
        _policy(flat_delta=5.0),
    )

    assert len(anomalies) == 1
    assert anomalies[0].kind == "flat_baseline_jump"
    assert anomalies[0].baseline_value == 20.0
    assert anomalies[0].threshold_value == 5.0
    assert anomalies[0].score is None


def test_exact_zscore_threshold_is_an_anomaly() -> None:
    current = _reading(Metric.TEMPERATURE, 2.0, 3)
    history = [
        _reading(Metric.TEMPERATURE, -1.0, 1),
        _reading(Metric.TEMPERATURE, 1.0, 2),
    ]

    anomalies = detect_anomalies(
        history,
        {Metric.TEMPERATURE: current},
        _policy(min_samples=2, zscore=2.0),
    )

    assert len(anomalies) == 1
    assert anomalies[0].kind == "zscore"
    assert anomalies[0].score == 2.0


def test_rate_of_change_is_reported_independently() -> None:
    current = _reading(Metric.SOIL_MOISTURE, 10.0, 4)
    history = [
        _reading(Metric.SOIL_MOISTURE, 0.0, 1),
        _reading(Metric.SOIL_MOISTURE, 1.0, 2),
        _reading(Metric.SOIL_MOISTURE, 2.0, 3),
    ]

    anomalies = detect_anomalies(
        history,
        {Metric.SOIL_MOISTURE: current},
        _policy(zscore=100.0, max_rate=8.0),
    )

    assert [anomaly.kind for anomaly in anomalies] == ["rate_of_change"]
    assert anomalies[0].score == 8.0
    assert anomalies[0].baseline_value == 2.0


def test_current_and_other_metrics_are_excluded_from_baseline() -> None:
    current = _reading(Metric.TEMPERATURE, 20.0, 4)
    history = [
        _reading(Metric.TEMPERATURE, 20.0, 3),
        _reading(Metric.TEMPERATURE, 20.0, 1),
        current,
        _reading(Metric.HUMIDITY, 100.0, 2),
        _reading(Metric.TEMPERATURE, 20.0, 2),
    ]

    assert (
        detect_anomalies(
            history,
            {Metric.TEMPERATURE: current},
            _policy(),
        )
        == ()
    )


def test_history_from_other_sensor_id_is_not_used_as_baseline() -> None:
    current = _reading(
        Metric.TEMPERATURE,
        20.0,
        4,
        sensor_id="temperature-a",
    )
    history = [
        _reading(
            Metric.TEMPERATURE,
            0.0,
            minute,
            sensor_id="temperature-b",
        )
        for minute in range(1, 4)
    ]

    assert (
        detect_anomalies(
            history,
            {Metric.TEMPERATURE: current},
            _policy(flat_delta=5.0),
        )
        == ()
    )


def test_window_uses_most_recent_values_independent_of_input_order() -> None:
    current = _reading(Metric.TEMPERATURE, 10.0, 10)
    history = [
        _reading(Metric.TEMPERATURE, 100.0, 1),
        _reading(Metric.TEMPERATURE, 10.0, 8),
        _reading(Metric.TEMPERATURE, 10.0, 7),
        _reading(Metric.TEMPERATURE, 10.0, 9),
    ]

    assert (
        detect_anomalies(
            history,
            {Metric.TEMPERATURE: current},
            _policy(window_size=3),
        )
        == ()
    )
