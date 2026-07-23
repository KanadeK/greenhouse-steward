"""Application-layer contracts shared by adapters and services."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, TextIO

from greenhouse_steward.domain import (
    AnomalyPolicy,
    CropProfile,
    Metric,
    SafetyPolicy,
    SensorReading,
)
from greenhouse_steward.domain.clock import require_aware_utc

_DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")


@dataclass(frozen=True, slots=True)
class ReadingSnapshot:
    """Exactly four metric readings captured for one device and timestamp."""

    device_id: str
    observed_at: datetime
    readings: tuple[SensorReading, ...]

    def __post_init__(self) -> None:
        """Normalize ordering and enforce the wide-snapshot invariant."""

        if _DEVICE_ID_PATTERN.fullmatch(self.device_id) is None:
            raise ValueError(
                "device_id must be 1-80 safe characters beginning with a letter or digit"
            )
        normalized_time = require_aware_utc(self.observed_at)
        ordered = tuple(sorted(self.readings, key=lambda reading: reading.metric.value))
        if len(ordered) != len(Metric):
            raise ValueError("a snapshot must contain exactly four readings")
        if {reading.metric for reading in ordered} != set(Metric):
            raise ValueError("a snapshot must contain one reading for every metric")
        if len({reading.sensor_id for reading in ordered}) != len(Metric):
            raise ValueError("snapshot sensor identifiers must be unique")
        if any(reading.observed_at != normalized_time for reading in ordered):
            raise ValueError("all snapshot readings must share observed_at")
        object.__setattr__(self, "observed_at", normalized_time)
        object.__setattr__(self, "readings", ordered)

    @property
    def by_metric(self) -> Mapping[Metric, SensorReading]:
        """Return the readings keyed by metric."""

        return {reading.metric: reading for reading in self.readings}


@dataclass(frozen=True, slots=True)
class ProfileBundle:
    """One crop profile and the safety/anomaly policies used with it."""

    profile: CropProfile
    safety: SafetyPolicy
    anomaly: AnomalyPolicy


class StoreOutcome(StrEnum):
    """Result of an idempotent snapshot write."""

    INSERTED = "inserted"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True)
class BatchStoreResult:
    """Counts from one atomic batch write."""

    inserted: int
    unchanged: int

    @property
    def total(self) -> int:
        """Return the number of snapshots considered."""

        return self.inserted + self.unchanged


class ProfileProvider(Protocol):
    """Load immutable bundled or user-supplied crop profiles."""

    def load(self, profile_slug: str) -> ProfileBundle:
        """Load one validated profile bundle."""

    def list_slugs(self) -> tuple[str, ...]:
        """List available profile slugs."""


class ObservationRepository(Protocol):
    """Persist and query complete four-metric snapshots."""

    def save_snapshot(
        self,
        snapshot: ReadingSnapshot,
        *,
        source_kind: str,
        source_ref: str | None = None,
    ) -> StoreOutcome:
        """Store one snapshot without replacing conflicting data."""

    def save_many(
        self,
        snapshots: Iterable[ReadingSnapshot],
        *,
        source_kind: str,
        source_ref: str | None = None,
    ) -> BatchStoreResult:
        """Store a batch atomically."""

    def query(
        self,
        device_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100_000,
    ) -> tuple[ReadingSnapshot, ...]:
        """Return snapshots ordered by time using a half-open time range."""

    def latest(self, device_id: str) -> ReadingSnapshot | None:
        """Return the newest snapshot for a device."""

    def export_csv(
        self,
        writer: TextIO,
        *,
        device_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> int:
        """Write snapshots in the strict five-column CSV format."""


class SnapshotSource(Protocol):
    """Read complete snapshots from an external representation."""

    def read_path(self, path: str, *, device_id: str) -> Sequence[ReadingSnapshot]:
        """Read snapshots from a path."""
