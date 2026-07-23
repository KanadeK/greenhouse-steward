# Privacy and Security

## Current baseline

Version `0.1.0` contains no running service, sensor adapter, database, analytics,
or telemetry. It neither collects nor transmits greenhouse data. This document
defines the constraints that runtime capabilities must satisfy as they are
implemented.

## Data categories

A real deployment may process:

- sensor identifiers and human-assigned locations;
- environmental measurements and timestamps;
- crop, threshold, and rule configuration;
- broker addresses and account identifiers;
- application diagnostics; and
- derived advisories and their supporting evidence.

Even without a person's name, this data may reveal presence, routines,
property characteristics, crop choices, or commercial activity. Treat it as
private operational data.

Credentials, API tokens, private keys, and session material are secrets. They
must never be treated as ordinary configuration or export data.

## Privacy defaults

Runtime features must adopt these defaults:

- persist data only on the operator-controlled machine;
- make outbound network communication opt-in and purpose-specific;
- avoid analytics, tracking pixels, remote fonts, and remote script resources;
- bind local HTTP services to loopback;
- collect only fields required for a documented use case;
- use bounded retention that the operator can inspect and change;
- provide a documented export and deletion path; and
- show when an integration will disclose data before enabling it.

An integration may not repurpose sensor readings for training, advertising, or
unrelated analytics.

## Secrets

Secrets belong in an operating-system credential facility or a local,
access-controlled secret source. Environment variables can be useful in
controlled deployments but may leak through process inspection, crash reports,
or shell history.

The application must:

- redact secrets from logs and structured errors;
- never include credentials in broker or HTTP URLs shown to the operator;
- prevent secret fields from entering exports;
- fail closed when a required secret is absent or malformed; and
- document rotation and revocation for every supported credential type.

Example configuration files contain non-working example values only and are
safe to commit. The repository ignores common local secret-file patterns as a
secondary defense, not as permission to store secrets in the project tree.

## Network boundaries

### Local web interface

The default listener is loopback-only. Listening on another interface is an
explicit deployment decision that requires authentication, transport
encryption, trusted proxy configuration when applicable, and a review of
cross-site request protections.

Routes that change configuration or import data require size limits,
content-type validation, and protection against cross-origin submission.
Operator-controlled strings are escaped on output. Error responses do not
include stack traces or secrets in normal operation.

### MQTT

MQTT connections should use authenticated TLS whenever traffic leaves a single
trusted host. Certificate verification is enabled by default. Disabling
verification is not an acceptable production workaround.

Topic names are configuration, not authorization. The broker account should
have the smallest publish and subscribe permissions required. Payloads remain
untrusted even when they arrive from an authenticated broker.

Implementations must bound payload size, parsing depth, retained-message
handling, reconnect rates, and queued work. Duplicate and out-of-order
messages must not corrupt history or manufacture confidence.

## Input and rendering safety

All imported files, messages, labels, notes, and configuration values are
untrusted input.

- Validate shape, type, range, encoding, and length at the system boundary.
- Reject ambiguous units and timestamps.
- Keep template auto-escaping enabled.
- Do not render imported HTML as trusted markup.
- Serialize chart data rather than constructing executable JavaScript strings.
- Parameterize persistence queries.
- Prevent file imports and exports from escaping an operator-selected
  directory.
- Defend spreadsheet exports against formula injection when a cell begins with
  a formula-significant character.

## Logs and diagnostics

Logs should contain event type, component, severity, time, and a safe correlation
identifier. Raw payloads are excluded by default. Diagnostic modes must state
what extra data they record, apply a finite duration, and keep the same secret
redaction rules.

Operators need a way to locate, rotate, and delete logs. A support bundle
requires an explicit preview of included files and fields.

## Storage, retention, and backup

Local storage should use operating-system permissions appropriate to one user.
Encryption at rest depends on deployment needs and should use established
platform or database facilities rather than project-specific cryptography.

Retention is measured from the observation timestamp and must define how
invalid, rejected, and derived records are treated. Deletion should cover
primary records, derived advisories, cached views, and documented backups where
technically possible.

Backups can contain the same private information as the live database.
Documentation must describe consistency, encryption expectations, restore
verification, and schema compatibility.

## Threat model

The minimum review assumes:

- an attacker can publish crafted payloads to a misconfigured broker;
- a malicious or compromised sensor can lie, replay, or flood;
- an imported file can contain adversarial content;
- another device on the local network may be untrusted;
- a browser may have unrelated hostile pages open; and
- logs, exports, or backups may be shared for support.

The project cannot protect a host already fully controlled by an attacker.
Compromise of the host is still considered when minimizing retained secrets and
outbound communication.

## Human and physical safety

Advice is informational and must identify missing evidence and uncertainty.
Greenhouse Steward does not bypass equipment interlocks, manufacturer limits,
or professional judgment. Connecting a future advisory to physical actuation
would create a materially different product boundary and requires dedicated
hazard analysis, authentication, authorization, fail-safe states, and hardware
testing.

## Dependency and release controls

Direct dependencies are exactly pinned. Automated update proposals are reviewed
for upstream provenance, changelog impact, license, vulnerabilities, and
behavioral changes. A clean dependency audit reduces known risk but does not
prove that a release is secure.

Release artifacts must be built from the intended commit, contain no local
configuration or data, and be accompanied by reproducible checksums. Follow
[`RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md).

## Reporting

Report suspected vulnerabilities privately according to
[`SECURITY.md`](../SECURITY.md). Do not attach real credentials or private
greenhouse data.
