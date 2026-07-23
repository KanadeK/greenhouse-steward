# Architecture

## Status and purpose

This document records the design boundaries for Greenhouse Steward. In version
`0.1.0`, the repository contains package metadata and engineering policy; the
runtime components described below are an implementation contract, not a claim
that those components exist.

The system is intended to help a human understand greenhouse conditions. It is
not an autonomous controller. Keeping observation, interpretation, and physical
actuation separate is a core safety property.

## Context

The expected deployment is a single operator-owned computer on a trusted local
network. Sensors or a broker provide measurements. Greenhouse Steward validates
and normalizes those measurements, stores local history, evaluates explicit
rules, and presents the result through a local web interface.

Conceptual data flow:

```text
sensor / explicit import
          |
          v
   ingestion adapter
          |
          v
 validation + normalization -----> rejected-reading record
          |
          v
    local repository
          |
          +----------> rule evaluation
          |                  |
          v                  v
 historical query       advisory + evidence
          |                  |
          +---------> application service
                             |
                             v
                     local API / dashboard
```

No path in this design leads from an advisory directly to an actuator.

## Layer boundaries

### Domain

The domain layer owns vocabulary and invariants without depending on FastAPI,
MQTT, templates, storage engines, or operating-system services.

Core concepts are expected to include:

- **Sensor identity:** a stable identifier and human label, independent of an
  MQTT topic or file column.
- **Reading:** sensor identity, observed time, received time, quantity, explicit
  unit, numeric value, source, and quality state.
- **Quality state:** accepted, stale, out of configured range, malformed, or
  missing. A quality state is data, not an exception to hide.
- **Advisory:** severity, concise message, evidence, named rule, evaluation time,
  and an expiry or supersession condition.

Domain objects should be immutable where practical. Decimal or carefully
bounded numeric behavior should be selected according to the precision of the
source; display rounding must not alter stored evidence.

### Ingestion adapters

Adapters translate external representations into a transport-neutral candidate
reading. An adapter may understand MQTT envelopes, an uploaded file, or a
manual form, but it must not decide horticultural meaning.

Adapter requirements:

- enforce payload size and field-count limits before expensive parsing;
- preserve source timestamps separately from receipt timestamps;
- reject unknown or ambiguous units;
- attach a source identifier without exposing credentials;
- tolerate duplicate delivery through deterministic identity or idempotency
  rules; and
- report parsing failures as structured results suitable for operator review.

MQTT subscriptions must be explicit. Wildcard subscriptions require a
documented reason and tests that prove unrelated topics are ignored.

### Validation and normalization

Normalization converts an accepted source unit into a documented canonical unit
for the quantity. Validation distinguishes malformed input from valid but
suspicious values. Configured horticultural thresholds belong to analysis, not
to syntactic validation.

Every conversion should be deterministic and independently tested at boundary
values. Time is stored in UTC; a presentation time zone is an operator
preference and must not rewrite history.

### Local repository

Persistence is accessed through interfaces defined by the application or domain
boundary. Storage-specific queries and migrations remain inside the storage
adapter.

The repository must support:

- atomic storage of an accepted reading and its source metadata;
- bounded historical queries;
- an explicit retention operation;
- deterministic export;
- migration with rollback or recovery guidance; and
- detection and reporting of an incompatible schema.

The initial persistence implementation should optimize for inspectability and
backup simplicity rather than distributed scale.

### Analysis

Analysis evaluates named, versioned rules against validated readings and
operator configuration. A result without evidence is invalid.

A rule result should answer:

1. Which rule and version ran?
2. Which readings and configuration values were used?
3. Were any required readings missing, stale, or suspicious?
4. Why did the rule produce this severity and message?
5. When should the result be evaluated again?

Rules must be deterministic for the same inputs. Horticultural defaults should
be conservative, sourced in documentation, and readily overridden for a
specific crop and deployment. Uncertainty must be visible.

### Application services

Application services coordinate adapters, repositories, and analysis. They own
use-case transactions and map expected failures into structured errors. They do
not embed HTML, SQL, MQTT topic syntax, or horticultural formulas.

Long-running ingestion and request handling need explicit lifecycle ownership.
Startup must fail visibly when required configuration is invalid. Shutdown must
stop accepting work, drain bounded in-flight operations, and close local
resources.

### API and presentation

FastAPI routes and browser views are delivery mechanisms. They validate
transport input, call application services, and render returned models.

The interface should:

- bind to loopback by default;
- use finite pagination and query windows;
- escape operator-controlled labels and imported content;
- display units and observation age beside values;
- distinguish unavailable data from zero;
- show the evidence and rule identity for each advisory; and
- avoid embedding private readings in third-party resources or URLs.

Plotly output must be generated from bounded, validated series. Template
auto-escaping stays enabled.

## Configuration

Configuration has three classes:

1. non-sensitive application preferences;
2. deployment-specific connection settings; and
3. secrets such as broker credentials.

Defaults belong in typed code or a committed example file. Real secrets do not
belong in source control, URLs, command history, exports, or logs. Each setting
needs a documented source, type, default behavior, and validation rule.

Configuration precedence must be deterministic. The effective non-secret
configuration should be inspectable from the local interface or diagnostic
output.

## Dependency direction

Dependencies point inward:

```text
presentation / transport / storage adapters
                    |
                    v
           application services
                    |
                    v
                 domain
```

The domain does not import framework or infrastructure packages. Application
services may depend on domain-owned protocols. Concrete adapters implement
those protocols and are assembled at the process boundary.

## Failure behavior

Expected external failures—broker disconnects, malformed payloads, a locked
database, or an invalid import—must be represented without terminating
unrelated read-only functions. Retries are bounded and use backoff. Persistent
failure becomes visible to the operator.

The interface must never turn missing data into a reassuring state. When the
system cannot establish data freshness or rule completeness, it reports that
uncertainty and withholds confident guidance.

## Testing strategy

Tests are organized by boundary:

- pure domain and rule tests for invariants and edge cases;
- adapter contract tests using controlled messages and files;
- repository tests against a temporary local database;
- application tests with in-memory protocol implementations;
- API tests through an in-process HTTP client; and
- a small end-to-end path that proves ingestion, persistence, analysis, and
  presentation agree on identity, time, units, and quality.

Coverage is a gate, not evidence of correctness by itself. Safety-relevant
branches require explicit assertions even when line coverage is already met.

## Architecture changes

A change that introduces remote data transfer, authentication, physical
actuation, a new persistence engine, or a new process boundary requires an
architecture decision in the pull request. The decision should state context,
alternatives, privacy and safety effects, migration behavior, and test
evidence.
