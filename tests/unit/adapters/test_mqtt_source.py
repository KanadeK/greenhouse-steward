"""Versioned nested MQTT payload tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import SecretStr

from greenhouse_steward.adapters.mqtt_source import (
    DuplicateJsonKeyError,
    MqttConfig,
    MqttConfigurationError,
    MqttConnectionError,
    MqttPayloadError,
    MqttTlsConfig,
    PahoMqttAdapter,
    RetainedMessageError,
)
from greenhouse_steward.domain import Metric
from greenhouse_steward.ports import ReadingSnapshot


def _payload(**updates: object) -> bytes:
    document: dict[str, object] = {
        "schema_version": 1,
        "device_id": "esp32-demo-01",
        "timestamp": "2026-01-05T00:00:00Z",
        "readings": {
            "temperature_c": 22.4,
            "humidity_pct": 63.1,
            "soil_moisture_pct": 48.8,
            "light_lux": 12400.0,
        },
    }
    document.update(updates)
    return json.dumps(document).encode()


def test_feed_payload_uses_nested_versioned_contract_and_dispatches() -> None:
    received: list[ReadingSnapshot] = []
    adapter = PahoMqttAdapter(
        MqttConfig(host="broker.example"),
        lambda snapshot: received.append(snapshot) or snapshot.device_id,
        error_sink=lambda _error: None,
    )

    result = adapter.feed_payload(
        "greenhouse/esp32-demo-01/telemetry",
        _payload(),
    )

    assert result == "esp32-demo-01"
    assert len(received) == 1
    assert set(received[0].by_metric) == set(Metric)


def test_flat_payload_and_duplicate_keys_are_rejected() -> None:
    adapter = PahoMqttAdapter(
        MqttConfig(host="broker.example"),
        lambda snapshot: snapshot,
        error_sink=lambda _error: None,
    )
    flat = (
        b'{"schema_version":1,"device_id":"esp32-demo-01",'
        b'"observed_at":"2026-01-05T00:00:00Z","temperature_c":20}'
    )
    duplicate = (
        b'{"schema_version":1,"device_id":"esp32-demo-01",'
        b'"device_id":"other","timestamp":"2026-01-05T00:00:00Z",'
        b'"readings":{"temperature_c":20,"humidity_pct":60,'
        b'"soil_moisture_pct":40,"light_lux":1000}}'
    )

    with pytest.raises(MqttPayloadError):
        adapter.decode_payload("greenhouse/esp32-demo-01/telemetry", flat)
    with pytest.raises(MqttPayloadError):
        adapter.decode_payload("greenhouse/esp32-demo-01/telemetry", duplicate)


def test_duplicate_key_and_tls_failures_do_not_disclose_sensitive_input() -> None:
    adapter = PahoMqttAdapter(
        MqttConfig(host="broker.example"),
        lambda snapshot: snapshot,
        error_sink=lambda _error: None,
    )
    sensitive_key = "private-operator-label"
    payload = f'{{"{sensitive_key}":1,"{sensitive_key}":2}}'.encode()

    with pytest.raises(DuplicateJsonKeyError) as duplicate:
        adapter.decode_payload("greenhouse/esp32-demo-01/telemetry", payload)
    assert sensitive_key not in str(duplicate.value)

    sensitive_path = "private-deployment-ca-name.pem"
    tls_adapter = PahoMqttAdapter(
        MqttConfig(
            host="broker.example",
            tls=MqttTlsConfig(ca_file=Path(sensitive_path)),
        ),
        lambda snapshot: snapshot,
        error_sink=lambda _error: None,
    )
    with pytest.raises(MqttConnectionError) as connection:
        tls_adapter.connect()
    assert sensitive_path not in str(connection.value)


def test_retained_and_huge_integer_are_safe_typed_errors() -> None:
    adapter = PahoMqttAdapter(
        MqttConfig(host="broker.example"),
        lambda snapshot: snapshot,
        error_sink=lambda _error: None,
    )
    with pytest.raises(RetainedMessageError):
        adapter.decode_payload(
            "greenhouse/esp32-demo-01/telemetry",
            _payload(),
            retained=True,
        )
    readings = {
        "temperature_c": 10**400,
        "humidity_pct": 60,
        "soil_moisture_pct": 40,
        "light_lux": 1000,
    }
    with pytest.raises(MqttPayloadError, match="finite"):
        adapter.decode_payload(
            "greenhouse/esp32-demo-01/telemetry",
            _payload(readings=readings),
        )


def test_tls_defaults_and_plaintext_guard() -> None:
    config = MqttConfig(
        host="broker.example",
        username="user",
        password=SecretStr("secret"),
    )
    assert config.port == 8883
    assert config.tls.enabled
    assert "secret" not in repr(config)

    with pytest.raises(MqttConfigurationError, match="loopback"):
        MqttConfig(host="broker.example", port=1883, tls=MqttTlsConfig(enabled=False))
    local = MqttConfig(
        host="127.0.0.1",
        port=1883,
        tls=MqttTlsConfig(enabled=False, allow_plaintext_localhost=True),
    )
    assert not local.tls.enabled
