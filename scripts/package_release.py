"""Create reviewable v0.1.0 release artifacts and their SHA-256 manifest."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist-release"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    built = subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(DIST)],
        cwd=ROOT,
        check=False,
    )
    if built.returncode:
        return built.returncode
    for name in ("firmware", "examples", "docker-compose.yml", "Dockerfile"):
        source = ROOT / name
        target = DIST / f"greenhouse-steward-0.1.0-{name}"
        if source.is_dir():
            shutil.make_archive(str(target), "zip", ROOT, name)
        elif source.is_file():
            shutil.copy2(source, target.with_suffix(source.suffix))
    artifacts = sorted(path for path in DIST.iterdir() if path.is_file())
    (DIST / "SHA256SUMS.txt").write_text(
        "".join(f"{_hash(path)}  {path.name}\\n" for path in artifacts), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
