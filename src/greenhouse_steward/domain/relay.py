"""Fail-safe in-memory relay simulator."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import AwareDatetime, Field, field_validator

from greenhouse_steward.domain.clock import Clock, require_aware_utc
from greenhouse_steward.domain.models import Action, DomainModel, WateringDecision


class RelayState(StrEnum):
    """Observable relay states."""

    OFF = "off"
    ON = "on"
    LOCKED_SAFE = "locked_safe"


class RelaySnapshot(DomainModel):
    """Immutable view of the simulated relay."""

    state: RelayState
    started_at: AwareDatetime | None
    hard_stop_at: AwareDatetime | None
    last_checked_at: AwareDatetime
    reason: str = Field(min_length=1, max_length=256)
    requested_seconds: int | None = Field(default=None, ge=1)
    applied_seconds: int | None = Field(default=None, ge=1)
    capped: bool = False

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        """Reject empty transition reasons."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("relay reason must not be blank")
        return normalized


class RelaySimulator:
    """Simulate irrigation without ever controlling physical hardware."""

    def __init__(self, clock: Clock, max_on_seconds: int) -> None:
        """Create an off relay with a mandatory hard duration cap."""

        if max_on_seconds <= 0:
            raise ValueError("max_on_seconds must be positive")
        self._clock = clock
        self._max_on_seconds = max_on_seconds
        now = require_aware_utc(clock.now())
        self._snapshot = RelaySnapshot(
            state=RelayState.OFF,
            started_at=None,
            hard_stop_at=None,
            last_checked_at=now,
            reason="initialized_off",
        )

    def apply(
        self,
        decision: WateringDecision,
        requested_seconds: int,
    ) -> RelaySnapshot:
        """Apply guidance, enforcing safety locks and a non-extendable hard stop."""

        now = require_aware_utc(self._clock.now())
        current = self._refresh(now)
        if current.state == RelayState.LOCKED_SAFE and current.reason == "clock_rollback":
            return current
        if decision.safety_lock:
            return self._set_off(
                state=RelayState.LOCKED_SAFE,
                now=now,
                reason="safety_lock:" + ",".join(decision.reason_codes),
            )
        if decision.action != Action.WATER or not decision.relay_permitted:
            return self._set_off(
                state=RelayState.OFF,
                now=now,
                reason="watering_not_permitted:" + ",".join(decision.reason_codes),
            )
        if requested_seconds <= 0:
            raise ValueError("requested_seconds must be positive")

        applied = min(requested_seconds, self._max_on_seconds)
        proposed_stop = now + timedelta(seconds=applied)
        if current.state == RelayState.ON:
            if current.hard_stop_at is None or current.started_at is None:
                return self._set_off(
                    state=RelayState.LOCKED_SAFE,
                    now=now,
                    reason="invalid_internal_relay_state",
                )
            hard_stop = min(current.hard_stop_at, proposed_stop)
            total_applied = max(
                1,
                int((hard_stop - current.started_at).total_seconds()),
            )
            self._snapshot = RelaySnapshot(
                state=RelayState.ON,
                started_at=current.started_at,
                hard_stop_at=hard_stop,
                last_checked_at=now,
                reason="watering_request_updated_without_extension",
                requested_seconds=requested_seconds,
                applied_seconds=total_applied,
                capped=requested_seconds > self._max_on_seconds,
            )
            return self._snapshot

        self._snapshot = RelaySnapshot(
            state=RelayState.ON,
            started_at=now,
            hard_stop_at=proposed_stop,
            last_checked_at=now,
            reason="watering_started",
            requested_seconds=requested_seconds,
            applied_seconds=applied,
            capped=requested_seconds > self._max_on_seconds,
        )
        return self._snapshot

    def stop(self, reason: str) -> RelaySnapshot:
        """Explicitly stop the simulated relay."""

        normalized = reason.strip()
        if not normalized:
            raise ValueError("stop reason must not be blank")
        now = require_aware_utc(self._clock.now())
        if now < self._snapshot.last_checked_at:
            return self._set_off(
                state=RelayState.LOCKED_SAFE,
                now=now,
                reason="clock_rollback",
            )
        return self._set_off(state=RelayState.OFF, now=now, reason=normalized)

    def status(self) -> RelaySnapshot:
        """Refresh timeout and rollback checks, then return the current state."""

        now = require_aware_utc(self._clock.now())
        return self._refresh(now)

    def _refresh(self, now: datetime) -> RelaySnapshot:
        """Refresh state using one timestamp already sampled by the caller."""

        if now < self._snapshot.last_checked_at:
            return self._set_off(
                state=RelayState.LOCKED_SAFE,
                now=now,
                reason="clock_rollback",
            )
        if (
            self._snapshot.state == RelayState.ON
            and self._snapshot.hard_stop_at is not None
            and now >= self._snapshot.hard_stop_at
        ):
            return self._set_off(
                state=RelayState.OFF,
                now=now,
                reason="maximum_duration_elapsed",
            )
        if now != self._snapshot.last_checked_at:
            self._snapshot = self._snapshot.model_copy(update={"last_checked_at": now})
        return self._snapshot

    def _set_off(
        self,
        *,
        state: RelayState,
        now: datetime,
        reason: str,
    ) -> RelaySnapshot:
        """Store a fully de-energized state."""

        self._snapshot = RelaySnapshot(
            state=state,
            started_at=None,
            hard_stop_at=None,
            last_checked_at=now,
            reason=reason,
        )
        return self._snapshot
