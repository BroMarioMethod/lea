"""Canonical configuration templates for LEA runtime profiles."""

from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lea.runtime.contracts import (
    RUNTIME_SCHEMA_VERSION,
    ComponentRecordPaths,
    RuntimeConfig,
    RuntimePaths,
    RuntimeProfile,
    SecretPaths,
)
from lea.runtime.layouts import (
    development_runtime_paths,
    isolated_test_runtime_paths,
    system_runtime_paths,
)


def system_runtime_config(
    *,
    display_timezone: str = "UTC",
    telegram_token_file: Path | None = None,
) -> RuntimeConfig:
    """Return the canonical system runtime configuration."""
    return _build_runtime_config(
        profile=RuntimeProfile.SYSTEM,
        display_timezone=display_timezone,
        telegram_token_file=telegram_token_file,
        paths=system_runtime_paths(),
    )


def development_runtime_config(
    root: Path,
    *,
    display_timezone: str = "UTC",
    telegram_token_file: Path | None = None,
) -> RuntimeConfig:
    """Return a canonical development runtime configuration."""
    return _build_runtime_config(
        profile=RuntimeProfile.DEVELOPMENT,
        display_timezone=display_timezone,
        telegram_token_file=telegram_token_file,
        paths=development_runtime_paths(root),
    )


def isolated_test_runtime_config(
    root: Path,
    *,
    display_timezone: str = "UTC",
    telegram_token_file: Path | None = None,
) -> RuntimeConfig:
    """Return a canonical isolated-test runtime configuration."""
    return _build_runtime_config(
        profile=RuntimeProfile.TEST,
        display_timezone=display_timezone,
        telegram_token_file=telegram_token_file,
        paths=isolated_test_runtime_paths(root),
    )


def _build_runtime_config(
    *,
    profile: RuntimeProfile,
    display_timezone: str,
    telegram_token_file: Path | None,
    paths: RuntimePaths,
) -> RuntimeConfig:
    """Construct one validated canonical runtime configuration."""
    _validate_display_timezone(display_timezone)

    return RuntimeConfig(
        schema_version=RUNTIME_SCHEMA_VERSION,
        profile=profile,
        display_timezone=display_timezone,
        paths=paths,
        component_records=ComponentRecordPaths(
            taskwarrior=paths.state_dir / "install" / "taskwarrior.json",
        ),
        secrets=SecretPaths(
            telegram_token_file=telegram_token_file,
        ),
    )


def _validate_display_timezone(
    display_timezone: str,
) -> None:
    """Validate one configured IANA display timezone."""
    if not isinstance(display_timezone, str):
        raise TypeError("display_timezone must be a string.")

    if not display_timezone.strip():
        raise ValueError(
            "display_timezone must be a non-empty IANA timezone identifier."
        )

    try:
        ZoneInfo(display_timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError(
            "display_timezone must be a recognised IANA timezone."
        ) from error
