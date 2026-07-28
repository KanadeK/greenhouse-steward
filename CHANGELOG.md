# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Changes under active development belong here until their behavior, tests, and
documentation are ready for a tagged release.

## [0.1.0] - 2026-07-23

### Added

- Local CSV and MQTT v1 ingestion with strict validation, deterministic bundled
  tomato and herb seven-day samples, and SQLite persistence.
- Explainable crop-profile rules, anomaly/stale-data safety states, daily and
  weekly trends, and an explicitly simulated, duration-capped relay.
- FastAPI dashboard/API plus CLI paths for analysis, export, MQTT validation,
  and safe relay simulation; ESP32 synthetic firmware remains hardware-off by
  default.
- Integration and user-entry end-to-end coverage alongside Ruff, mypy, pytest,
  coverage, package build, and dependency-audit task wiring.

### Safety boundary

- Hardware actuation is never enabled by this release. Relay behaviour is an
  in-memory simulation with a profile safety cap; operators remain responsible
  for physical greenhouse decisions.

[Unreleased]: https://github.com/KanadeK/greenhouse-steward/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/KanadeK/greenhouse-steward/releases/tag/v0.1.0
