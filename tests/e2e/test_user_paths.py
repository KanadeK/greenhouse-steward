"""User-facing end-to-end flows over the real local adapters."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from greenhouse_steward.application import create_default_application
from greenhouse_steward.cli import app
from greenhouse_steward.web import create_web_app


def test_cli_sample_to_json_and_csv_export(tmp_path: Path) -> None:
    """A user can persist a bundled sample and export two real representations."""

    runner = CliRunner()
    database = tmp_path / "steward.sqlite3"
    analyzed = runner.invoke(app, ["analyze", "--sample", "tomato-7d", "--db", str(database)])
    assert analyzed.exit_code == 0, analyzed.output
    assert json.loads(analyzed.output)["storage"]["inserted"] == 672

    exported = runner.invoke(
        app,
        ["export", "sample-tomato", "--db", str(database), "--format", "json"],
    )
    assert exported.exit_code == 0, exported.output
    assert json.loads(exported.output)["history_snapshot_count"] == 672

    csv_export = runner.invoke(
        app,
        ["export", "sample-tomato", "--db", str(database), "--format", "csv"],
    )
    assert csv_export.exit_code == 0, csv_export.output
    assert len(csv_export.output.splitlines()) == 673


def test_web_sample_dashboard_and_downloads(tmp_path: Path) -> None:
    """The browser path persists data, renders evidence, and returns actual exports."""

    facade = create_default_application(tmp_path / "web.sqlite3")
    client = TestClient(create_web_app(facade))
    client.get("/dashboard")
    submitted = client.post(
        "/analyses/sample",
        data={
            "csrf_token": client.cookies["greenhouse_csrf"],
            "sample_slug": "herb-7d",
            "profile_slug": "herb",
        },
        follow_redirects=False,
    )
    assert submitted.status_code == 303
    dashboard = client.get(submitted.headers["location"])
    assert "Rule evidence" in dashboard.text
    assert client.get("/api/v1/export/sample-herb.csv").text.count("\n") == 673
    report = client.get("/api/v1/export/sample-herb.json", params={"profile_slug": "herb"})
    assert report.status_code == 200
    assert report.json()["source"]["kind"] == "persisted"


def test_invalid_mqtt_config_does_not_disclose_password(tmp_path: Path) -> None:
    """A hostile configuration reaches the CLI boundary without leaking its secret."""

    config = tmp_path / "mqtt.json"
    secret = "never-print-this-password"
    config.write_text(
        json.dumps({"host": "broker.invalid", "password": secret, "extra": "invalid"}),
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["mqtt", "validate", "--config", str(config)])
    assert result.exit_code == 2
    assert secret not in result.output
    assert "invalid MQTT configuration" in result.output
