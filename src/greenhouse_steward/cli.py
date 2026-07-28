"""Typer command line interface backed by the shared application facade."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from greenhouse_steward.application import (
    AnalysisMode,
    ApplicationError,
    GreenhouseApplication,
    create_default_application,
    report_to_dict,
)

app = typer.Typer(
    name="greenhouse-steward",
    help="Local greenhouse monitoring, evidence, trends, and safe simulation.",
    no_args_is_help=True,
)
mqtt_app = typer.Typer(help="Validate or ingest MQTT sensor configuration.")
relay_app = typer.Typer(help="Run explicitly simulated relay transitions.")
app.add_typer(mqtt_app, name="mqtt")
app.add_typer(relay_app, name="relay")


def _application(database: Path) -> GreenhouseApplication:
    """Build the production facade for one command invocation."""

    return create_default_application(database)


def _abort(error: Exception, *, code: int = 2) -> NoReturn:
    """Print one safe diagnostic and stop without a traceback."""

    typer.echo(f"Error: {error}", err=True)
    raise typer.Exit(code=code)


def _read_json_object(path: Path, *, label: str) -> dict[str, object]:
    """Read a strict JSON object for a user-facing command."""

    raw = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
    )
    if not isinstance(raw, dict):
        raise ValueError(f"{label} root must be an object")
    return {str(key): value for key, value in raw.items()}


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    """Reject ambiguous config documents without echoing sensitive key names."""

    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("configuration contains a duplicate JSON key")
        document[key] = value
    return document


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Loopback HTTP bind address.")] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option(min=1, max=65_535, help="HTTP port."),
    ] = 8000,
    database: Annotated[
        Path,
        typer.Option("--db", help="SQLite database path."),
    ] = Path("greenhouse-steward.sqlite3"),
) -> None:
    """Run the local FastAPI dashboard."""

    loopback_hosts = {"127.0.0.1", "localhost", "::1"}
    if host not in loopback_hosts:
        _abort(ValueError("--host must be a loopback address"), code=2)
    import uvicorn

    from greenhouse_steward.web import create_web_app

    web_app = create_web_app(_application(database))
    uvicorn.run(web_app, host=host, port=port, log_level="info")


@app.command()
def analyze(
    csv_path: Annotated[
        Path | None,
        typer.Option(
            "--csv",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Canonical sensor CSV path.",
        ),
    ] = None,
    sample: Annotated[
        str | None,
        typer.Option("--sample", help="Bundled sample slug: tomato-7d or herb-7d."),
    ] = None,
    profile: Annotated[str, typer.Option(help="Crop profile slug.")] = "tomato",
    device_id: Annotated[
        str,
        typer.Option(help="Device identifier for CSV data."),
    ] = "cli-upload",
    mode: Annotated[
        AnalysisMode,
        typer.Option(case_sensitive=False, help="historical or live evaluation."),
    ] = AnalysisMode.HISTORICAL,
    database: Annotated[
        Path,
        typer.Option("--db", help="SQLite database path."),
    ] = Path("greenhouse-steward.sqlite3"),
) -> None:
    """Analyze one real CSV or deterministic bundled sample."""

    if (csv_path is None) == (sample is None):
        _abort(ValueError("provide exactly one of --csv or --sample"))
    facade = _application(database)
    try:
        if sample is not None:
            report = facade.analyze_sample(
                sample_slug=sample,
                profile_slug=profile,
            )
        else:
            if csv_path is None:
                _abort(ValueError("--csv is required"))
            report = facade.analyze_csv(
                csv_path.read_bytes(),
                device_id=device_id,
                profile_slug=profile,
                mode=mode,
                source_name=csv_path.name,
            )
    except (ApplicationError, OSError) as error:
        _abort(error)
    typer.echo(
        json.dumps(
            report_to_dict(report),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


@app.command("profiles")
def profiles_command(
    database: Annotated[
        Path,
        typer.Option("--db", help="SQLite database path."),
    ] = Path("greenhouse-steward.sqlite3"),
) -> None:
    """List validated crop profiles and safety caps."""

    try:
        payload = _application(database).list_profiles()
    except ApplicationError as error:
        _abort(error)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


@app.command("export")
def export_command(
    device_id: Annotated[str, typer.Argument(help="Persisted device identifier.")],
    format_name: Annotated[
        str,
        typer.Option("--format", help="json status report or csv sensor readings."),
    ] = "json",
    profile: Annotated[
        str,
        typer.Option(help="Crop profile slug for JSON."),
    ] = "tomato",
    mode: Annotated[
        AnalysisMode,
        typer.Option(
            case_sensitive=False,
            help="historical or live evaluation for JSON.",
        ),
    ] = AnalysisMode.HISTORICAL,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            dir_okay=False,
            help="Output path; stdout when omitted.",
        ),
    ] = None,
    database: Annotated[
        Path,
        typer.Option("--db", help="SQLite database path."),
    ] = Path("greenhouse-steward.sqlite3"),
) -> None:
    """Export persisted readings or a complete status report."""

    facade = _application(database)
    try:
        if format_name == "json":
            payload = facade.export_json(
                device_id,
                profile_slug=profile,
                mode=mode,
            )
        elif format_name == "csv":
            payload = facade.export_csv(device_id)
        else:
            _abort(ValueError("--format must be json or csv"))
    except ApplicationError as error:
        _abort(error, code=3)
    if output is None:
        typer.echo(payload.decode("utf-8"), nl=False)
        return
    try:
        output.write_bytes(payload)
    except OSError as error:
        _abort(error, code=4)
    typer.echo(f"Wrote {len(payload)} bytes to {output}")


@mqtt_app.command("validate")
def mqtt_validate(
    config: Annotated[
        Path,
        typer.Option(
            "--config",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Strict JSON MQTT configuration.",
        ),
    ],
    database: Annotated[
        Path,
        typer.Option("--db", help="SQLite database path."),
    ] = Path("greenhouse-steward.sqlite3"),
) -> None:
    """Validate MQTT settings without opening a network connection."""

    try:
        document = _read_json_object(config, label="MQTT config")
        payload = _application(database).validate_mqtt_config(document)
    except (ApplicationError, OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        _abort(error)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


@mqtt_app.command("ingest")
def mqtt_ingest(
    config: Annotated[
        Path,
        typer.Option(
            "--config",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Strict JSON MQTT configuration.",
        ),
    ],
    profile: Annotated[
        str,
        typer.Option(help="Crop profile applied to received snapshots."),
    ] = "tomato",
    duration: Annotated[
        float,
        typer.Option(
            min=0.001,
            max=86_400,
            help="Maximum network-loop duration in seconds.",
        ),
    ] = 60.0,
    max_messages: Annotated[
        int,
        typer.Option(
            "--max-messages",
            min=1,
            max=1_000_000,
            help="Stop after this many accepted snapshots.",
        ),
    ] = 100,
    database: Annotated[
        Path,
        typer.Option("--db", help="SQLite database path."),
    ] = Path("greenhouse-steward.sqlite3"),
) -> None:
    """Connect with Paho and persist a strictly bounded MQTT session."""

    try:
        document = _read_json_object(config, label="MQTT config")
        result = _application(database).ingest_mqtt(
            document,
            profile_slug=profile,
            duration_seconds=duration,
            max_messages=max_messages,
        )
    except (ApplicationError, OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        _abort(error)
    typer.echo(
        json.dumps(
            {
                "accepted": result.accepted,
                "rejected": result.rejected,
                "interrupted": result.interrupted,
                "last_error": result.last_error,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    if result.interrupted:
        raise typer.Exit(code=130)


@relay_app.command("simulate")
def relay_simulate(
    device_id: Annotated[str, typer.Argument(help="Persisted device identifier.")],
    profile: Annotated[str, typer.Option(help="Crop profile slug.")] = "tomato",
    mode: Annotated[
        AnalysisMode,
        typer.Option(case_sensitive=False, help="Must be live for relay simulation."),
    ] = AnalysisMode.LIVE,
    seconds: Annotated[
        int,
        typer.Option(
            "--seconds",
            min=1,
            max=86_400,
            help="Requested simulated on-time.",
        ),
    ] = 10,
    database: Annotated[
        Path,
        typer.Option("--db", help="SQLite database path."),
    ] = Path("greenhouse-steward.sqlite3"),
) -> None:
    """Apply safety rules to the in-memory relay simulator only."""

    try:
        snapshot = _application(database).simulate_relay(
            device_id,
            profile_slug=profile,
            mode=mode,
            requested_seconds=seconds,
        )
    except ApplicationError as error:
        _abort(error, code=3)
    typer.echo(
        json.dumps(
            snapshot.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    app()
