"""Strict Paho MQTT telemetry adapter with deterministic direct injection."""

from __future__ import annotations

import ipaddress
import json
import re
import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import Any, TypeVar

from paho.mqtt import MQTTException
from paho.mqtt import client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from pydantic import SecretStr, ValidationError

from greenhouse_steward.domain import Metric, SensorReading
from greenhouse_steward.ports import ReadingSnapshot

_PAYLOAD_LIMIT_BYTES = 16 * 1024
_DEVICE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_TOPIC_PATTERN = re.compile(r"^greenhouse/([^/]+)/telemetry$")
_SUBSCRIPTION_PATTERN = re.compile(r"^greenhouse/(?:\+|[A-Za-z0-9][A-Za-z0-9._-]{0,63})/telemetry$")
_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)
_READING_KEYS = frozenset(metric.value for metric in Metric)
T = TypeVar("T")


class MqttAdapterError(ValueError):
    """Base class for MQTT configuration and payload failures."""


class MqttConfigurationError(MqttAdapterError):
    """MQTT settings are unsafe or inconsistent."""


class MqttPayloadError(MqttAdapterError):
    """A telemetry payload violates the strict contract."""


class DuplicateJsonKeyError(MqttPayloadError):
    """A JSON object repeats a key."""


class RetainedMessageError(MqttPayloadError):
    """Stale retained telemetry is disabled."""


class MqttConnectionError(MqttAdapterError):
    """The broker connection failed without a plaintext fallback."""


class MqttDispatchError(MqttAdapterError):
    """The configured snapshot sink rejected a decoded payload."""


@dataclass(frozen=True, slots=True)
class MqttTlsConfig:
    """TLS defaults that verify certificates and hostnames."""

    enabled: bool = True
    ca_file: Path | None = None
    cert_file: Path | None = None
    key_file: Path | None = None
    allow_plaintext_localhost: bool = False

    def __post_init__(self) -> None:
        """Require client certificate material in pairs."""

        if type(self.enabled) is not bool or type(self.allow_plaintext_localhost) is not bool:
            raise MqttConfigurationError("MQTT TLS flags must be booleans")
        if (self.cert_file is None) != (self.key_file is None):
            raise MqttConfigurationError(
                "MQTT client certificate and private key must be supplied together"
            )


@dataclass(frozen=True, slots=True)
class MqttConfig:
    """Connection configuration with TLS and QoS 1 safe defaults."""

    host: str
    port: int = 8883
    topic: str = "greenhouse/+/telemetry"
    client_id: str = "greenhouse-steward"
    qos: int = 1
    keepalive_seconds: int = 60
    username: str | None = None
    password: SecretStr | None = None
    tls: MqttTlsConfig = field(default_factory=MqttTlsConfig)
    accept_retained: bool = False

    def __post_init__(self) -> None:
        """Validate settings without making a network connection."""

        normalized_host = self.host.strip()
        if not normalized_host:
            raise MqttConfigurationError("MQTT host must not be blank")
        if (
            type(self.port) is not int
            or type(self.qos) is not int
            or type(self.keepalive_seconds) is not int
        ):
            raise MqttConfigurationError("MQTT port, qos, and keepalive must be integers")
        if type(self.accept_retained) is not bool:
            raise MqttConfigurationError("accept_retained must be a boolean")
        if not 1 <= self.port <= 65_535:
            raise MqttConfigurationError("MQTT port must be between 1 and 65535")
        if _SUBSCRIPTION_PATTERN.fullmatch(self.topic) is None:
            raise MqttConfigurationError(
                "MQTT topic must match greenhouse/{device-or-plus}/telemetry"
            )
        if not self.client_id.strip() or len(self.client_id) > 128:
            raise MqttConfigurationError("MQTT client_id must be 1-128 characters")
        if self.qos not in {0, 1, 2}:
            raise MqttConfigurationError("MQTT qos must be 0, 1, or 2")
        if not 1 <= self.keepalive_seconds <= 65_535:
            raise MqttConfigurationError("MQTT keepalive must be between 1 and 65535")
        if self.password is not None and self.username is None:
            raise MqttConfigurationError("MQTT password requires a username")
        if not self.tls.enabled and (
            not self.tls.allow_plaintext_localhost or not _is_loopback(normalized_host)
        ):
            raise MqttConfigurationError(
                "plaintext MQTT is allowed only for an explicitly enabled loopback broker"
            )
        object.__setattr__(self, "host", normalized_host)


ClientFactory = Callable[[MqttConfig], mqtt.Client]
SnapshotSink = Callable[[ReadingSnapshot], T]
ErrorSink = Callable[[MqttAdapterError], None]


class PahoMqttAdapter[T]:
    """Decode MQTT messages and synchronously dispatch complete snapshots."""

    def __init__(
        self,
        config: MqttConfig,
        sink: SnapshotSink[T],
        *,
        error_sink: ErrorSink,
        client_factory: ClientFactory | None = None,
    ) -> None:
        """Create a disconnected adapter."""

        self.config = config
        self._sink = sink
        self._error_sink = error_sink
        self._client_factory = client_factory or _default_client_factory
        self._client: mqtt.Client | None = None

    def decode_payload(
        self,
        topic: str,
        payload: bytes,
        *,
        retained: bool = False,
    ) -> ReadingSnapshot:
        """Decode one strict telemetry message without broker access."""

        if retained and not self.config.accept_retained:
            raise RetainedMessageError("retained MQTT telemetry is disabled")
        topic_match = _TOPIC_PATTERN.fullmatch(topic)
        if topic_match is None:
            raise MqttPayloadError("MQTT topic must match greenhouse/{device}/telemetry")
        topic_device = topic_match.group(1)
        if _DEVICE_PATTERN.fullmatch(topic_device) is None:
            raise MqttPayloadError("MQTT topic contains an invalid device identifier")
        if len(payload) > _PAYLOAD_LIMIT_BYTES:
            raise MqttPayloadError(f"MQTT payload exceeds the {_PAYLOAD_LIMIT_BYTES}-byte limit")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise MqttPayloadError("MQTT payload must be UTF-8") from error
        try:
            document = json.loads(
                text,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_nonstandard_constant,
            )
        except DuplicateJsonKeyError:
            raise
        except (json.JSONDecodeError, RecursionError, ValueError) as error:
            raise MqttPayloadError("MQTT payload must be strict JSON") from error
        if not isinstance(document, dict):
            raise MqttPayloadError("MQTT payload root must be an object")
        expected_top = {"schema_version", "device_id", "timestamp", "readings"}
        if set(document) != expected_top:
            raise MqttPayloadError(f"MQTT payload keys must be exactly {sorted(expected_top)!r}")
        version = document["schema_version"]
        if type(version) is not int or version != 1:
            raise MqttPayloadError("unsupported MQTT payload schema_version")
        device_id = document["device_id"]
        if not isinstance(device_id, str) or _DEVICE_PATTERN.fullmatch(device_id) is None:
            raise MqttPayloadError("MQTT payload device_id is invalid")
        if device_id != topic_device:
            raise MqttPayloadError("MQTT topic device does not match payload device_id")
        timestamp = document["timestamp"]
        if not isinstance(timestamp, str):
            raise MqttPayloadError("MQTT timestamp must be a string")
        observed_at = _parse_timestamp(timestamp)
        values = document["readings"]
        if not isinstance(values, dict) or set(values) != _READING_KEYS:
            raise MqttPayloadError(f"MQTT readings keys must be exactly {sorted(_READING_KEYS)!r}")

        readings: list[SensorReading] = []
        for metric in Metric:
            raw_value = values[metric.value]
            if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
                raise MqttPayloadError(f"{metric.value} must be a JSON number")
            try:
                value = float(raw_value)
            except (OverflowError, ValueError) as error:
                raise MqttPayloadError(f"{metric.value} must be a finite number") from error
            if not isfinite(value):
                raise MqttPayloadError(f"{metric.value} must be finite")
            try:
                readings.append(
                    SensorReading(
                        sensor_id=f"{device_id}:{metric.value}",
                        metric=metric,
                        value=value,
                        observed_at=observed_at,
                    )
                )
            except ValidationError as error:
                raise MqttPayloadError(f"invalid {metric.value} reading") from error
        return ReadingSnapshot(
            device_id=device_id,
            observed_at=observed_at,
            readings=tuple(readings),
        )

    def feed_payload(
        self,
        topic: str,
        payload: bytes,
        *,
        retained: bool = False,
    ) -> T:
        """Run the same decode-and-dispatch path used by Paho callbacks."""

        snapshot = self.decode_payload(topic, payload, retained=retained)
        try:
            return self._sink(snapshot)
        except Exception as error:
            raise MqttDispatchError("MQTT snapshot sink rejected the payload") from error

    def connect(self) -> None:
        """Configure TLS and connect; never downgrade to plaintext."""

        try:
            client = self._client_factory(self.config)
            client.on_connect = self._on_connect
            client.on_message = self._on_message
            if self.config.username is not None:
                password = (
                    None
                    if self.config.password is None
                    else self.config.password.get_secret_value()
                )
                client.username_pw_set(self.config.username, password=password)
            if self.config.tls.enabled:
                context = ssl.create_default_context(
                    cafile=(
                        None if self.config.tls.ca_file is None else str(self.config.tls.ca_file)
                    )
                )
                context.check_hostname = True
                context.verify_mode = ssl.CERT_REQUIRED
                if self.config.tls.cert_file is not None:
                    context.load_cert_chain(
                        certfile=str(self.config.tls.cert_file),
                        keyfile=str(self.config.tls.key_file),
                    )
                client.tls_set_context(context)
            client.connect(
                self.config.host,
                self.config.port,
                keepalive=self.config.keepalive_seconds,
            )
        except (OSError, MQTTException, ssl.SSLError, ValueError) as error:
            raise MqttConnectionError("MQTT broker connection failed") from error
        self._client = client

    def loop_start(self) -> None:
        """Start Paho's background network loop after connecting."""

        if self._client is None:
            raise MqttConnectionError("MQTT adapter is not connected")
        self._client.loop_start()

    def stop(self) -> None:
        """Stop and disconnect idempotently."""

        client = self._client
        self._client = None
        if client is None:
            return
        client.loop_stop()
        client.disconnect()

    def _on_connect(
        self,
        client: mqtt.Client,
        _userdata: object,
        _flags: Any,
        reason_code: Any,
        _properties: Any,
    ) -> None:
        """Subscribe after a successful MQTT v5 connection."""

        if bool(getattr(reason_code, "is_failure", False)):
            self._report_error(MqttConnectionError("MQTT broker rejected the connection"))
            return
        client.subscribe(self.config.topic, qos=self.config.qos)

    def _on_message(
        self,
        _client: mqtt.Client,
        _userdata: object,
        message: mqtt.MQTTMessage,
    ) -> None:
        """Route network messages through deterministic feed_payload."""

        try:
            self.feed_payload(
                message.topic,
                bytes(message.payload),
                retained=bool(message.retain),
            )
        except MqttAdapterError as error:
            self._report_error(error)

    def _report_error(self, error: MqttAdapterError) -> None:
        """Prevent an error-reporting callback from killing Paho's loop."""

        try:
            self._error_sink(error)
        except Exception:
            return


def _default_client_factory(config: MqttConfig) -> mqtt.Client:
    """Create a modern Paho v2 MQTT v5 client."""

    return mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=config.client_id,
        protocol=mqtt.MQTTv5,
    )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject JSON ambiguity at every object depth."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKeyError("MQTT payload contains a duplicate JSON key")
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> object:
    """Reject NaN and Infinity extensions accepted by Python's decoder."""

    raise MqttPayloadError(f"non-standard JSON number is forbidden: {value}")


def _parse_timestamp(raw: str) -> datetime:
    """Parse strict timezone-aware RFC 3339."""

    if _TIMESTAMP_PATTERN.fullmatch(raw) is None:
        raise MqttPayloadError("MQTT timestamp must be RFC 3339 with a timezone")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise MqttPayloadError("MQTT timestamp is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MqttPayloadError("MQTT timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _is_loopback(host: str) -> bool:
    """Recognize explicit loopback names and addresses."""

    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
