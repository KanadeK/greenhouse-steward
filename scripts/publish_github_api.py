"""Publish an existing local commit through GitHub's Git data API.

This is a transport fallback for environments where ``git push`` cannot reach
GitHub but the authenticated GitHub CLI can. It never reads or prints tokens.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["GIT_CONFIG_COUNT"] = "1"
os.environ["GIT_CONFIG_KEY_0"] = "safe.directory"
os.environ["GIT_CONFIG_VALUE_0"] = str(ROOT)


def api(repository: str, method: str, endpoint: str, payload: object) -> object:
    completed = subprocess.run(
        ["gh", "api", f"repos/{repository}/git/{endpoint}", "--method", method, "--input", "-"],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "GitHub API request failed")
    return json.loads(completed.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", help="OWNER/REPOSITORY")
    parsed = parser.parse_args()
    commits = subprocess.check_output(
        ["git", "rev-list", "--reverse", "HEAD"], cwd=ROOT, text=True
    ).splitlines()
    blob_cache: dict[str, str] = {}
    parent: str | None = None
    for local_commit in commits:
        tree: list[dict[str, str]] = []
        entries = subprocess.check_output(
            ["git", "ls-tree", "-r", local_commit], cwd=ROOT, text=True
        ).splitlines()
        for entry in entries:
            metadata, path = entry.split("\t", 1)
            mode, _, local_blob = metadata.split()
            remote_blob = blob_cache.get(local_blob)
            if remote_blob is None:
                content = subprocess.check_output(["git", "cat-file", "blob", local_blob], cwd=ROOT)
                blob = api(
                    parsed.repository,
                    "POST",
                    "blobs",
                    {"content": base64.b64encode(content).decode(), "encoding": "base64"},
                )
                remote_blob = str(blob["sha"])
                blob_cache[local_blob] = remote_blob
            tree.append({"path": path, "mode": mode, "type": "blob", "sha": remote_blob})
        remote_tree = api(parsed.repository, "POST", "trees", {"tree": tree})
        fields = (
            subprocess.check_output(
                [
                    "git",
                    "show",
                    "-s",
                    "--format=%B%x00%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI",
                    local_commit,
                ],
                cwd=ROOT,
                text=True,
            )
            .rstrip("\n")
            .split("\x00")
        )
        message, an, ae, ad, cn, ce, cd = fields
        payload: dict[str, object] = {
            "message": message,
            "tree": remote_tree["sha"],
            "parents": [] if parent is None else [parent],
            "author": {"name": an, "email": ae, "date": ad},
            "committer": {"name": cn, "email": ce, "date": cd},
        }
        remote_commit = api(parsed.repository, "POST", "commits", payload)
        parent = str(remote_commit["sha"])
    if parent is None:
        raise RuntimeError("HEAD has no commits")
    api(parsed.repository, "PATCH", "refs/heads/main", {"sha": parent, "force": True})
    print(parent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
