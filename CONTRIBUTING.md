# Contributing to Greenhouse Steward

Thank you for helping build a trustworthy, local-first greenhouse tool.
Contributions are evaluated for correctness, explainability, privacy, and
operational safety—not only for whether they work on one device.

## Before opening an issue

Search existing issues and confirm that the report applies to the current
source. For defects, include:

- operating system and Python version;
- installed Greenhouse Steward version or commit;
- the smallest reproducible input, with credentials and private sensor data
  removed;
- expected and observed behavior;
- complete error output or logs after redaction; and
- whether any physical equipment was connected.

Use a GitHub Security Advisory instead of a public issue when disclosure could
put deployments, credentials, or people at risk. See [`SECURITY.md`](SECURITY.md).

## Development setup

Greenhouse Steward targets Python 3.12.

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Create a focused branch from the current default branch. Keep unrelated
formatting or dependency changes out of the contribution.

## Engineering checks

Run the checks relevant to the change during development. Before requesting
review, run the complete quality task:

```bash
python scripts/task.py quality
```

Equivalent entry points are available through `make quality` and
`.\scripts\task.ps1 quality`. The quality task performs formatting verification,
linting, strict type checking, tests with branch coverage, a dependency audit,
and a package build. It stops at the first failure and preserves that tool's
exit status.

Do not weaken a check simply to make a change pass. If a rule is inappropriate,
explain the project-wide rationale in the pull request.

## Design expectations

- Keep hardware and transport concerns behind adapters.
- Normalize timestamps to UTC while retaining enough source context to explain
  ingestion problems.
- Represent units explicitly; never infer a unit from a bare number when the
  source contract is ambiguous.
- Treat stale, missing, and implausible readings as first-class states.
- Make recommendations deterministic and traceable to input readings and named
  rules.
- Keep advice separate from actuation. Any proposal to add physical control
  requires a dedicated threat and failure analysis.
- Avoid writing secrets, raw authorization headers, or full broker URLs to
  logs.
- Add tests for normal operation, boundaries, invalid data, and failure paths.

## Documentation and changelog

Update user-facing documentation in both languages when behavior or setup
changes. Record a concise entry under `Unreleased` in `CHANGELOG.md` for
observable changes. Architecture or privacy changes also require updates to the
corresponding documents under `docs/`.

## Commits and pull requests

Use clear, imperative commit subjects and keep commits reviewable. A pull
request should:

- explain the problem and the chosen design;
- identify privacy, safety, migration, and compatibility effects;
- list the exact checks run and their outcomes;
- include screenshots only when they clarify a user-interface change and do
  not expose private greenhouse data; and
- link the relevant issue when one exists.

By contributing, you agree that your contribution is licensed under the MIT
License and that project interactions follow the Code of Conduct.
