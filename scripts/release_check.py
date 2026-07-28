"""Refuse a release when local provenance or artifacts are incomplete."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _command(*arguments: str) -> str:
    return subprocess.check_output(arguments, cwd=ROOT, text=True).strip()


def main() -> int:
    required = (ROOT / "dist-release" / "SHA256SUMS.txt", ROOT / "CHANGELOG.md")
    if any(not path.exists() for path in required):
        print("release artifacts or changelog are missing", file=sys.stderr)
        return 1
    if "v0.1.0" not in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"):
        print("CHANGELOG.md lacks v0.1.0", file=sys.stderr)
        return 1
    if _command("git", "status", "--porcelain"):
        print("working tree is not clean", file=sys.stderr)
        return 1
    markers = subprocess.run(
        [
            "git",
            "grep",
            "-nE",
            "TODO|FIXME|NotImplemented|placeholder|coming soon|lorem ipsum",
            "--",
            ":!docs/ROADMAP.md",
        ],
        cwd=ROOT,
        check=False,
    )
    if markers.returncode == 0:
        return 1
    if markers.returncode != 1:
        return markers.returncode
    return subprocess.run([sys.executable, "scripts/verify.py"], cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
