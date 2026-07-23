"""Host-side contract checks for the ESP32 synthetic firmware."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from greenhouse_steward.adapters.mqtt_source import (
    MqttAdapterError,
    MqttConfig,
    PahoMqttAdapter,
)
from greenhouse_steward.domain import Metric, SensorReading
from greenhouse_steward.ports import ReadingSnapshot

PROJECT_ROOT = Path(__file__).parents[3]
FIRMWARE_ROOT = PROJECT_ROOT / "firmware" / "esp32_synthetic"
SAFETY_HEADER = FIRMWARE_ROOT / "safety.h"
SKETCH = FIRMWARE_ROOT / "esp32_synthetic.ino"
SECRETS_EXAMPLE = FIRMWARE_ROOT / "secrets.example.h"
GOLDEN_PAYLOAD = FIRMWARE_ROOT / "golden_telemetry.json"
HOST_TEST = FIRMWARE_ROOT / "host_safety_test.cpp"

REQUIRED_TOP_LEVEL_FIELDS = {
    "schema_version",
    "device_id",
    "timestamp",
    "readings",
}
REQUIRED_READING_FIELDS = {
    "temperature_c",
    "humidity_pct",
    "soil_moisture_pct",
    "light_lux",
}


def _unsigned_constant(source: str, name: str) -> int:
    match = re.search(rf"\b{name}\s*=\s*([0-9']+)U", source)
    assert match is not None, f"{name} must be an unsigned integer constant"
    return int(match.group(1).replace("'", ""))


def _identity_snapshot(snapshot: ReadingSnapshot) -> ReadingSnapshot:
    return snapshot


def _unexpected_adapter_error(error: MqttAdapterError) -> None:
    raise AssertionError(f"golden MQTT payload raised an adapter error: {error}")


def test_safety_constants_preserve_hard_limit_and_shutdown_margin() -> None:
    source = SAFETY_HEADER.read_text(encoding="utf-8")

    hard_max = _unsigned_constant(source, "kRelayHardMaxMs")
    command_max = _unsigned_constant(source, "kRelayCommandMaxMs")
    watchdog = _unsigned_constant(source, "kWatchdogTimeoutMs")
    cooldown = _unsigned_constant(source, "kRelayCooldownMs")
    command_ttl = _unsigned_constant(source, "kMaxCommandTtlSeconds")
    command_payload = _unsigned_constant(source, "kMaxCommandPayloadBytes")

    assert hard_max == 30_000
    assert command_max + watchdog < hard_max
    assert cooldown >= hard_max
    assert command_ttl == 60
    assert command_payload <= 384
    assert "static_cast<std::uint32_t>(now - started_at)" in source


def test_sketch_defaults_off_and_requires_verified_tls() -> None:
    sketch = SKETCH.read_text(encoding="utf-8")
    secrets = SECRETS_EXAMPLE.read_text(encoding="utf-8")

    assert "#define GREENHOUSE_ENABLE_REAL_RELAY 0" in sketch
    assert "constexpr bool ENABLE_REAL_RELAY = GREENHOUSE_ENABLE_REAL_RELAY == 1;" in sketch
    assert "WiFiClientSecure" in sketch
    assert "setCACert(MQTT_ROOT_CA)" in sketch
    assert "setInsecure" not in sketch
    assert "MQTT_PORT == 8883U" in sketch
    assert "MQTT_PORT = 8883U" in secrets
    assert "esp_task_wdt_reset()" in sketch
    assert "return add_result == ESP_OK;" in sketch
    assert 'forceRelayOff("transport_disconnected"' in sketch
    assert 'forceRelayOff("telemetry_stale"' in sketch
    assert "cappedRelayDurationMs" in sketch
    assert "cooldownComplete" in sketch
    assert "commandTimestampIsFresh" in sketch
    assert "measureJson(document)" in sketch
    assert "length != required_length" in sketch


def test_golden_payload_matches_topic_and_domain_contract() -> None:
    payload = json.loads(GOLDEN_PAYLOAD.read_text(encoding="utf-8"))

    assert set(payload) == REQUIRED_TOP_LEVEL_FIELDS
    assert payload["schema_version"] == 1
    assert not isinstance(payload["schema_version"], bool)
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,48}", payload["device_id"])
    topic = f"greenhouse/{payload['device_id']}/telemetry"
    assert topic == "greenhouse/esp32-synthetic-01/telemetry"
    assert set(payload["readings"]) == REQUIRED_READING_FIELDS

    observed_at = datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00"))
    for metric in Metric:
        reading = SensorReading(
            sensor_id=f"{payload['device_id']}:{metric.value}",
            metric=metric,
            value=payload["readings"][metric.value],
            observed_at=observed_at,
        )
        assert reading.metric.unit

    encoded = json.dumps(payload, separators=(",", ":")).encode()
    assert len(encoded) <= 384

    adapter = PahoMqttAdapter[ReadingSnapshot](
        MqttConfig(host="broker.example.invalid"),
        _identity_snapshot,
        error_sink=_unexpected_adapter_error,
    )
    snapshot = adapter.decode_payload(topic, encoded)
    assert snapshot.device_id == payload["device_id"]
    assert snapshot.observed_at == observed_at
    assert {
        metric.value: reading.value for metric, reading in snapshot.by_metric.items()
    } == payload["readings"]


def test_sketch_emits_every_required_telemetry_field() -> None:
    sketch = SKETCH.read_text(encoding="utf-8")
    publish_start = sketch.index("bool publishTelemetry")
    publish_end = sketch.index("void maintainMqtt", publish_start)
    publish_source = sketch[publish_start:publish_end]

    top_level_assignments = set(re.findall(r'document\["([^"]+)"\]\s*=', publish_source))
    assert top_level_assignments == {"schema_version", "device_id", "timestamp"}
    assert 'document.createNestedObject("readings")' in publish_source
    reading_assignments = set(re.findall(r'readings\["([^"]+)"\]\s*=', publish_source))
    assert reading_assignments == REQUIRED_READING_FIELDS
    assert '"greenhouse/%s/telemetry"' in sketch


def test_host_safety_header_compiles_and_runs_when_compiler_is_available(
    tmp_path: Path,
) -> None:
    compiler = next(
        (
            compiler_path
            for name in ("c++", "g++", "clang++")
            if (compiler_path := shutil.which(name)) is not None
        ),
        None,
    )
    if compiler is None:
        if os.environ.get("CI"):
            pytest.fail("CI must provide a host C++ compiler for the firmware safety test")
        pytest.skip("no host C++ compiler is installed")

    binary_path = tmp_path / (
        "host_safety_test.exe" if Path(compiler).suffix.lower() == ".exe" else "host_safety_test"
    )
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-pedantic",
            str(HOST_TEST),
            "-o",
            str(binary_path),
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [str(binary_path)],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
