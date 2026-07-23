"""SQLite v1 repository with atomic, idempotent snapshot storage."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import TextIO
from uuid import uuid4

from greenhouse_steward.adapters.csv_source import CSV_COLUMNS
from greenhouse_steward.domain import Clock, Metric, SensorReading
from greenhouse_steward.domain.clock import require_aware_utc
from greenhouse_steward.ports import (
    BatchStoreResult,
    ReadingSnapshot,
    StoreOutcome,
)

_SCHEMA_VERSION = 1
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    device_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_ref TEXT,
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    ingested_at TEXT NOT NULL,
    UNIQUE(device_id, observed_at)
);

CREATE TABLE IF NOT EXISTS readings (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    metric TEXT NOT NULL,
    sensor_id TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY(snapshot_id, metric)
);

CREATE INDEX IF NOT EXISTS snapshots_device_time
ON snapshots(device_id, observed_at);
"""


class RepositoryError(RuntimeError):
    """Base class for persistence failures."""


class SchemaVersionError(RepositoryError):
    """The database schema is newer than this application."""


class ObservationConflictError(RepositoryError):
    """A timestamp already contains different immutable data."""

    def __init__(self, device_id: str, observed_at: datetime) -> None:
        self.device_id = device_id
        self.observed_at = observed_at
        super().__init__(
            f"conflicting observation for {device_id!r} at {_format_timestamp(observed_at)}"
        )


class SQLiteObservationRepository:
    """Store four-metric snapshots without destructive replacement."""

    def __init__(
        self,
        path: Path | str,
        *,
        clock: Clock,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        """Open a repository and apply the idempotent v1 migration."""

        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be positive")
        requested_path = str(path)
        if not requested_path.strip():
            raise ValueError("database path must not be blank")
        self._is_memory = requested_path == ":memory:"
        self._path = (
            f"file:greenhouse-steward-{uuid4().hex}?mode=memory&cache=shared"
            if self._is_memory
            else requested_path
        )
        self._anchor: sqlite3.Connection | None = None
        if self._is_memory:
            self._anchor = sqlite3.connect(
                self._path,
                uri=True,
                isolation_level=None,
            )
        self._clock = clock
        self._busy_timeout_ms = busy_timeout_ms
        self.migrate()

    def migrate(self) -> None:
        """Create schema v1 atomically and refuse unknown newer schemas."""

        connection = self._connect()
        try:
            if not self._is_memory:
                connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("BEGIN IMMEDIATE")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > _SCHEMA_VERSION:
                raise SchemaVersionError(
                    f"database schema {version} is newer than supported version {_SCHEMA_VERSION}"
                )
            if version == 0:
                for statement in _SCHEMA_SQL.split(";"):
                    if statement.strip():
                        connection.execute(statement)
                connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
            connection.commit()
        except SchemaVersionError:
            connection.rollback()
            raise
        except sqlite3.Error as error:
            connection.rollback()
            raise RepositoryError(f"database migration failed: {error}") from error
        finally:
            connection.close()

    def save_snapshot(
        self,
        snapshot: ReadingSnapshot,
        *,
        source_kind: str,
        source_ref: str | None = None,
    ) -> StoreOutcome:
        """Store one snapshot idempotently."""

        result = self.save_many(
            (snapshot,),
            source_kind=source_kind,
            source_ref=source_ref,
        )
        return StoreOutcome.INSERTED if result.inserted == 1 else StoreOutcome.UNCHANGED

    def save_many(
        self,
        snapshots: Iterable[ReadingSnapshot],
        *,
        source_kind: str,
        source_ref: str | None = None,
    ) -> BatchStoreResult:
        """Store all snapshots in one transaction, rolling back on conflict."""

        normalized_kind = source_kind.strip()
        if not normalized_kind or len(normalized_kind) > 64:
            raise ValueError("source_kind must be 1-64 non-blank characters")
        if source_ref is not None and len(source_ref) > 512:
            raise ValueError("source_ref must not exceed 512 characters")
        items = tuple(snapshots)
        if not items:
            return BatchStoreResult(inserted=0, unchanged=0)
        for snapshot in items:
            if any(not isfinite(reading.value) for reading in snapshot.readings):
                raise ValueError("snapshot readings must be finite")

        ingested_at = _format_timestamp(require_aware_utc(self._clock.now()))
        connection = self._connect()
        inserted = 0
        unchanged = 0
        try:
            connection.execute("BEGIN IMMEDIATE")
            for snapshot in items:
                outcome = self._save_one(
                    connection,
                    snapshot,
                    source_kind=normalized_kind,
                    source_ref=source_ref,
                    ingested_at=ingested_at,
                )
                if outcome == StoreOutcome.INSERTED:
                    inserted += 1
                else:
                    unchanged += 1
            connection.commit()
        except ObservationConflictError:
            connection.rollback()
            raise
        except sqlite3.Error as error:
            connection.rollback()
            raise RepositoryError(f"database write failed: {error}") from error
        finally:
            connection.close()
        return BatchStoreResult(inserted=inserted, unchanged=unchanged)

    def query(
        self,
        device_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100_000,
    ) -> tuple[ReadingSnapshot, ...]:
        """Return snapshots in ascending order over the half-open interval."""

        if limit <= 0 or limit > 100_000:
            raise ValueError("limit must be between 1 and 100000")
        start_text = None if start is None else _format_timestamp(require_aware_utc(start))
        end_text = None if end is None else _format_timestamp(require_aware_utc(end))
        if start_text is not None and end_text is not None and start_text >= end_text:
            raise ValueError("query start must be before end")

        clauses = ["device_id = ?"]
        parameters: list[object] = [device_id]
        if start_text is not None:
            clauses.append("observed_at >= ?")
            parameters.append(start_text)
        if end_text is not None:
            clauses.append("observed_at < ?")
            parameters.append(end_text)
        parameters.append(limit)
        where = " AND ".join(clauses)
        sql = f"""
            SELECT selected.device_id, selected.observed_at,
                   readings.sensor_id, readings.metric, readings.value
            FROM (
                SELECT id, device_id, observed_at
                FROM snapshots
                WHERE {where}
                ORDER BY observed_at DESC
                LIMIT ?
            ) AS selected
            JOIN readings ON readings.snapshot_id = selected.id
            ORDER BY selected.observed_at ASC, readings.metric ASC
        """
        connection = self._connect()
        try:
            rows = connection.execute(sql, parameters).fetchall()
        except sqlite3.Error as error:
            raise RepositoryError(f"database query failed: {error}") from error
        finally:
            connection.close()
        return _snapshots_from_rows(rows)

    def latest(self, device_id: str) -> ReadingSnapshot | None:
        """Return the newest snapshot for a device."""

        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT snapshots.device_id, snapshots.observed_at,
                       readings.sensor_id, readings.metric, readings.value
                FROM snapshots
                JOIN readings ON readings.snapshot_id = snapshots.id
                WHERE snapshots.id = (
                    SELECT id FROM snapshots
                    WHERE device_id = ?
                    ORDER BY observed_at DESC
                    LIMIT 1
                )
                ORDER BY readings.metric ASC
                """,
                (device_id,),
            ).fetchall()
        except sqlite3.Error as error:
            raise RepositoryError(f"database query failed: {error}") from error
        finally:
            connection.close()
        snapshots = _snapshots_from_rows(rows)
        return snapshots[0] if snapshots else None

    def export_csv(
        self,
        writer: TextIO,
        *,
        device_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> int:
        """Export a device stream using the canonical wide schema."""

        snapshots = self.query(device_id, start=start, end=end)
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

    def count(self, device_id: str | None = None) -> int:
        """Return a diagnostic snapshot count."""

        connection = self._connect()
        try:
            if device_id is None:
                row = connection.execute("SELECT count(*) FROM snapshots").fetchone()
            else:
                row = connection.execute(
                    "SELECT count(*) FROM snapshots WHERE device_id = ?",
                    (device_id,),
                ).fetchone()
            return int(row[0])
        except sqlite3.Error as error:
            raise RepositoryError(f"database count failed: {error}") from error
        finally:
            connection.close()

    def _save_one(
        self,
        connection: sqlite3.Connection,
        snapshot: ReadingSnapshot,
        *,
        source_kind: str,
        source_ref: str | None,
        ingested_at: str,
    ) -> StoreOutcome:
        """Write one snapshot inside an existing transaction."""

        observed_at = _format_timestamp(snapshot.observed_at)
        digest = _snapshot_digest(snapshot)
        existing = connection.execute(
            """
            SELECT id, content_sha256
            FROM snapshots
            WHERE device_id = ? AND observed_at = ?
            """,
            (snapshot.device_id, observed_at),
        ).fetchone()
        if existing is not None:
            if str(existing["content_sha256"]) == digest:
                return StoreOutcome.UNCHANGED
            raise ObservationConflictError(snapshot.device_id, snapshot.observed_at)

        cursor = connection.execute(
            """
            INSERT INTO snapshots(
                device_id, observed_at, source_kind, source_ref,
                content_sha256, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.device_id,
                observed_at,
                source_kind,
                source_ref,
                digest,
                ingested_at,
            ),
        )
        if cursor.lastrowid is None:
            raise RepositoryError("database insert did not return a snapshot identifier")
        snapshot_id = cursor.lastrowid
        connection.executemany(
            """
            INSERT INTO readings(snapshot_id, metric, sensor_id, value)
            VALUES (?, ?, ?, ?)
            """,
            (
                (snapshot_id, reading.metric.value, reading.sensor_id, reading.value)
                for reading in snapshot.readings
            ),
        )
        return StoreOutcome.INSERTED

    def _connect(self) -> sqlite3.Connection:
        """Open one configured connection."""

        try:
            connection = sqlite3.connect(
                self._path,
                timeout=self._busy_timeout_ms / 1000.0,
                isolation_level=None,
                uri=self._is_memory,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
            return connection
        except sqlite3.Error as error:
            raise RepositoryError(f"cannot open database: {error}") from error


def _snapshot_digest(snapshot: ReadingSnapshot) -> str:
    """Hash a canonical representation independent of source metadata."""

    payload = {
        "device_id": snapshot.device_id,
        "observed_at": _format_timestamp(snapshot.observed_at),
        "readings": [
            {
                "metric": reading.metric.value,
                "sensor_id": reading.sensor_id,
                "value": (0.0 if reading.value == 0.0 else reading.value).hex(),
            }
            for reading in snapshot.readings
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _snapshots_from_rows(rows: list[sqlite3.Row]) -> tuple[ReadingSnapshot, ...]:
    """Rebuild immutable snapshots from joined rows."""

    grouped: dict[tuple[str, str], list[SensorReading]] = {}
    for row in rows:
        key = (str(row["device_id"]), str(row["observed_at"]))
        grouped.setdefault(key, []).append(
            SensorReading(
                sensor_id=str(row["sensor_id"]),
                metric=Metric(str(row["metric"])),
                value=float(row["value"]),
                observed_at=_parse_timestamp(str(row["observed_at"])),
            )
        )
    return tuple(
        ReadingSnapshot(
            device_id=device_id,
            observed_at=_parse_timestamp(observed_at),
            readings=tuple(readings),
        )
        for (device_id, observed_at), readings in grouped.items()
    )


def _format_timestamp(value: datetime) -> str:
    """Serialize an aware timestamp as fixed-width UTC RFC 3339."""

    normalized = require_aware_utc(value)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    """Parse timestamps written by this repository."""

    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _format_number(value: float) -> str:
    """Serialize a finite float compactly and deterministically."""

    if value == 0.0:
        return "0"
    return repr(value)
