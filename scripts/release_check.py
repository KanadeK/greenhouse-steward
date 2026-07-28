"""Refuse a release when local provenance or artifacts are incomplete."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["GIT_CONFIG_COUNT"] = "1"
    environment["GIT_CONFIG_KEY_0"] = "safe.directory"
    environment["GIT_CONFIG_VALUE_0"] = str(ROOT)
    return environment


def _command(*arguments: str) -> str:
    return subprocess.check_output(
        arguments,
        cwd=ROOT,
        env=_git_environment(),
        text=True,
    ).strip()


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
            ":!scripts/release_check.py",
            ":!src/greenhouse_steward/web/static/vendor/**",
        ],
        cwd=ROOT,
        check=False,
        env=_git_environment(),
    )
    if markers.returncode == 0:
        return 1
    if markers.returncode != 1:
        return markers.returncode
    return subprocess.run([sys.executable, "scripts/verify.py"], cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
