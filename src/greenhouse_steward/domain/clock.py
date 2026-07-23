"""Injectable clocks for deterministic time-sensitive logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol


def require_aware_utc(value: datetime) -> datetime:
    """Validate and normalize an aware timestamp."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock timestamps must be timezone-aware")
    return value.astimezone(UTC)


class Clock(Protocol):
    """Small time source contract used by domain services."""

    def now(self) -> datetime:
        """Return an aware current timestamp."""


class SystemClock:
    """Production UTC clock."""

    def now(self) -> datetime:
        """Return the current UTC timestamp."""

        return datetime.now(UTC)


@dataclass(slots=True)
class FrozenClock:
    """Mutable test clock that never sleeps."""

    current: datetime

    def __post_init__(self) -> None:
        """Normalize the initial value."""

        self.current = require_aware_utc(self.current)

    def now(self) -> datetime:
        """Return the configured timestamp."""

        return self.current

    def advance(self, delta: timedelta) -> None:
        """Move by a deterministic duration, including rollback scenarios."""

        self.current = require_aware_utc(self.current + delta)

    def set(self, value: datetime) -> None:
        """Set a new deterministic timestamp."""

        self.current = require_aware_utc(value)
