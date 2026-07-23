"""Safety tests for the optional relay simulator."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from greenhouse_steward.domain import (
    Action,
    FrozenClock,
    RelaySimulator,
    RelayState,
    WateringDecision,
)


class SequenceClock:
    """Clock that exposes accidental extra reads as a test failure."""

    def __init__(self, values: list[datetime]) -> None:
        self._values = iter(values)
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        try:
            return next(self._values)
        except StopIteration as error:
            raise AssertionError("clock was read more often than expected") from error


def _watering() -> WateringDecision:
    return WateringDecision(
        action=Action.WATER,
        suggested_duration_seconds=300,
        relay_permitted=True,
        reason_codes=("soil_below_watering_trigger",),
    )


def _hold() -> WateringDecision:
    return WateringDecision(
        action=Action.MONITOR,
        relay_permitted=False,
        reason_codes=("soil_moisture_in_hold_band",),
    )


def _safe() -> WateringDecision:
    return WateringDecision(
        action=Action.STOP_WATER,
        relay_permitted=False,
        safety_lock=True,
        reason_codes=("sensor.soil_moisture_pct.stale",),
    )


def test_relay_caps_requested_duration(
    clock: FrozenClock,
) -> None:
    relay = RelaySimulator(clock, max_on_seconds=120)

    snapshot = relay.apply(_watering(), requested_seconds=300)

    assert snapshot.state == RelayState.ON
    assert snapshot.requested_seconds == 300
    assert snapshot.applied_seconds == 120
    assert snapshot.capped
    assert snapshot.started_at is not None
    assert snapshot.hard_stop_at == snapshot.started_at + timedelta(seconds=120)


def test_relay_stops_exactly_at_hard_deadline(
    clock: FrozenClock,
) -> None:
    relay = RelaySimulator(clock, max_on_seconds=120)
    relay.apply(_watering(), requested_seconds=120)

    clock.advance(timedelta(seconds=119, microseconds=999_999))
    assert relay.status().state == RelayState.ON
    clock.advance(timedelta(microseconds=1))
    stopped = relay.status()

    assert stopped.state == RelayState.OFF
    assert stopped.reason == "maximum_duration_elapsed"
    assert stopped.hard_stop_at is None


def test_repeated_on_request_never_extends_original_deadline(
    clock: FrozenClock,
) -> None:
    relay = RelaySimulator(clock, max_on_seconds=120)
    initial = relay.apply(_watering(), requested_seconds=120)
    original_stop = initial.hard_stop_at
    clock.advance(timedelta(seconds=60))

    repeated = relay.apply(_watering(), requested_seconds=120)

    assert repeated.hard_stop_at == original_stop
    assert repeated.reason == "watering_request_updated_without_extension"
    clock.advance(timedelta(seconds=60))
    assert relay.status().state == RelayState.OFF


def test_repeated_request_may_shorten_but_not_extend(
    clock: FrozenClock,
) -> None:
    relay = RelaySimulator(clock, max_on_seconds=120)
    started = relay.apply(_watering(), requested_seconds=120)
    assert started.started_at is not None
    clock.advance(timedelta(seconds=60))

    shortened = relay.apply(_watering(), requested_seconds=10)

    assert shortened.hard_stop_at == started.started_at + timedelta(seconds=70)
    assert shortened.applied_seconds == 70


def test_safe_decision_immediately_deenergizes_active_relay(
    clock: FrozenClock,
) -> None:
    relay = RelaySimulator(clock, max_on_seconds=120)
    relay.apply(_watering(), requested_seconds=60)
    clock.advance(timedelta(seconds=1))

    stopped = relay.apply(_safe(), requested_seconds=60)

    assert stopped.state == RelayState.LOCKED_SAFE
    assert stopped.started_at is None
    assert stopped.hard_stop_at is None
    assert "sensor.soil_moisture_pct.stale" in stopped.reason


def test_non_watering_decision_never_starts_relay(
    clock: FrozenClock,
) -> None:
    relay = RelaySimulator(clock, max_on_seconds=120)

    snapshot = relay.apply(_hold(), requested_seconds=60)

    assert snapshot.state == RelayState.OFF
    assert snapshot.reason.startswith("watering_not_permitted")


@pytest.mark.parametrize("duration", [0, -1])
def test_relay_rejects_non_positive_start_duration(
    clock: FrozenClock,
    duration: int,
) -> None:
    relay = RelaySimulator(clock, max_on_seconds=120)

    with pytest.raises(ValueError, match="positive"):
        relay.apply(_watering(), requested_seconds=duration)


def test_clock_rollback_fails_closed_and_remains_locked(
    now: datetime,
    clock: FrozenClock,
) -> None:
    relay = RelaySimulator(clock, max_on_seconds=120)
    relay.apply(_watering(), requested_seconds=60)
    clock.advance(timedelta(seconds=10))
    relay.status()
    clock.set(now - timedelta(seconds=1))

    rolled_back = relay.status()
    retry = relay.apply(_watering(), requested_seconds=60)

    assert rolled_back.state == RelayState.LOCKED_SAFE
    assert rolled_back.reason == "clock_rollback"
    assert retry == rolled_back


def test_apply_samples_clock_once_and_fails_closed_on_observed_rollback(
    now: datetime,
) -> None:
    clock = SequenceClock([now, now - timedelta(seconds=1)])
    relay = RelaySimulator(clock, max_on_seconds=120)

    snapshot = relay.apply(_watering(), requested_seconds=60)

    assert clock.calls == 2
    assert snapshot.state == RelayState.LOCKED_SAFE
    assert snapshot.reason == "clock_rollback"
    assert snapshot.started_at is None
    assert snapshot.hard_stop_at is None


def test_status_is_idempotent_without_time_change(
    clock: FrozenClock,
) -> None:
    relay = RelaySimulator(clock, max_on_seconds=120)
    started = relay.apply(_watering(), requested_seconds=60)

    assert relay.status() == started
    assert relay.status() == started


def test_explicit_stop_and_input_validation(
    clock: FrozenClock,
) -> None:
    relay = RelaySimulator(clock, max_on_seconds=120)
    relay.apply(_watering(), requested_seconds=60)

    assert relay.stop("operator stop").state == RelayState.OFF
    with pytest.raises(ValueError, match="blank"):
        relay.stop(" ")
    with pytest.raises(ValueError, match="positive"):
        RelaySimulator(clock, max_on_seconds=0)
