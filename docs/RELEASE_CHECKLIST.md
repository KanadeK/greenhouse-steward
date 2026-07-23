# Release Checklist

This checklist is a release gate. Check an item only when evidence exists for
the exact commit and artifact being published.

## 1. Scope and version

- [ ] The release scope is described in `CHANGELOG.md`.
- [ ] User-visible behavior is documented in English and Simplified Chinese.
- [ ] The version in `src/greenhouse_steward/__init__.py` matches
      `pyproject.toml`, the changelog heading, and the intended tag.
- [ ] Removed or deferred work is not described as available.
- [ ] Safety limitations and unsupported deployment modes are explicit.
- [ ] Migration and rollback instructions exist when persisted data or
      configuration changes.

## 2. Source review

- [ ] The release commit is reviewed and contains only intended files.
- [ ] Author and committer identities are correct.
- [ ] Commit messages contain no unintended co-author attribution.
- [ ] Generated files, credentials, local configuration, logs, databases, and
      private measurements are absent.
- [ ] The license and third-party dependency licenses are compatible with the
      distribution.

## 3. Engineering gates

Run from a clean Python 3.12 virtual environment:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python scripts/task.py quality
```

- [ ] Ruff formatting verification succeeds.
- [ ] Ruff linting succeeds.
- [ ] Strict mypy checking succeeds.
- [ ] Pytest succeeds with the configured branch-coverage threshold.
- [ ] The dependency audit reports no unaccepted vulnerabilities.
- [ ] Source and wheel builds succeed.
- [ ] Tests cover error paths for stale, malformed, missing, duplicate, and
      out-of-order data when those capabilities are in release scope.
- [ ] The runtime smoke test uses the built artifact rather than only the source
      checkout when a runtime exists.

Record the Python version, operating system, commands, exit status, and artifact
hashes in the release evidence.

## 4. Privacy and security

- [ ] Defaults keep data local and bind services to loopback.
- [ ] Outbound traffic, if any, is documented and explicitly enabled.
- [ ] Secrets are absent from logs, errors, exports, examples, and artifacts.
- [ ] MQTT and HTTP input limits are tested when those interfaces are in scope.
- [ ] Template and chart output safely encode operator-controlled content.
- [ ] Export, retention, and deletion behavior match the privacy documentation.
- [ ] The threat model reflects every new process, interface, data store, and
      integration.
- [ ] A security-reporting path is available on the public repository.

## 5. Documentation and usability

- [ ] Installation commands work in a clean supported environment.
- [ ] Configuration fields, types, defaults, and precedence are documented.
- [ ] Examples use non-working credentials and synthetic measurements.
- [ ] Error messages help an operator recover without exposing sensitive data.
- [ ] The interface displays observation time, freshness, unit, quality, and
      advisory evidence when those features are in scope.
- [ ] Accessibility and keyboard operation are checked for user-interface
      changes.

## 6. Artifact verification

- [ ] `dist/` was created from the reviewed commit.
- [ ] Package contents contain only files intended for distribution.
- [ ] Wheel metadata has the correct name, version, Python requirement,
      dependencies, license, and project links.
- [ ] The source archive can build without repository-only state.
- [ ] SHA-256 hashes are recorded for every published artifact.
- [ ] Installing the wheel into a clean environment imports
      `greenhouse_steward` and reports the expected version.

## 7. Publication

- [ ] The repository is public with the intended default branch and description.
- [ ] Branch protection and private vulnerability reporting are enabled where
      available.
- [ ] The signed or annotated version tag points to the reviewed commit.
- [ ] Release notes match the changelog and preserve safety limitations.
- [ ] Published artifact hashes match the locally verified hashes.
- [ ] The release page, source archives, and package links are checked from a
      logged-out session.

## 8. After publication

- [ ] Installation and the smallest documented use path are repeated against
      the published artifact.
- [ ] Known limitations are visible in the release notes.
- [ ] Newly reported regressions are triaged without rewriting published
      artifacts.
- [ ] A failed gate results in a corrected version rather than moving an
      existing tag.
