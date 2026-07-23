## Problem

Explain the operator or maintainer problem this change addresses.

## Change

Describe the chosen behavior and important design decisions.

## Evidence

List the exact commands run and their results. Include sanitized screenshots or
sample data only when they materially help review.

## Privacy, security, and safety

Describe effects on stored data, outbound communication, credentials, network
exposure, recommendations, and physical operations. State explicitly when
there is no effect.

## Compatibility and recovery

Describe configuration or data migrations, compatibility constraints, and how
an operator can recover or roll back.

## Checklist

- [ ] The change is focused and contains no unrelated edits.
- [ ] Tests cover normal, boundary, and failure behavior.
- [ ] Ruff formatting and linting succeed.
- [ ] Strict mypy checking succeeds.
- [ ] Pytest and the configured coverage gate succeed.
- [ ] Dependency audit and package build succeed when dependencies changed.
- [ ] English and Simplified Chinese user documentation are consistent.
- [ ] `CHANGELOG.md` records observable behavior under `Unreleased`.
- [ ] Logs, fixtures, screenshots, and examples contain no secrets or private
      greenhouse data.
- [ ] Safety limitations remain accurate.
