# Greenhouse Steward

[简体中文](README.zh-CN.md)

Greenhouse Steward is a local-first, open-source foundation for collecting
greenhouse observations and turning them into understandable, operator-reviewed
guidance. The project is designed for small growers, educators, and tinkerers
who want ownership of their data and a clear explanation behind every
recommendation.

## Project status

Version `0.1.0` establishes the Python package, dependency policy, engineering
checks, architecture boundaries, and community documentation. The current
source package exposes version metadata only. It does not ingest measurements,
serve a dashboard, generate horticultural advice, or control equipment.

Do not use this baseline to operate heating, ventilation, irrigation, lighting,
or other physical systems. Environmental decisions remain the responsibility
of a qualified human operator.

## Intended product contract

Implementation work is governed by these principles:

- **Local first:** readings, configuration, and derived guidance stay on the
  operator's machine unless the operator deliberately enables an integration.
- **Observable inputs:** every accepted reading carries a source, timestamp,
  unit, and validation result.
- **Explainable guidance:** recommendations cite the readings and rules that
  produced them; opaque scores are not sufficient.
- **Human authority:** the application presents information and guidance. It
  does not silently actuate greenhouse equipment.
- **Graceful degradation:** missing, stale, or implausible measurements are
  shown as data-quality problems rather than converted into confident advice.
- **Portable data:** operators can inspect and export their own measurements
  using documented formats.

The intended application boundary includes MQTT and explicit manual or file
imports, normalized measurements, local persistence, rule-based analysis, a
FastAPI interface, and a browser dashboard. Each capability must earn its own
tests and documentation before it is described as available.

## Requirements

- Python 3.12
- A virtual environment is strongly recommended
- A local MQTT broker is optional and relevant only after an MQTT adapter is
  implemented

All direct runtime and development dependencies are exactly pinned in
[`pyproject.toml`](pyproject.toml). Dependency updates should be reviewed as
deliberate changes rather than arriving implicitly during installation.

## Development setup

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Activate the virtual environment using the command appropriate for your shell,
then run an individual engineering task:

```bash
python scripts/task.py lint
python scripts/task.py typecheck
python scripts/task.py test
python scripts/task.py audit
python scripts/task.py build
```

PowerShell users can invoke the same tasks with:

```powershell
.\scripts\task.ps1 lint
```

On systems with `make`, the equivalent targets are `make lint`, `make
typecheck`, `make test`, `make audit`, `make build`, and `make quality`.

These commands are release gates, not claims about the state of an unverified
checkout. A task returning a non-zero status must be investigated before a
release.

## Repository layout

```text
.
├── src/greenhouse_steward/  Python package
├── scripts/                 Cross-platform engineering task entry points
├── docs/                    Architecture, security, and release policy
├── .github/                 Contribution and dependency-management metadata
└── pyproject.toml           Package and tool configuration
```

## Safety and privacy

Greenhouse measurements can reveal occupancy patterns, location, crop choices,
and operating schedules. Review
[`docs/PRIVACY_AND_SECURITY.md`](docs/PRIVACY_AND_SECURITY.md) before connecting
real sensors. Security reports should follow [`SECURITY.md`](SECURITY.md).

## Contributing

Issue reports, design discussions, documentation improvements, and carefully
tested code are welcome. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) and the
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) before participating.

## License

Greenhouse Steward is available under the [MIT License](LICENSE).
