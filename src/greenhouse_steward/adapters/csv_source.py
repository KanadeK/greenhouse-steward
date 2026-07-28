"""Strict, deterministic CSV ingestion for complete sensor snapshots."""

from __future__ import annotations

import csv
import io
import re
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path

from pydantic import ValidationError

from greenhouse_steward.domain import Metric, SensorReading
from greenhouse_steward.ports import ReadingSnapshot

CSV_COLUMNS = (
    "timestamp",
    Metric.TEMPERATURE.value,
    Metric.HUMIDITY.value,
    Metric.SOIL_MOISTURE.value,
    Metric.LIGHT.value,
)
_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)


class CsvAdapterError(ValueError):
    """Base class for safe, user-facing CSV failures."""


class CsvEncodingError(CsvAdapterError):
    """The input is not valid UTF-8."""


class CsvSchemaError(CsvAdapterError):
    """The header does not match the canonical schema."""

    def __init__(self, actual: tuple[str, ...]) -> None:
        self.expected = CSV_COLUMNS
        self.actual = actual
        super().__init__(
            "CSV header does not match the required five-column sensor schema "
            f"(received {len(actual)} columns)"
        )


class CsvRowError(CsvAdapterError):
    """One data row is malformed."""

    def __init__(
        self,
        line: int,
        column: str,
        raw_value: str,
        reason: str,
    ) -> None:
        self.line = line
        self.column = column
        self.raw_value = raw_value
        self.reason = reason
        super().__init__(f"CSV line {line}, column {column}: {reason}")


class CsvTimestampOrderError(CsvAdapterError):
    """Timestamps are duplicated or not strictly increasing."""

    def __init__(self, line: int, previous: datetime, current: datetime) -> None:
        self.line = line
        self.previous = previous
        self.current = current
        super().__init__(
            f"CSV line {line}: timestamp {current.isoformat()} must be after {previous.isoformat()}"
        )


class CsvLimitError(CsvAdapterError):
    """The configured row ceiling was exceeded."""

    def __init__(self, max_rows: int) -> None:
        self.max_rows = max_rows
        super().__init__(f"CSV exceeds the {max_rows}-row limit")


class StrictCsvSource:
    """Parse the canonical five-column format without partial acceptance."""

    def read_path(
        self,
        path: Path | str,
        *,
        device_id: str,
        max_rows: int = 100_000,
    ) -> tuple[ReadingSnapshot, ...]:
        """Read and validate a UTF-8 CSV file."""

        try:
            payload = Path(path).read_bytes()
        except OSError as error:
            raise CsvAdapterError(f"cannot read CSV input: {error}") from error
        return self.read_bytes(payload, device_id=device_id, max_rows=max_rows)

    def read_bytes(
        self,
        payload: bytes,
        *,
        device_id: str,
        max_rows: int = 100_000,
    ) -> tuple[ReadingSnapshot, ...]:
        """Decode UTF-8, accepting a single leading BOM."""

        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise CsvEncodingError("CSV must be UTF-8 encoded") from error
        return self.read_text(text, device_id=device_id, max_rows=max_rows)

    def read_text(
        self,
        text: str,
        *,
        device_id: str,
        max_rows: int = 100_000,
    ) -> tuple[ReadingSnapshot, ...]:
        """Parse text into one four-reading snapshot per row."""

        if max_rows <= 0:
            raise ValueError("max_rows must be positive")
        if text.startswith("\ufeff"):
            text = text.removeprefix("\ufeff")

        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        try:
            header = next(reader)
        except StopIteration as error:
            raise CsvSchemaError(()) from error
        except csv.Error as error:
            raise CsvSchemaError(()) from error

        actual_header = tuple(header)
        if actual_header != CSV_COLUMNS:
            raise CsvSchemaError(actual_header)

        snapshots: list[ReadingSnapshot] = []
        previous: datetime | None = None
        try:
            for row in reader:
                line = reader.line_num
                if len(snapshots) >= max_rows:
                    raise CsvLimitError(max_rows)
                if len(row) != len(CSV_COLUMNS):
                    raise CsvRowError(
                        line,
                        "<row>",
                        repr(row),
                        f"expected {len(CSV_COLUMNS)} fields, received {len(row)}",
                    )
                observed_at = _parse_timestamp(row[0], line)
                if previous is not None and observed_at <= previous:
                    raise CsvTimestampOrderError(line, previous, observed_at)
                values = {
                    metric: _parse_number(row[index], line, metric.value)
                    for index, metric in enumerate(Metric.__members__.values(), start=1)
                }
                try:
                    readings = tuple(
                        SensorReading(
                            sensor_id=f"{device_id}:{metric.value}",
                            metric=metric,
                            value=values[metric],
                            observed_at=observed_at,
                        )
                        for metric in Metric.__members__.values()
                    )
                    snapshot = ReadingSnapshot(
                        device_id=device_id,
                        observed_at=observed_at,
                        readings=readings,
                    )
                except (ValidationError, ValueError) as error:
                    raise CsvRowError(line, "<row>", repr(row), str(error)) from error
                snapshots.append(snapshot)
                previous = observed_at
        except csv.Error as error:
            raise CsvRowError(reader.line_num, "<row>", "", f"malformed CSV: {error}") from error

        if not snapshots:
            raise CsvRowError(2, "<row>", "", "CSV must contain at least one data row")
        return tuple(snapshots)


def _parse_timestamp(raw: str, line: int) -> datetime:
    """Parse one strict RFC 3339 timestamp."""

    if raw != raw.strip() or _TIMESTAMP_PATTERN.fullmatch(raw) is None:
        raise CsvRowError(line, "timestamp", raw, "expected an RFC 3339 timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise CsvRowError(line, "timestamp", raw, "invalid calendar timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CsvRowError(line, "timestamp", raw, "timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _parse_number(raw: str, line: int, column: str) -> float:
    """Parse one finite, whitespace-free decimal value."""

    if not raw or raw != raw.strip():
        raise CsvRowError(line, column, raw, "value must be a non-blank number")
    try:
        value = float(raw)
    except ValueError as error:
        raise CsvRowError(line, column, raw, "value must be numeric") from error
    if not isfinite(value):
        raise CsvRowError(line, column, raw, "value must be finite")
    return value
