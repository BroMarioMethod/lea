"""Tests for package version discovery."""

from lea.version import get_version


def test_get_version_returns_installed_version() -> None:
    """The package version should come from installed metadata."""
    assert get_version() == "0.2.0"
