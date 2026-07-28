"""Typer command tests around the same application facade used by the web UI."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from greenhouse_steward.application import GreenhouseApplication, MqttIngestResult
from greenhouse_steward.cli import app


def test_serve_refuses_non_loopback_binding() -> None:
    result = CliRunner().invoke(app, ["serve", "--host", "0.0.0.0"])

    assert result.exit_code == 2
    assert "--host must be a loopback address" in result.output


def test_analyze_export_and_relay_commands_share_persistence(
    monkeypatch: object,
    tmp_path: Path,
    facade: GreenhouseApplication,
    dry_csv: bytes,
) -> None:
    """CLI analysis feeds subsequent export and simulator commands."""

    from greenhouse_steward import cli

    monkeypatch.setattr(cli, "_application", lambda _database: facade)
    csv_path = tmp_path / "readings.csv"
    csv_path.write_bytes(dry_csv)
    runner = CliRunner()

    analyzed = runner.invoke(
        app,
        [
            "analyze",
            "--csv",
            str(csv_path),
            "--device-id",
            "cli-01",
            "--profile",
            "tomato",
            "--mode",
            "live",
        ],
    )
    assert analyzed.exit_code == 0, analyzed.output
    assert json.loads(analyzed.output)["device_id"] == "cli-01"

    exported = runner.invoke(
        app,
        ["export", "cli-01", "--format", "csv"],
    )
    assert exported.exit_code == 0, exported.output
    assert exported.output.startswith(
        "timestamp,temperature_c,humidity_pct,soil_moisture_pct,light_lux"
    )

    relay = runner.invoke(
        app,
        ["relay", "simulate", "cli-01", "--seconds", "100"],
    )
    assert relay.exit_code == 0, relay.output
    relay_payload = json.loads(relay.output)
    assert relay_payload["applied_seconds"] == 30
    assert relay_payload["capped"] is True


def test_mqtt_validate_and_ingest_outputs_are_safe(
    monkeypatch: object,
    tmp_path: Path,
    facade: GreenhouseApplication,
) -> None:
    """MQTT commands report validation and bounded counts without a password."""

    from greenhouse_steward import cli

    secret = "do-not-print-this"
    config = tmp_path / "mqtt.json"
    config.write_text(
        json.dumps(
            {
                "host": "localhost",
                "username": "grower",
                "password": secret,
                "tls": {
                    "enabled": False,
                    "allow_plaintext_localhost": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "_application", lambda _database: facade)
    runner = CliRunner()

    validated = runner.invoke(app, ["mqtt", "validate", "--config", str(config)])
    assert validated.exit_code == 0, validated.output
    assert json.loads(validated.output)["has_password"] is True
    assert secret not in validated.output

    sensitive_key = "private-config-label"
    config.write_text(
        f'{{"{sensitive_key}": 1, "{sensitive_key}": 2}}',
        encoding="utf-8",
    )
    duplicate = runner.invoke(app, ["mqtt", "validate", "--config", str(config)])
    assert duplicate.exit_code == 2
    assert sensitive_key not in duplicate.output

    config.write_text(
        json.dumps(
            {
                "host": "localhost",
                "username": "grower",
                "password": secret,
                "tls": {
                    "enabled": False,
                    "allow_plaintext_localhost": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        facade,
        "ingest_mqtt",
        lambda *_args, **_kwargs: MqttIngestResult(
            accepted=4,
            rejected=1,
            interrupted=False,
            last_error="one invalid payload",
        ),
    )
    ingested = runner.invoke(
        app,
        [
            "mqtt",
            "ingest",
            "--config",
            str(config),
            "--duration",
            "2",
            "--max-messages",
            "4",
        ],
    )
    assert ingested.exit_code == 0, ingested.output
    assert json.loads(ingested.output)["accepted"] == 4
    assert secret not in ingested.output
