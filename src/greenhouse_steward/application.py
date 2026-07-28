"""Shared application facade for the CLI and local web interface."""

from __future__ import annotations

import csv
import io
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from pathlib import Path
from threading import Event, Lock, RLock
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from greenhouse_steward.adapters import (
    JsonProfileStore,
    MqttAdapterError,
    MqttConfig,
    MqttTlsConfig,
    PahoMqttAdapter,
    SQLiteObservationRepository,
    StrictCsvSource,
)
from greenhouse_steward.domain import (
    Clock,
    Metric,
    RelaySimulator,
    RelaySnapshot,
    SystemClock,
)
from greenhouse_steward.ports import ObservationRepository, ProfileProvider, ReadingSnapshot
from greenhouse_steward.services import BatchIngestResult, MonitoringResult, MonitoringService

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_SAMPLE_PROFILES = {
    "tomato-7d": "tomato",
    "herb-7d": "herb",
}
_METRIC_LABELS = {
    Metric.TEMPERATURE: "Temperature",
    Metric.HUMIDITY: "Humidity",
    Metric.SOIL_MOISTURE: "Soil moisture",
    Metric.LIGHT: "Light",
}


class AnalysisMode(StrEnum):
    """Time semantics used for status evaluation."""

    HISTORICAL = "historical"
    LIVE = "live"


class ApplicationError(RuntimeError):
    """Safe base error for user-facing interface failures."""


class ApplicationInputError(ApplicationError):
    """A supplied command, form, or document is invalid."""


class AnalysisNotFoundError(ApplicationError):
    """No persisted observations exist for the requested device."""


class SampleDataMissingError(ApplicationError):
    """A bundled deterministic sample is not installed."""


class RelaySafetyError(ApplicationError):
    """A relay simulation request was rejected by safety policy."""


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    """Interface-oriented metadata plus a real monitoring result."""

    monitoring: MonitoringResult
    analysis_mode: AnalysisMode
    source_kind: str
    source_name: str
    inserted: int
    unchanged: int


@dataclass(frozen=True, slots=True)
class MqttIngestResult:
    """Real counts from one bounded MQTT network-loop session."""

    accepted: int
    rejected: int
    interrupted: bool
    last_error: str | None


class MqttRunner(Protocol):
    """Narrow lifecycle used by bounded MQTT ingestion."""

    def connect(self) -> None:
        """Connect without starting the background loop."""

    def loop_start(self) -> None:
        """Start processing broker traffic."""

    def stop(self) -> None:
        """Stop and disconnect idempotently."""


MqttRunnerFactory = Callable[
    [
        MqttConfig,
        Callable[[ReadingSnapshot], object],
        Callable[[MqttAdapterError], None],
    ],
    MqttRunner,
]
MqttWaiter = Callable[[Event, float], bool]


class _MqttTlsDocument(BaseModel):
    """Validated JSON representation of MQTT TLS settings."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    ca_file: Path | None = None
    cert_file: Path | None = None
    key_file: Path | None = None
    allow_plaintext_localhost: bool = False


class _MqttDocument(BaseModel):
    """Validated MQTT config file that keeps passwords secret."""

    model_config = ConfigDict(extra="forbid")

    host: str
    port: int = 8883
    topic: str = "greenhouse/+/telemetry"
    client_id: str = "greenhouse-steward"
    qos: int = 1
    keepalive_seconds: int = 60
    username: str | None = None
    password: SecretStr | None = None
    tls: _MqttTlsDocument = Field(default_factory=_MqttTlsDocument)
    accept_retained: bool = False


class GreenhouseApplication:
    """One facade shared by every user-facing transport."""

    def __init__(
        self,
        *,
        csv_source: StrictCsvSource,
        profiles: ProfileProvider,
        repository: ObservationRepository,
        clock: Clock,
        mqtt_runner_factory: MqttRunnerFactory | None = None,
        mqtt_waiter: MqttWaiter | None = None,
    ) -> None:
        """Compose existing adapters and services without duplicating domain logic."""

        self._csv_source = csv_source
        self._profiles = profiles
        self._repository = repository
        self._clock = clock
        self._monitoring = MonitoringService(repository, profiles, clock=clock)
        self._relay_simulators: dict[tuple[str, str], RelaySimulator] = {}
        self._relay_lock = RLock()
        self._mqtt_runner_factory = mqtt_runner_factory or _default_mqtt_runner
        self._mqtt_waiter = mqtt_waiter or _default_mqtt_waiter

    def list_profiles(self) -> tuple[dict[str, object], ...]:
        """Return complete, safe profile summaries for UI selection."""

        summaries: list[dict[str, object]] = []
        for slug in self._profiles.list_slugs():
            bundle = self._profiles.load(slug)
            summaries.append(
                {
                    "slug": bundle.profile.slug,
                    "display_name": bundle.profile.display_name,
                    "targets": {
                        metric.value: {
                            "label": _METRIC_LABELS[metric],
                            "unit": metric.unit,
                            "low": target.low,
                            "high": target.high,
                        }
                        for metric, target in bundle.profile.targets.items()
                    },
                    "watering": bundle.profile.watering.model_dump(mode="json"),
                    "relay_max_on_seconds": bundle.safety.relay_max_on_seconds,
                }
            )
        return tuple(summaries)

    def analyze_csv(
        self,
        payload: bytes,
        *,
        device_id: str,
        profile_slug: str,
        mode: AnalysisMode | str,
        source_name: str,
    ) -> AnalysisReport:
        """Strictly parse, atomically persist, and evaluate one real CSV payload."""

        if not payload:
            raise ApplicationInputError("CSV upload is empty")
        if len(payload) > _MAX_UPLOAD_BYTES:
            raise ApplicationInputError("CSV upload exceeds the 10 MiB limit")
        normalized_mode = _parse_mode(mode)
        safe_source_name = Path(source_name).name.strip() or "upload.csv"
        if len(safe_source_name) > 255:
            raise ApplicationInputError("CSV filename must not exceed 255 characters")
        try:
            snapshots = self._csv_source.read_bytes(payload, device_id=device_id)
            evaluated_at = (
                snapshots[-1].observed_at if normalized_mode == AnalysisMode.HISTORICAL else None
            )
            result = self._monitoring.ingest_many(
                snapshots,
                profile_slug=profile_slug,
                source_kind="csv",
                source_ref=safe_source_name,
                evaluated_at=evaluated_at,
            )
        except ApplicationError:
            raise
        except (ValueError, OSError, RuntimeError) as error:
            raise ApplicationInputError(str(error)) from error
        return _report_from_batch(
            result,
            mode=normalized_mode,
            source_kind="csv",
            source_name=safe_source_name,
        )

    def analyze_sample(
        self,
        *,
        sample_slug: str,
        profile_slug: str,
    ) -> AnalysisReport:
        """Analyze a packaged seven-day fixture as an explicit historical replay."""

        expected_profile = _SAMPLE_PROFILES.get(sample_slug)
        if expected_profile is None:
            raise ApplicationInputError(f"unknown sample: {sample_slug}")
        if profile_slug != expected_profile:
            raise ApplicationInputError(f"sample {sample_slug} requires profile {expected_profile}")
        sample_name = f"{sample_slug}.csv"
        sample_resource = (
            resources.files("greenhouse_steward.sample_data").joinpath("data").joinpath(sample_name)
        )
        if not sample_resource.is_file():
            raise SampleDataMissingError(
                f"bundled sample is missing: sample_data/data/{sample_name}"
            )
        try:
            payload = sample_resource.read_bytes()
        except OSError as error:
            raise SampleDataMissingError(f"cannot read bundled sample: {sample_name}") from error
        report = self.analyze_csv(
            payload,
            device_id=f"sample-{expected_profile}",
            profile_slug=profile_slug,
            mode=AnalysisMode.HISTORICAL,
            source_name=sample_name,
        )
        return AnalysisReport(
            monitoring=report.monitoring,
            analysis_mode=report.analysis_mode,
            source_kind="sample",
            source_name=sample_name,
            inserted=report.inserted,
            unchanged=report.unchanged,
        )

    def status(
        self,
        device_id: str,
        *,
        profile_slug: str,
        mode: AnalysisMode | str,
    ) -> AnalysisReport:
        """Evaluate already-persisted observations in live or replay time."""

        normalized_mode = _parse_mode(mode)
        latest = self._repository.latest(device_id)
        if latest is None:
            raise AnalysisNotFoundError(f"no observations found for device {device_id!r}")
        evaluated_at = latest.observed_at if normalized_mode == AnalysisMode.HISTORICAL else None
        try:
            monitoring = self._monitoring.current_status(
                device_id,
                profile_slug=profile_slug,
                evaluated_at=evaluated_at,
            )
        except (ValueError, OSError, RuntimeError) as error:
            raise ApplicationInputError(str(error)) from error
        return AnalysisReport(
            monitoring=monitoring,
            analysis_mode=normalized_mode,
            source_kind="persisted",
            source_name=device_id,
            inserted=0,
            unchanged=0,
        )

    def export_json(
        self,
        device_id: str,
        *,
        profile_slug: str,
        mode: AnalysisMode | str,
    ) -> bytes:
        """Export a complete, deterministic status report."""

        report = self.status(device_id, profile_slug=profile_slug, mode=mode)
        return (
            json.dumps(
                report_to_dict(report),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")

    def export_csv(self, device_id: str) -> bytes:
        """Export persisted observations using the canonical adapter schema."""

        writer = io.StringIO(newline="")
        try:
            count = self._repository.export_csv(writer, device_id=device_id)
        except (ValueError, OSError, RuntimeError) as error:
            raise ApplicationInputError(str(error)) from error
        if count == 0:
            raise AnalysisNotFoundError(f"no observations found for device {device_id!r}")
        return writer.getvalue().encode("utf-8")

    def simulate_relay(
        self,
        device_id: str,
        *,
        profile_slug: str,
        mode: AnalysisMode | str,
        requested_seconds: int,
    ) -> RelaySnapshot:
        """Apply a current live decision to the in-memory simulator only."""

        normalized_mode = _parse_mode(mode)
        if normalized_mode != AnalysisMode.LIVE:
            raise RelaySafetyError("relay simulation is disabled for historical replay")
        if requested_seconds <= 0:
            raise ApplicationInputError("requested relay duration must be positive")
        report = self.status(
            device_id,
            profile_slug=profile_slug,
            mode=AnalysisMode.LIVE,
        )
        bundle = self._profiles.load(profile_slug)
        key = (device_id, profile_slug)
        with self._relay_lock:
            simulator = self._relay_simulators.get(key)
            if simulator is None:
                simulator = RelaySimulator(
                    self._clock,
                    max_on_seconds=bundle.safety.relay_max_on_seconds,
                )
                self._relay_simulators[key] = simulator
            snapshot = simulator.apply(
                report.monitoring.evaluation.watering,
                requested_seconds=requested_seconds,
            )
        if not report.monitoring.evaluation.watering.relay_permitted:
            raise RelaySafetyError(
                "relay simulation rejected: "
                + ", ".join(report.monitoring.evaluation.watering.reason_codes)
            )
        return snapshot

    def relay_status(
        self,
        device_id: str,
        *,
        profile_slug: str,
    ) -> RelaySnapshot | None:
        """Return and refresh the active simulator state, if any."""

        with self._relay_lock:
            simulator = self._relay_simulators.get((device_id, profile_slug))
            return None if simulator is None else simulator.status()

    def validate_mqtt_config(
        self,
        document: Mapping[str, object],
    ) -> dict[str, object]:
        """Validate MQTT settings without connecting or disclosing secrets."""

        config = _mqtt_config_from_document(document)
        return {
            "valid": True,
            "host": config.host,
            "port": config.port,
            "topic": config.topic,
            "qos": config.qos,
            "tls_enabled": config.tls.enabled,
            "username": config.username,
            "has_password": config.password is not None,
            "accept_retained": config.accept_retained,
        }

    def ingest_mqtt(
        self,
        document: Mapping[str, object],
        *,
        profile_slug: str,
        duration_seconds: float,
        max_messages: int,
    ) -> MqttIngestResult:
        """Persist MQTT snapshots until the time or message bound is reached."""

        if duration_seconds <= 0 or duration_seconds > 86_400:
            raise ApplicationInputError(
                "MQTT duration must be greater than 0 and at most 86400 seconds"
            )
        if max_messages <= 0 or max_messages > 1_000_000:
            raise ApplicationInputError("MQTT max messages must be between 1 and 1000000")
        config = _mqtt_config_from_document(document)
        try:
            self._profiles.load(profile_slug)
        except (ValueError, OSError, RuntimeError) as error:
            raise ApplicationInputError(str(error)) from error

        complete = Event()
        result_lock = Lock()
        accepted = 0
        rejected = 0
        last_error: str | None = None
        source_ref = f"{config.host}:{config.port}/{config.topic}"

        def accept(snapshot: ReadingSnapshot) -> object:
            nonlocal accepted
            with result_lock:
                if accepted + rejected >= max_messages:
                    complete.set()
                    return None
                outcome = self._monitoring.ingest(
                    snapshot,
                    profile_slug=profile_slug,
                    source_kind="mqtt",
                    source_ref=source_ref,
                )
                accepted += 1
                if accepted + rejected >= max_messages:
                    complete.set()
            return outcome

        def reject(error: MqttAdapterError) -> None:
            nonlocal last_error, rejected
            with result_lock:
                if accepted + rejected >= max_messages:
                    complete.set()
                    return
                rejected += 1
                last_error = str(error)
                if accepted + rejected >= max_messages:
                    complete.set()

        runner = self._mqtt_runner_factory(config, accept, reject)
        interrupted = False
        try:
            runner.connect()
            runner.loop_start()
            self._mqtt_waiter(complete, duration_seconds)
        except KeyboardInterrupt:
            interrupted = True
        except (MqttAdapterError, OSError, RuntimeError, ValueError) as error:
            raise ApplicationInputError(f"MQTT ingestion failed: {error}") from error
        finally:
            try:
                runner.stop()
            except (OSError, RuntimeError, ValueError) as error:
                with result_lock:
                    last_error = f"MQTT shutdown failed: {error}"
        with result_lock:
            return MqttIngestResult(
                accepted=accepted,
                rejected=rejected,
                interrupted=interrupted,
                last_error=last_error,
            )


def create_default_application(
    database_path: Path | str | None = None,
    *,
    clock: Clock | None = None,
) -> GreenhouseApplication:
    """Create the production facade using the existing local adapters."""

    active_clock = clock or SystemClock()
    selected_path = database_path
    if selected_path is None:
        selected_path = os.environ.get(
            "GREENHOUSE_STEWARD_DB",
            str(Path.cwd() / "greenhouse-steward.sqlite3"),
        )
    repository = SQLiteObservationRepository(selected_path, clock=active_clock)
    return GreenhouseApplication(
        csv_source=StrictCsvSource(),
        profiles=JsonProfileStore(),
        repository=repository,
        clock=active_clock,
    )


def report_to_dict(report: AnalysisReport) -> dict[str, object]:
    """Serialize a report for JSON, templates, CLI output, and tests."""

    monitoring = report.monitoring
    evaluation = monitoring.evaluation
    latest_readings: list[dict[str, object]] = []
    for metric in Metric:
        reading = evaluation.latest_readings.get(metric)
        if reading is None:
            latest_readings.append(
                {
                    "metric": metric.value,
                    "label": _METRIC_LABELS[metric],
                    "unit": metric.unit,
                    "available": False,
                }
            )
            continue
        latest_readings.append(
            {
                "metric": metric.value,
                "label": _METRIC_LABELS[metric],
                "unit": metric.unit,
                "available": True,
                "value": reading.value,
                "observed_at": reading.observed_at.isoformat(),
                "sensor_id": reading.sensor_id,
            }
        )
    rules: list[dict[str, object]] = []
    for rule in evaluation.rules:
        payload = rule.model_dump(mode="json")
        payload["unit"] = rule.metric.unit
        payload["metric_label"] = _METRIC_LABELS[rule.metric]
        rules.append(payload)
    return {
        "device_id": monitoring.device_id,
        "profile_slug": monitoring.profile_slug,
        "analysis_mode": report.analysis_mode.value,
        "historical": report.analysis_mode == AnalysisMode.HISTORICAL,
        "source": {
            "kind": report.source_kind,
            "name": report.source_name,
        },
        "storage": {
            "inserted": report.inserted,
            "unchanged": report.unchanged,
        },
        "evaluated_at": monitoring.evaluated_at.isoformat(),
        "history_snapshot_count": monitoring.history_snapshot_count,
        "history_reading_count": monitoring.history_reading_count,
        "system_mode": evaluation.mode.value,
        "offline_metrics": [metric.value for metric in evaluation.offline_metrics],
        "latest_readings": latest_readings,
        "watering": evaluation.watering.model_dump(mode="json"),
        "rules": rules,
        "anomalies": [anomaly.model_dump(mode="json") for anomaly in evaluation.anomalies],
        "trends": {
            "timezone": monitoring.trends.timezone,
            "daily": [aggregate.model_dump(mode="json") for aggregate in monitoring.trends.daily],
            "weekly": [aggregate.model_dump(mode="json") for aggregate in monitoring.trends.weekly],
        },
    }


def report_to_rule_csv(report: AnalysisReport) -> bytes:
    """Export flattened rule evidence when callers need a tabular report."""

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        (
            "rule_id",
            "metric",
            "severity",
            "observed_value",
            "threshold_kind",
            "threshold_low",
            "threshold_high",
            "recommendation",
            "action",
        )
    )
    for rule in report.monitoring.evaluation.rules:
        writer.writerow(
            (
                rule.rule_id,
                rule.metric.value,
                rule.severity.value,
                "" if rule.observed_value is None else rule.observed_value,
                rule.threshold.kind,
                "" if rule.threshold.low is None else rule.threshold.low,
                "" if rule.threshold.high is None else rule.threshold.high,
                rule.recommendation,
                rule.action.value,
            )
        )
    return output.getvalue().encode("utf-8")


def _parse_mode(value: AnalysisMode | str) -> AnalysisMode:
    """Normalize a mode into the stable public enum."""

    try:
        return value if isinstance(value, AnalysisMode) else AnalysisMode(value)
    except ValueError as error:
        raise ApplicationInputError("analysis mode must be 'historical' or 'live'") from error


def _report_from_batch(
    result: BatchIngestResult,
    *,
    mode: AnalysisMode,
    source_kind: str,
    source_name: str,
) -> AnalysisReport:
    """Join existing service output with interface metadata."""

    return AnalysisReport(
        monitoring=result.monitoring,
        analysis_mode=mode,
        source_kind=source_kind,
        source_name=source_name,
        inserted=result.storage.inserted,
        unchanged=result.storage.unchanged,
    )


def _mqtt_config_from_document(document: Mapping[str, object]) -> MqttConfig:
    """Validate a config document without including secret inputs in errors."""

    try:
        parsed = _MqttDocument.model_validate(document)
        tls = MqttTlsConfig(
            enabled=parsed.tls.enabled,
            ca_file=parsed.tls.ca_file,
            cert_file=parsed.tls.cert_file,
            key_file=parsed.tls.key_file,
            allow_plaintext_localhost=parsed.tls.allow_plaintext_localhost,
        )
        return MqttConfig(
            host=parsed.host,
            port=parsed.port,
            topic=parsed.topic,
            client_id=parsed.client_id,
            qos=parsed.qos,
            keepalive_seconds=parsed.keepalive_seconds,
            username=parsed.username,
            password=parsed.password,
            tls=tls,
            accept_retained=parsed.accept_retained,
        )
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors(include_input=False)
        )
        raise ApplicationInputError(f"invalid MQTT configuration: {details}") from error
    except ValueError as error:
        raise ApplicationInputError(f"invalid MQTT configuration: {error}") from error


def _default_mqtt_runner(
    config: MqttConfig,
    sink: Callable[[ReadingSnapshot], object],
    error_sink: Callable[[MqttAdapterError], None],
) -> MqttRunner:
    """Create the production Paho lifecycle behind the testable protocol."""

    return PahoMqttAdapter(config, sink, error_sink=error_sink)


def _default_mqtt_waiter(event: Event, timeout: float) -> bool:
    """Wait for the message limit while retaining a strict duration cap."""

    return event.wait(timeout)
