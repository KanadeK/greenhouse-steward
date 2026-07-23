"""Regenerate the committed seven-day deterministic sample datasets."""

from __future__ import annotations

import argparse
import io
from datetime import UTC, datetime
from pathlib import Path

from greenhouse_steward.adapters.profile_store import JsonProfileStore
from greenhouse_steward.sample_data.generator import (
    SyntheticDatasetConfig,
    build_manifest,
    generate_dataset,
    write_dataset_csv,
    write_manifest,
)


def main() -> int:
    """Generate both sample profiles and their checksum manifest."""

    repository_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=repository_root / "src" / "greenhouse_steward" / "sample_data" / "data",
    )
    parser.add_argument(
        "--examples-dir",
        type=Path,
        default=repository_root / "examples" / "data",
    )
    arguments = parser.parse_args()
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    arguments.examples_dir.mkdir(parents=True, exist_ok=True)

    store = JsonProfileStore()
    start = datetime(2026, 1, 5, tzinfo=UTC)
    configs = {
        "tomato-7d.csv": SyntheticDatasetConfig(
            profile_slug="tomato",
            device_id="sample-tomato",
            start=start,
            seed=3501,
        ),
        "herb-7d.csv": SyntheticDatasetConfig(
            profile_slug="herb",
            device_id="sample-herb",
            start=start,
            seed=3502,
        ),
    }
    payloads: dict[str, bytes] = {}
    for filename, config in configs.items():
        profile = store.load(config.profile_slug).profile
        snapshots = generate_dataset(config, profile)
        buffer = io.StringIO(newline="")
        write_dataset_csv(snapshots, buffer)
        payload = buffer.getvalue().encode("utf-8")
        (arguments.output_dir / filename).write_bytes(payload)
        (arguments.examples_dir / filename).write_bytes(payload)
        payloads[filename] = payload

    manifest = build_manifest(payloads, configs)
    write_manifest(arguments.output_dir / "MANIFEST.json", manifest)
    write_manifest(arguments.examples_dir / "MANIFEST.json", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
