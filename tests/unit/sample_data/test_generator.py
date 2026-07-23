"""Deterministic packaged sample-data tests."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path

from greenhouse_steward.adapters.csv_source import StrictCsvSource
from greenhouse_steward.adapters.profile_store import JsonProfileStore
from greenhouse_steward.sample_data.generator import (
    SyntheticDatasetConfig,
    generate_dataset,
    write_dataset_csv,
)


def test_generator_is_byte_reproducible_and_has_672_rows() -> None:
    profile = JsonProfileStore().load("tomato").profile
    config = SyntheticDatasetConfig(
        profile_slug="tomato",
        device_id="sample-tomato",
        start=datetime(2026, 1, 5, tzinfo=UTC),
        seed=3501,
    )
    first = generate_dataset(config, profile)
    second = generate_dataset(config, profile)
    first_buffer = io.StringIO(newline="")
    second_buffer = io.StringIO(newline="")

    write_dataset_csv(first, first_buffer)
    write_dataset_csv(second, second_buffer)

    assert len(first) == 672
    assert first_buffer.getvalue().encode() == second_buffer.getvalue().encode()


def test_packaged_and_example_samples_use_canonical_names_and_parse() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    package_dir = repository_root / "src" / "greenhouse_steward" / "sample_data" / "data"
    examples_dir = repository_root / "examples" / "data"

    for filename, device_id in (
        ("tomato-7d.csv", "sample-tomato"),
        ("herb-7d.csv", "sample-herb"),
    ):
        packaged = package_dir / filename
        example = examples_dir / filename
        assert packaged.read_bytes() == example.read_bytes()
        assert len(StrictCsvSource().read_path(packaged, device_id=device_id)) == 672
    assert (package_dir / "MANIFEST.json").read_bytes() == (
        examples_dir / "MANIFEST.json"
    ).read_bytes()
