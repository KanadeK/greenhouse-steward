"""Byte-reproducible seven-day greenhouse fixture generation."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TextIO

from greenhouse_steward.adapters.csv_source import CSV_COLUMNS
from greenhouse_steward.domain import CropProfile, Metric, SensorReading
from greenhouse_steward.domain.clock import require_aware_utc
from greenhouse_steward.ports import ReadingSnapshot

GENERATOR_VERSION = 1


@dataclass(frozen=True, slots=True)
class SyntheticDatasetConfig:
    """All inputs needed to reproduce a synthetic dataset."""

    profile_slug: str
    device_id: str
    start: datetime
    days: int = 7
    interval_minutes: int = 15
    seed: int = 3501

    def __post_init__(self) -> None:
        """Validate and normalize deterministic configuration."""

        if not self.profile_slug:
            raise ValueError("profile_slug must not be blank")
        if self.days <= 0 or self.days > 365:
            raise ValueError("days must be between 1 and 365")
        if self.interval_minutes <= 0 or 1_440 % self.interval_minutes != 0:
            raise ValueError("interval_minutes must divide a day exactly")
        object.__setattr__(self, "start", require_aware_utc(self.start))

    @property
    def row_count(self) -> int:
        """Return the exact number of generated timestamps."""

        return self.days * 1_440 // self.interval_minutes


def generate_dataset(
    config: SyntheticDatasetConfig,
    profile: CropProfile,
) -> tuple[ReadingSnapshot, ...]:
    """Generate realistic patterns plus scheduled, explainable excursions."""

    if config.profile_slug != profile.slug:
        raise ValueError("dataset profile_slug does not match the loaded profile")
    rng = random.Random(config.seed)
    slots_per_day = 1_440 // config.interval_minutes
    snapshots: list[ReadingSnapshot] = []
    last_stuck_light: float | None = None

    for index in range(config.row_count):
        observed_at = config.start + timedelta(minutes=index * config.interval_minutes)
        slot = index % slots_per_day
        day = index // slots_per_day
        minute_of_day = slot * config.interval_minutes
        hour = minute_of_day / 60.0
        phase = 2.0 * math.pi * (minute_of_day / 1_440.0 - 0.25)
        daylight = max(0.0, math.sin(math.pi * (hour - 6.0) / 12.0))

        temperature_target = profile.targets[Metric.TEMPERATURE]
        humidity_target = profile.targets[Metric.HUMIDITY]
        light_target = profile.targets[Metric.LIGHT]

        temperature = (
            (temperature_target.low + temperature_target.high) / 2.0
            + 3.8 * math.sin(phase)
            + rng.uniform(-0.35, 0.35)
        )
        humidity = (
            (humidity_target.low + humidity_target.high) / 2.0
            - 6.5 * math.sin(phase)
            + rng.uniform(-0.7, 0.7)
        )
        soil = (
            profile.watering.stop_at_pct
            + 3.0
            - 10.0 * (slot / slots_per_day)
            + rng.uniform(-0.25, 0.25)
        )
        light = daylight * light_target.high * 0.82 + (
            rng.uniform(0.0, 300.0) if daylight > 0 else 0.0
        )

        # Fixed demonstrations: temperature spike, dry soil, humid period,
        # and a short sensor value that remains exactly unchanged.
        if day == 2 and 56 <= slot < 60:
            temperature += 9.0
        if day == 3 and 48 <= slot < 56:
            soil = profile.watering.trigger_below_pct - 6.0 + (slot - 48) * 0.4
        if day == 4 and 12 <= slot < 20:
            humidity += 18.0
        if day == 5 and 36 <= slot < 44:
            if last_stuck_light is None:
                last_stuck_light = light_target.low * 1.2
            light = last_stuck_light
        else:
            last_stuck_light = None

        values = {
            Metric.TEMPERATURE: round(_clamp(temperature, -10.0, 50.0), 3),
            Metric.HUMIDITY: round(_clamp(humidity, 5.0, 98.0), 3),
            Metric.SOIL_MOISTURE: round(_clamp(soil, 5.0, 95.0), 3),
            Metric.LIGHT: round(_clamp(light, 0.0, 180_000.0), 3),
        }
        readings = tuple(
            SensorReading(
                sensor_id=f"{config.device_id}:{metric.value}",
                metric=metric,
                value=values[metric],
                observed_at=observed_at,
            )
            for metric in Metric
        )
        snapshots.append(
            ReadingSnapshot(
                device_id=config.device_id,
                observed_at=observed_at,
                readings=readings,
            )
        )
    return tuple(snapshots)


def write_dataset_csv(
    snapshots: Sequence[ReadingSnapshot],
    writer: TextIO,
) -> int:
    """Write canonical CSV with stable LF endings and decimal formatting."""

    output = csv.writer(writer, lineterminator="\n")
    output.writerow(CSV_COLUMNS)
    for snapshot in snapshots:
        by_metric = snapshot.by_metric
        output.writerow(
            (
                _format_timestamp(snapshot.observed_at),
                _format_number(by_metric[Metric.TEMPERATURE].value),
                _format_number(by_metric[Metric.HUMIDITY].value),
                _format_number(by_metric[Metric.SOIL_MOISTURE].value),
                _format_number(by_metric[Metric.LIGHT].value),
            )
        )
    return len(snapshots)


def build_manifest(
    files: Mapping[str, bytes],
    configs: Mapping[str, SyntheticDatasetConfig],
) -> dict[str, object]:
    """Describe generated fixtures and their exact checksums."""

    entries: dict[str, object] = {}
    for filename in sorted(files):
        config = configs[filename]
        entries[filename] = {
            "sha256": hashlib.sha256(files[filename]).hexdigest(),
            "profile_slug": config.profile_slug,
            "device_id": config.device_id,
            "seed": config.seed,
            "start": _format_timestamp(config.start),
            "days": config.days,
            "interval_minutes": config.interval_minutes,
            "rows": config.row_count,
        }
    return {
        "schema_version": 1,
        "generator_version": GENERATOR_VERSION,
        "files": entries,
    }


def write_manifest(path: Path, manifest: Mapping[str, object]) -> None:
    """Write a canonical JSON manifest used by the generator script."""

    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _clamp(value: float, low: float, high: float) -> float:
    """Clamp synthetic output to broad physical bounds."""

    return min(high, max(low, value))


def _format_timestamp(value: datetime) -> str:
    """Use compact RFC 3339 while preserving deterministic precision."""

    normalized = require_aware_utc(value)
    return normalized.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _format_number(value: float) -> str:
    """Use exactly three decimals for byte-stable sample files."""

    return f"{value:.3f}"
