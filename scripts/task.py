"""Run project quality and packaging tasks with the active Python interpreter."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence

TASKS: dict[str, tuple[tuple[str, ...], ...]] = {
    "format": (("-m", "ruff", "format", "."),),
    "lint": (
        ("-m", "ruff", "format", "--check", "."),
        ("-m", "ruff", "check", "."),
    ),
    "typecheck": (("-m", "mypy"),),
    "test": (("-m", "pytest"),),
    "audit": (("-m", "pip_audit"),),
    "build": (("-m", "build"),),
}
TASKS["quality"] = (
    *TASKS["lint"],
    *TASKS["typecheck"],
    *TASKS["test"],
    *TASKS["audit"],
    *TASKS["build"],
)


def run(task: str, extra_arguments: Sequence[str]) -> int:
    """Execute each command in a named task and stop at the first failure."""
    commands = TASKS[task]
    for command in commands:
        completed = subprocess.run(
            [sys.executable, *command, *extra_arguments],
            check=False,
        )
        if completed.returncode != 0:
            return completed.returncode
    return 0


def parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the task name and arguments forwarded to its command."""
    parser = argparse.ArgumentParser(
        description="Run Greenhouse Steward development tasks.",
    )
    parser.add_argument("task", choices=sorted(TASKS))
    parser.add_argument(
        "task_arguments",
        nargs=argparse.REMAINDER,
        help="arguments appended to each command in the selected task",
    )
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the selected project task."""
    parsed = parse_args(arguments)
    return run(parsed.task, parsed.task_arguments)


if __name__ == "__main__":
    raise SystemExit(main())
