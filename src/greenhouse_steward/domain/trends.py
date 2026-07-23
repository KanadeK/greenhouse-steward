"""Timezone-aware daily and weekly trend aggregation."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from datetime import timezone as fixed_timezone
from enum import StrEnum
from math import isfinite
from statistics import fmean
from typing import Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, field_validator, model_validator

from greenhouse_steward.domain.models import DomainModel, Metric, SensorReading


class TrendDirection(StrEnum):
    """Change in mean compared with the preceding available period."""

    UP = "up"
    DOWN = "down"
    STABLE = "stable"
    INSUFFICIENT_DATA = "insufficient_data"


class PeriodAggregate(DomainModel):
    """Statistics for one metric in one local calendar period."""

    metric: Metric
    period_start: AwareDatetime
    period_end: AwareDatetime
    count: int = Field(ge=1)
    minimum: float
    maximum: float
    mean: float
    change_from_previous: float | None
    direction: TrendDirection

    @field_validator("minimum", "maximum", "mean", "change_from_previous")
    @classmethod
    def validate_statistic(cls, value: float | None) -> float | None:
        """Reject non-finite trend statistics."""

        if value is not None and not isfinite(value):
            raise ValueError("trend statistics must be finite")
        return value

    @model_validator(mode="after")
    def validate_period(self) -> Self:
        """Require coherent dates, values, and first-period direction."""

        if self.period_end <= self.period_start:
            raise ValueError("period_end must be after period_start")
        if not self.minimum <= self.mean <= self.maximum:
            raise ValueError("mean must lie between minimum and maximum")
        if self.change_from_previous is None:
            if self.direction != TrendDirection.INSUFFICIENT_DATA:
                raise ValueError("the first period must have insufficient-data direction")
        elif self.direction == TrendDirection.INSUFFICIENT_DATA:
            raise ValueError("periods with a change must have a directional result")
        return self


class TrendReport(DomainModel):
    """Daily and weekly aggregates from the same source readings."""

    timezone: str = Field(min_length=1)
    daily: tuple[PeriodAggregate, ...]
    weekly: tuple[PeriodAggregate, ...]


def build_trends(
    readings: Sequence[SensorReading],
    *,
    timezone: str = "UTC",
    stable_epsilon: Mapping[Metric, float] | None = None,
) -> TrendReport:
    """Aggregate readings by local day and Monday-based local week."""

    zone, timezone_name = _resolve_timezone(timezone)

    epsilons = {metric: 0.0 for metric in Metric}
    if stable_epsilon is not None:
        for metric, value in stable_epsilon.items():
            if not isfinite(value) or value < 0:
                raise ValueError("stable epsilon values must be finite and non-negative")
            epsilons[metric] = value

    daily_groups: defaultdict[tuple[Metric, date], list[float]] = defaultdict(list)
    weekly_groups: defaultdict[tuple[Metric, date], list[float]] = defaultdict(list)
    for reading in readings:
        local = reading.observed_at.astimezone(zone)
        local_day = local.date()
        week_start = local_day - timedelta(days=local_day.weekday())
        daily_groups[(reading.metric, local_day)].append(reading.value)
        weekly_groups[(reading.metric, week_start)].append(reading.value)

    daily = _aggregate(daily_groups, zone, epsilons, days=1)
    weekly = _aggregate(weekly_groups, zone, epsilons, days=7)
    return TrendReport(timezone=timezone_name, daily=daily, weekly=weekly)


def _resolve_timezone(value: str) -> tuple[tzinfo, str]:
    """Resolve UTC, portable fixed offsets, or an installed IANA timezone."""

    if value in {"UTC", "Etc/UTC", "Z"}:
        return UTC, "UTC"

    offset_match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", value)
    if offset_match is not None:
        sign_text, hours_text, minutes_text = offset_match.groups()
        hours = int(hours_text)
        minutes = int(minutes_text)
        if minutes >= 60 or hours > 14 or (hours == 14 and minutes != 0):
            raise ValueError(f"invalid UTC offset: {value}")
        sign = -1 if sign_text == "-" else 1
        offset = sign * timedelta(hours=hours, minutes=minutes)
        return fixed_timezone(offset, name=value), value

    try:
        zone = ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError(f"unknown timezone: {value}") from error
    return zone, zone.key


def _aggregate(
    groups: Mapping[tuple[Metric, date], list[float]],
    zone: tzinfo,
    epsilons: Mapping[Metric, float],
    *,
    days: int,
) -> tuple[PeriodAggregate, ...]:
    """Build sorted period aggregates and changes per metric."""

    results: list[PeriodAggregate] = []
    previous_mean: dict[Metric, float] = {}
    for metric, start_date in sorted(groups, key=lambda item: (item[0].value, item[1])):
        values = groups[(metric, start_date)]
        mean = fmean(values)
        prior = previous_mean.get(metric)
        if prior is None:
            change: float | None = None
            direction = TrendDirection.INSUFFICIENT_DATA
        else:
            change = mean - prior
            epsilon = epsilons[metric]
            if change > epsilon:
                direction = TrendDirection.UP
            elif change < -epsilon:
                direction = TrendDirection.DOWN
            else:
                direction = TrendDirection.STABLE

        period_start = _first_valid_local_instant(start_date, zone)
        period_end = _first_valid_local_instant(start_date + timedelta(days=days), zone)
        results.append(
            PeriodAggregate(
                metric=metric,
                period_start=period_start,
                period_end=period_end,
                count=len(values),
                minimum=min(values),
                maximum=max(values),
                mean=mean,
                change_from_previous=change,
                direction=direction,
            )
        )
        previous_mean[metric] = mean
    return tuple(results)


def _first_valid_local_instant(local_date: date, zone: tzinfo) -> datetime:
    """Resolve local midnight, advancing across a timezone gap when necessary."""

    midnight = datetime.combine(local_date, time.min)
    candidates: list[datetime] = []
    for fold in (0, 1):
        attached = midnight.replace(tzinfo=zone, fold=fold)
        round_tripped = attached.astimezone(UTC).astimezone(zone)
        if round_tripped.replace(tzinfo=None) >= midnight:
            candidates.append(round_tripped)

    if not candidates:
        raise ValueError(f"cannot resolve local period boundary for {local_date.isoformat()}")

    return min(
        candidates,
        key=lambda candidate: (
            candidate.replace(tzinfo=None),
            candidate.astimezone(UTC),
        ),
    )
