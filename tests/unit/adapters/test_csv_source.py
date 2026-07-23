"""Strict CSV adapter tests."""

from __future__ import annotations

import pytest

from greenhouse_steward.adapters.csv_source import (
    CsvRowError,
    CsvSchemaError,
    CsvTimestampOrderError,
    StrictCsvSource,
)
from greenhouse_steward.domain import Metric

HEADER = "timestamp,temperature_c,humidity_pct,soil_moisture_pct,light_lux\n"


def test_csv_accepts_bom_and_builds_four_readings_per_timestamp() -> None:
    source = StrictCsvSource()
    snapshots = source.read_bytes(
        (
            "\ufeff"
            + HEADER
            + "2026-01-01T00:00:00+08:00,20,60,40,1000\n"
            + "2026-01-01T00:15:00+08:00,21,61,39,1100\n"
        ).encode(),
        device_id="greenhouse-1",
    )

    assert len(snapshots) == 2
    assert set(snapshots[0].by_metric) == set(Metric)
    assert snapshots[0].observed_at.isoformat() == "2025-12-31T16:00:00+00:00"
    assert snapshots[0].by_metric[Metric.SOIL_MOISTURE].sensor_id.startswith("greenhouse-1:")


def test_csv_schema_error_does_not_echo_untrusted_header() -> None:
    secret = "ghp_DEMONSTRATION_SECRET"
    with pytest.raises(CsvSchemaError) as caught:
        StrictCsvSource().read_text(
            f"{secret},temperature_c\n",
            device_id="device-1",
        )

    assert secret not in str(caught.value)
    assert caught.value.actual[0] == secret


@pytest.mark.parametrize(
    "row",
    [
        "2026-01-01T00:00:00Z,nan,60,40,1000\n",
        "2026-01-01 00:00:00,20,60,40,1000\n",
        "2026-01-01T00:00:00Z, 20,60,40,1000\n",
        "2026-01-01T00:00:00Z,20,60,40\n",
    ],
)
def test_csv_rejects_nonfinite_timestamp_whitespace_and_short_rows(row: str) -> None:
    with pytest.raises(CsvRowError):
        StrictCsvSource().read_text(HEADER + row, device_id="device-1")


def test_csv_rejects_duplicate_or_reversed_timestamps() -> None:
    payload = (
        HEADER + "2026-01-01T00:15:00Z,20,60,40,1000\n" + "2026-01-01T00:15:00Z,21,61,41,1100\n"
    )
    with pytest.raises(CsvTimestampOrderError):
        StrictCsvSource().read_text(payload, device_id="device-1")
