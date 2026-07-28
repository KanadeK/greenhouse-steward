"""Run the required local quality gate without weakening failures."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    commands = (
        ("-m", "ruff", "format", "--check", "."),
        ("-m", "ruff", "check", "."),
        ("-m", "mypy", "src"),
        ("-m", "pytest", "-q", "--basetemp=.pytest-tmp-verify"),
        ("-m", "build"),
    )
    for command in commands:
        completed = subprocess.run([sys.executable, *command], check=False)
        if completed.returncode:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
