"""Shared facade tests using real parsing, profiles, rules, and persistence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from greenhouse_steward.adapters import (
    JsonProfileStore,
    MqttAdapterError,
    MqttConfig,
    SQLiteObservationRepository,
    StrictCsvSource,
)
from greenhouse_steward.application import (
    AnalysisMode,
    ApplicationInputError,
    GreenhouseApplication,
    MqttRunner,
    RelaySafetyError,
    report_to_dict,
)
from greenhouse_steward.domain import FrozenClock, Metric, RelayState, SensorReading
from greenhouse_steward.ports import ReadingSnapshot


def _snapshot(device_id: str, observed_at: datetime, *, soil: float = 30.0) -> ReadingSnapshot:
    values = {
        Metric.TEMPERATURE: 22.0,
        Metric.HUMIDITY: 65.0,
        Metric.SOIL_MOISTURE: soil,
        Metric.LIGHT: 20_000.0,
    }
    return ReadingSnapshot(
        device_id=device_id,
        observed_at=observed_at,
        readings=tuple(
            SensorReading(
                sensor_id=f"{device_id}:{metric.value}",
                metric=metric,
                value=values[metric],
                observed_at=observed_at,
            )
            for metric in Metric
        ),
    )


def test_csv_analysis_persists_status_and_both_exports(
    facade: GreenhouseApplication,
    dry_csv: bytes,
) -> None:
    """CSV input reaches storage and all report surfaces without mock data."""

    report = facade.analyze_csv(
        dry_csv,
        device_id="interface-01",
        profile_slug="tomato",
        mode=AnalysisMode.HISTORICAL,
        source_name="../readings.csv",
    )

    assert report.inserted == 2
    assert report.source_name == "readings.csv"
    assert report.monitoring.history_snapshot_count == 2
    assert report.monitoring.evaluated_at == report.monitoring.latest_snapshot.observed_at

    status = report_to_dict(
        facade.status(
            "interface-01",
            profile_slug="tomato",
            mode=AnalysisMode.HISTORICAL,
        )
    )
    assert status["history_reading_count"] == 8
    assert b'"device_id": "interface-01"' in facade.export_json(
        "interface-01",
        profile_slug="tomato",
        mode=AnalysisMode.HISTORICAL,
    )
    exported_csv = facade.export_csv("interface-01").decode()
    assert exported_csv.startswith(
        "timestamp,temperature_c,humidity_pct,soil_moisture_pct,light_lux\n"
    )
    assert len(exported_csv.splitlines()) == 3


def test_repeated_csv_is_idempotent(
    facade: GreenhouseApplication,
    dry_csv: bytes,
) -> None:
    """The interface reports unchanged storage rather than duplicating rows."""

    first = facade.analyze_csv(
        dry_csv,
        device_id="interface-02",
        profile_slug="tomato",
        mode="historical",
        source_name="first.csv",
    )
    second = facade.analyze_csv(
        dry_csv,
        device_id="interface-02",
        profile_slug="tomato",
        mode="historical",
        source_name="second.csv",
    )

    assert first.inserted == 2
    assert second.inserted == 0
    assert second.unchanged == 2


def test_bundled_sample_uses_packaged_historical_data(
    facade: GreenhouseApplication,
) -> None:
    """Sample analysis reads the installed resource and persists every row."""

    report = facade.analyze_sample(
        sample_slug="tomato-7d",
        profile_slug="tomato",
    )

    assert report.source_kind == "sample"
    assert report.analysis_mode == AnalysisMode.HISTORICAL
    assert report.inserted == 672
    assert report.monitoring.history_snapshot_count == 672


def test_relay_is_live_only_and_enforces_profile_cap(
    facade: GreenhouseApplication,
    dry_csv: bytes,
) -> None:
    """A dry live device may simulate watering, but never beyond the hard cap."""

    facade.analyze_csv(
        dry_csv,
        device_id="relay-01",
        profile_slug="tomato",
        mode=AnalysisMode.LIVE,
        source_name="relay.csv",
    )

    with pytest.raises(RelaySafetyError, match="historical"):
        facade.simulate_relay(
            "relay-01",
            profile_slug="tomato",
            mode=AnalysisMode.HISTORICAL,
            requested_seconds=100,
        )

    snapshot = facade.simulate_relay(
        "relay-01",
        profile_slug="tomato",
        mode=AnalysisMode.LIVE,
        requested_seconds=100,
    )
    assert snapshot.state == RelayState.ON
    assert snapshot.applied_seconds == 30
    assert snapshot.capped


def test_mqtt_validation_never_discloses_password() -> None:
    """Valid and invalid config diagnostics omit secret input values."""

    clock = FrozenClock(datetime.fromisoformat("2026-01-15T12:00:00+00:00"))
    app = GreenhouseApplication(
        csv_source=StrictCsvSource(),
        profiles=JsonProfileStore(),
        repository=SQLiteObservationRepository(":memory:", clock=clock),
        clock=clock,
    )
    secret = "correct-horse-battery-staple"
    document: dict[str, object] = {
        "host": "localhost",
        "username": "grower",
        "password": secret,
        "tls": {
            "enabled": False,
            "allow_plaintext_localhost": True,
        },
    }

    result = app.validate_mqtt_config(document)

    assert result["has_password"] is True
    assert secret not in repr(result)

    document["password"] = {"unexpected": secret}
    with pytest.raises(ApplicationInputError) as caught:
        app.validate_mqtt_config(document)
    assert secret not in str(caught.value)


class _FakeMqttRunner:
    """Synchronous runner that exercises bounds without sleeping or networking."""

    def __init__(
        self,
        snapshots: tuple[ReadingSnapshot, ...],
        sink: Callable[[ReadingSnapshot], object],
        error_sink: Callable[[MqttAdapterError], None],
    ) -> None:
        self._snapshots = snapshots
        self._sink = sink
        self._error_sink = error_sink
        self.connected = False
        self.started = False
        self.stopped = False

    def connect(self) -> None:
        self.connected = True

    def loop_start(self) -> None:
        self.started = True
        self._error_sink(MqttAdapterError("rejected synthetic payload"))
        for snapshot in self._snapshots:
            self._sink(snapshot)

    def stop(self) -> None:
        self.stopped = True


def test_mqtt_ingest_is_message_bounded_persistent_and_stops_cleanly(
    tmp_path: Path,
    fixed_now: datetime,
) -> None:
    """A fake client proves the production lifecycle without network or sleeps."""

    clock = FrozenClock(fixed_now)
    repository = SQLiteObservationRepository(tmp_path / "mqtt.sqlite3", clock=clock)
    snapshots = tuple(
        _snapshot("mqtt-01", fixed_now + timedelta(seconds=index)) for index in range(3)
    )
    runners: list[_FakeMqttRunner] = []
    waits: list[float] = []

    def factory(
        _config: MqttConfig,
        sink: Callable[[ReadingSnapshot], object],
        error_sink: Callable[[MqttAdapterError], None],
    ) -> MqttRunner:
        runner = _FakeMqttRunner(snapshots, sink, error_sink)
        runners.append(runner)
        return runner

    def waiter(_event: object, timeout: float) -> bool:
        waits.append(timeout)
        return True

    app = GreenhouseApplication(
        csv_source=StrictCsvSource(),
        profiles=JsonProfileStore(),
        repository=repository,
        clock=clock,
        mqtt_runner_factory=factory,
        mqtt_waiter=waiter,
    )
    result = app.ingest_mqtt(
        {
            "host": "localhost",
            "tls": {
                "enabled": False,
                "allow_plaintext_localhost": True,
            },
        },
        profile_slug="tomato",
        duration_seconds=12.5,
        max_messages=2,
    )

    assert result.accepted == 1
    assert result.rejected == 1
    assert result.last_error == "rejected synthetic payload"
    assert waits == [12.5]
    assert runners[0].connected and runners[0].started and runners[0].stopped
    assert len(repository.query("mqtt-01")) == 1
