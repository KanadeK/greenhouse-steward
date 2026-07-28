"""Run the required local quality gate without weakening failures."""

from __future__ import annotations

import subprocess
import sys
from os import environ, pathsep
from pathlib import Path


def main() -> int:
    environment = environ.copy()
    source_path = str(Path("src").resolve())
    environment["PYTHONPATH"] = pathsep.join(
        filter(None, (source_path, environment.get("PYTHONPATH")))
    )
    commands = (
        ("-m", "ruff", "format", "--check", "."),
        ("-m", "ruff", "check", "."),
        ("-m", "mypy", "src"),
        ("-m", "pytest", "-q", "--basetemp=.pytest-tmp-verify"),
        ("-m", "build"),
    )
    for command in commands:
        completed = subprocess.run([sys.executable, *command], check=False, env=environment)
        if completed.returncode:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
