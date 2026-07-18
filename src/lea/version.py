"""Package version discovery for LEA."""

from importlib.metadata import PackageNotFoundError, version


def get_version() -> str:
    """Return the installed LEA package version."""
    try:
        return version("lea")
    except PackageNotFoundError:
        return "0+unknown"
