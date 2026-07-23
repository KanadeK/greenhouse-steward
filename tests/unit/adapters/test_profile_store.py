"""JSON profile-store tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from greenhouse_steward.adapters.profile_store import (
    DuplicateJsonKeyError,
    JsonProfileStore,
    ProfileSchemaError,
    ProfileStoreError,
)
from greenhouse_steward.domain import Metric


def test_bundled_profiles_are_complete_and_safely_capped() -> None:
    store = JsonProfileStore()

    assert store.list_slugs() == ("herb", "tomato")
    tomato = store.load("tomato")
    herb = store.load("herb")
    assert set(tomato.profile.targets) == set(Metric)
    assert tomato.safety.relay_max_on_seconds == 30
    assert herb.profile.watering.suggested_duration_seconds <= 30


def test_profile_store_rejects_traversal() -> None:
    with pytest.raises(ProfileStoreError):
        JsonProfileStore().load("../tomato")


def test_profile_store_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    profile = tmp_path / "bad.json"
    sensitive_key = "private-profile-label"
    profile.write_text(
        f'{{"{sensitive_key}": 1, "{sensitive_key}": 1}}',
        encoding="utf-8",
    )

    with pytest.raises(DuplicateJsonKeyError) as duplicate:
        JsonProfileStore(tmp_path).load("bad")
    assert sensitive_key not in str(duplicate.value)


def test_profile_store_rejects_numeric_coercion_and_boolean_hard_ranges(
    tmp_path: Path,
) -> None:
    bundled = Path(__file__).parents[3] / "src" / "greenhouse_steward" / "profiles" / "tomato.json"
    document = json.loads(bundled.read_text(encoding="utf-8"))
    document["safety"]["relay_max_on_seconds"] = 30.0
    profile = tmp_path / "tomato.json"
    profile.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ProfileSchemaError, match="JSON integer"):
        JsonProfileStore(tmp_path).load("tomato")

    document = json.loads(bundled.read_text(encoding="utf-8"))
    document["safety"]["hard_ranges"] = {
        "temperature_c": {"low": False, "high": 60},
        "humidity_pct": {"low": 0, "high": 100},
        "soil_moisture_pct": {"low": 0, "high": 100},
        "light_lux": {"low": 0, "high": 200000},
    }
    profile.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ProfileSchemaError, match="JSON number"):
        JsonProfileStore(tmp_path).load("tomato")
