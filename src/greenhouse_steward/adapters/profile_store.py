"""Strict JSON loading for bundled crop, safety, and anomaly profiles."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from greenhouse_steward.domain import AnomalyPolicy, CropProfile, SafetyPolicy
from greenhouse_steward.ports import ProfileBundle

_PROFILE_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_HARD_RELAY_LIMIT_SECONDS = 30


class ProfileStoreError(ValueError):
    """Base class for profile loading failures."""


class ProfileNotFoundError(ProfileStoreError):
    """A requested profile does not exist."""


class ProfileSchemaError(ProfileStoreError):
    """A profile document is malformed or unsafe."""


class DuplicateJsonKeyError(ProfileSchemaError):
    """A JSON object contains an ambiguous repeated key."""


class _ProfileDocument(BaseModel):
    """On-disk profile envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    profile: CropProfile
    safety: SafetyPolicy
    anomaly: AnomalyPolicy

    @model_validator(mode="before")
    @classmethod
    def reject_coerced_scalar_types(cls, value: Any) -> Any:
        """Fail closed instead of coercing booleans or numeric strings."""

        if not isinstance(value, dict):
            return value
        if type(value.get("schema_version")) is not int:
            raise ValueError("schema_version must be an integer")
        profile = value.get("profile")
        safety = value.get("safety")
        anomaly = value.get("anomaly")
        if isinstance(profile, dict):
            targets = profile.get("targets")
            if isinstance(targets, dict):
                for target in targets.values():
                    if isinstance(target, dict):
                        _require_numbers(target, ("low", "high"))
            watering = profile.get("watering")
            if isinstance(watering, dict):
                _require_numbers(
                    watering,
                    ("trigger_below_pct", "stop_at_pct"),
                )
                _require_integers(watering, ("suggested_duration_seconds",))
        if isinstance(safety, dict):
            _require_integers(
                safety,
                (
                    "offline_after_seconds",
                    "future_tolerance_seconds",
                    "relay_max_on_seconds",
                ),
            )
            hard_ranges = safety.get("hard_ranges")
            if isinstance(hard_ranges, dict):
                for hard_range in hard_ranges.values():
                    if isinstance(hard_range, dict):
                        _require_numbers(hard_range, ("low", "high"))
        if isinstance(anomaly, dict) and isinstance(anomaly.get("metrics"), dict):
            for limits in anomaly["metrics"].values():
                if isinstance(limits, dict):
                    _require_integers(limits, ("min_samples", "window_size"))
                    _require_numbers(
                        limits,
                        (
                            "zscore_threshold",
                            "flat_baseline_delta",
                            "max_rate_per_minute",
                        ),
                    )
        return value

    @model_validator(mode="after")
    def validate_relay_limits(self) -> Self:
        """Keep recommendations beneath both software and firmware caps."""

        if self.safety.relay_max_on_seconds > _HARD_RELAY_LIMIT_SECONDS:
            raise ValueError(f"relay_max_on_seconds must not exceed {_HARD_RELAY_LIMIT_SECONDS}")
        if self.profile.watering.suggested_duration_seconds > self.safety.relay_max_on_seconds:
            raise ValueError("watering duration must not exceed the relay safety cap")
        return self


class JsonProfileStore:
    """Load immutable profiles from one traversal-safe directory."""

    def __init__(self, profile_dir: Path | None = None) -> None:
        """Select the bundled profile directory by default."""

        self._profile_dir = (
            profile_dir
            if profile_dir is not None
            else Path(__file__).resolve().parents[1] / "profiles"
        )

    def list_slugs(self) -> tuple[str, ...]:
        """List valid JSON profile stems in deterministic order."""

        if not self._profile_dir.is_dir():
            return ()
        return tuple(
            path.stem
            for path in sorted(self._profile_dir.glob("*.json"))
            if _PROFILE_SLUG_PATTERN.fullmatch(path.stem) is not None
        )

    def load(self, profile_slug: str) -> ProfileBundle:
        """Load one profile by a safe slug."""

        if _PROFILE_SLUG_PATTERN.fullmatch(profile_slug) is None:
            raise ProfileStoreError("profile slug is invalid")
        path = self._profile_dir / f"{profile_slug}.json"
        bundle = self.load_path(path)
        if bundle.profile.slug != profile_slug:
            raise ProfileSchemaError(
                f"profile slug {bundle.profile.slug!r} does not match filename {profile_slug!r}"
            )
        return bundle

    def load_path(self, path: Path) -> ProfileBundle:
        """Load a path only when it resolves beneath the configured directory."""

        try:
            root = self._profile_dir.resolve(strict=True)
            resolved = path.resolve(strict=True)
        except FileNotFoundError as error:
            raise ProfileNotFoundError(f"profile not found: {path.name}") from error
        if not resolved.is_relative_to(root):
            raise ProfileStoreError("profile path escapes the configured directory")
        try:
            text = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ProfileStoreError(f"cannot read profile {resolved.name}") from error
        try:
            raw = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
            document = _ProfileDocument.model_validate(raw)
        except DuplicateJsonKeyError:
            raise
        except json.JSONDecodeError as error:
            raise ProfileSchemaError(f"invalid JSON in {resolved.name}: {error.msg}") from error
        except ValidationError as error:
            raise ProfileSchemaError(f"invalid profile {resolved.name}: {error}") from error
        return ProfileBundle(
            profile=document.profile,
            safety=document.safety,
            anomaly=document.anomaly,
        )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build a JSON object while refusing last-write-wins ambiguity."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKeyError("profile JSON contains a duplicate key")
        result[key] = value
    return result


def _require_numbers(document: dict[str, object], fields: tuple[str, ...]) -> None:
    """Reject bool and string coercion for safety-relevant numeric fields."""

    for field in fields:
        raw = document.get(field)
        if type(raw) not in {int, float}:
            raise ValueError(f"{field} must be a JSON number")


def _require_integers(document: dict[str, object], fields: tuple[str, ...]) -> None:
    """Reject booleans, floats, and strings for safety-relevant integer fields."""

    for field in fields:
        if type(document.get(field)) is not int:
            raise ValueError(f"{field} must be a JSON integer")
