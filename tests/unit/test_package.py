"""Baseline package metadata tests."""

from greenhouse_steward import __version__


def test_package_version_matches_initial_release() -> None:
    """The importable package exposes the release version."""
    assert __version__ == "0.1.0"
