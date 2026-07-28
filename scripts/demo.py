"""Generate a deterministic, inspectable sample report."""

from __future__ import annotations

import json
from pathlib import Path

from greenhouse_steward.application import create_default_application, report_to_dict


def main() -> int:
    output_dir = Path("artifacts")
    output_dir.mkdir(exist_ok=True)
    facade = create_default_application(output_dir / "demo.sqlite3")
    report = facade.analyze_sample(sample_slug="tomato-7d", profile_slug="tomato")
    (output_dir / "tomato-7d-report.json").write_text(
        json.dumps(report_to_dict(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(output_dir / "tomato-7d-report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
