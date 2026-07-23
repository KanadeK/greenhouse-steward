# Security Policy

Greenhouse Steward handles data that may describe a private physical space and
may eventually connect to networked sensors. Security reports are treated as
product-safety reports.

## Supported versions

Before the first stable release, security fixes are applied to the latest
published `0.1.x` version and the default development branch. Older development
snapshots are not maintained.

| Version | Security fixes |
| --- | --- |
| Latest `0.1.x` | Supported |
| Older snapshots | Not supported |

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability.

Use GitHub's private vulnerability-reporting or Security Advisory feature for
the `KanadeK/greenhouse-steward` repository. Include:

- the affected version or commit;
- the affected component and deployment assumptions;
- reproducible steps or a minimal proof of concept;
- the likely impact on confidentiality, integrity, availability, or physical
  operations;
- any temporary mitigation you have verified; and
- how you would like to be credited.

Remove real credentials and private sensor readings from the report. If a
sample secret is necessary, create a disposable one and label it clearly.

The maintainer will acknowledge receipt, investigate privately, coordinate a
fix and disclosure plan when the report is valid, and credit the reporter
unless anonymity is requested. Timing depends on severity, reproducibility, and
the safety of publishing details.

## Security scope

Examples of in-scope reports include:

- authentication or authorization bypass;
- exposure of credentials, measurements, schedules, or location data;
- unsafe defaults that expose a local service beyond the operator's machine;
- injection through MQTT topics, payloads, imported files, templates, or
  rendered charts;
- dependency or packaging behavior that executes untrusted code; and
- advice integrity failures caused by tampered or misattributed readings.

General gardening disagreements, unsupported hardware requests, and
availability problems in third-party services are not vulnerabilities unless
they cross a documented security boundary.

## Deployment responsibility

The `0.1.0` foundation does not operate greenhouse equipment. Future versions
must be evaluated in the context of their deployment, broker configuration,
network exposure, and connected devices. Never reuse production credentials in
development or issue reports.
