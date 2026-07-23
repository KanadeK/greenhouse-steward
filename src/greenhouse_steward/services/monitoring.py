"""Application service joining persistence, profiles, rules, and trends."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from greenhouse_steward.domain import (
    Clock,
    EvaluationResult,
    FrozenClock,
    RuleEngine,
    TrendReport,
    build_trends,
)
from greenhouse_steward.domain.clock import require_aware_utc
from greenhouse_steward.ports import (
    BatchStoreResult,
    ObservationRepository,
    ProfileProvider,
    ReadingSnapshot,
    StoreOutcome,
)


@dataclass(frozen=True, slots=True)
class MonitoringResult:
    """A real rule evaluation and trends from persisted readings."""

    device_id: str
    profile_slug: str
    evaluated_at: datetime
    latest_snapshot: ReadingSnapshot | None
    history_snapshot_count: int
    history_reading_count: int
    evaluation: EvaluationResult
    trends: TrendReport
    store_outcome: StoreOutcome | None = None


@dataclass(frozen=True, slots=True)
class BatchIngestResult:
    """Atomic storage counts plus the resulting current status."""

    storage: BatchStoreResult
    monitoring: MonitoringResult


class MonitoringService:
    """Coordinate adapters with the pure, clock-injected domain core."""

    def __init__(
        self,
        repository: ObservationRepository,
        profiles: ProfileProvider,
        *,
        clock: Clock,
    ) -> None:
        """Create a service without owning any physical actuator."""

        self._repository = repository
        self._profiles = profiles
        self._clock = clock

    def ingest(
        self,
        snapshot: ReadingSnapshot,
        *,
        profile_slug: str,
        source_kind: str,
        source_ref: str | None = None,
        trend_timezone: str = "UTC",
    ) -> MonitoringResult:
        """Persist one snapshot and evaluate the device at the current clock."""

        self._profiles.load(profile_slug)
        build_trends((), timezone=trend_timezone)
        outcome = self._repository.save_snapshot(
            snapshot,
            source_kind=source_kind,
            source_ref=source_ref,
        )
        result = self.current_status(
            snapshot.device_id,
            profile_slug=profile_slug,
            trend_timezone=trend_timezone,
        )
        return replace(result, store_outcome=outcome)

    def ingest_many(
        self,
        snapshots: Sequence[ReadingSnapshot],
        *,
        profile_slug: str,
        source_kind: str,
        source_ref: str | None = None,
        trend_timezone: str = "UTC",
        evaluated_at: datetime | None = None,
    ) -> BatchIngestResult:
        """Persist a same-device batch atomically and evaluate once."""

        if not snapshots:
            raise ValueError("ingest_many requires at least one snapshot")
        device_ids = {snapshot.device_id for snapshot in snapshots}
        if len(device_ids) != 1:
            raise ValueError("ingest_many snapshots must belong to one device")
        self._profiles.load(profile_slug)
        build_trends((), timezone=trend_timezone)
        if evaluated_at is not None:
            require_aware_utc(evaluated_at)
        storage = self._repository.save_many(
            snapshots,
            source_kind=source_kind,
            source_ref=source_ref,
        )
        monitoring = self.current_status(
            snapshots[0].device_id,
            profile_slug=profile_slug,
            trend_timezone=trend_timezone,
            evaluated_at=evaluated_at,
        )
        return BatchIngestResult(storage=storage, monitoring=monitoring)

    def current_status(
        self,
        device_id: str,
        *,
        profile_slug: str,
        trend_timezone: str = "UTC",
        evaluated_at: datetime | None = None,
    ) -> MonitoringResult:
        """Evaluate persisted readings, including a fail-safe empty/stale state."""

        bundle = self._profiles.load(profile_slug)
        evaluation_time = require_aware_utc(
            self._clock.now() if evaluated_at is None else evaluated_at
        )
        snapshots = self._repository.query(device_id)
        readings = tuple(reading for snapshot in snapshots for reading in snapshot.readings)
        evaluation = RuleEngine(FrozenClock(evaluation_time)).evaluate(
            readings,
            bundle.profile,
            bundle.safety,
            bundle.anomaly,
        )
        trends = build_trends(readings, timezone=trend_timezone)
        return MonitoringResult(
            device_id=device_id,
            profile_slug=bundle.profile.slug,
            evaluated_at=evaluation_time,
            latest_snapshot=snapshots[-1] if snapshots else None,
            history_snapshot_count=len(snapshots),
            history_reading_count=len(readings),
            evaluation=evaluation,
            trends=trends,
        )
