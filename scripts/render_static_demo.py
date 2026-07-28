"""Render a privacy-safe static demo from the deterministic sample report."""

from __future__ import annotations

import html
import json
from pathlib import Path


def main() -> int:
    report = json.loads(Path("artifacts/tomato-7d-report.json").read_text(encoding="utf-8"))
    output = Path("site")
    output.mkdir(exist_ok=True)
    rules = "".join(
        f"<li><strong>{html.escape(str(rule['metric']))}</strong>: "
        f"{html.escape(str(rule['recommendation']))}</li>"
        for rule in report["rules"]
    )
    document = "\n".join(
        (
            "<!doctype html><meta charset=utf-8>",
            "<meta name=viewport content='width=device-width,initial-scale=1'>",
            "<title>Greenhouse Steward demo</title>",
            "<style>body{max-width:48rem;margin:2rem auto;padding:1rem;font:16px system-ui;background:#f4f8f1;color:#183526}",  # noqa: E501
            "article{background:#fff;padding:1.5rem;border:1px solid #bfd1bf;border-radius:.5rem}</style>",  # noqa: E501
            "<main><article><h1>Greenhouse Steward</h1><p>Deterministic local tomato sample: ",
            f"{report['history_snapshot_count']} snapshots, {report['history_reading_count']} readings.</p>",  # noqa: E501
            f"<p>System mode: <strong>{html.escape(str(report['system_mode']))}</strong></p>",
            f"<h2>Rule evidence</h2><ul>{rules}</ul>",
            "<p>This static page contains only bundled synthetic data; the interactive dashboard remains local-only.</p></article></main>",  # noqa: E501
        )
    )
    output.joinpath("index.html").write_text(document, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
