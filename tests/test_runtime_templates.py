"""Tests for canonical LEA runtime configuration templates."""

from pathlib import Path

import pytest

from lea.runtime import (
    RUNTIME_SCHEMA_VERSION,
    RuntimeProfile,
    development_runtime_config,
    isolated_test_runtime_config,
    system_runtime_config,
)


def test_system_template_uses_system_profile() -> None:
    """The system template should use canonical system paths."""
    config = system_runtime_config(
        display_timezone="Africa/Gaborone",
    )

    assert config.schema_version == RUNTIME_SCHEMA_VERSION
    assert config.profile is RuntimeProfile.SYSTEM
    assert config.display_timezone == "Africa/Gaborone"
    assert config.paths.config_file == Path("/etc/lea/lea.toml")


def test_development_template_uses_explicit_root(
    tmp_path: Path,
) -> None:
    """Development configuration should remain below its root."""
    root = tmp_path / "workspace"

    config = development_runtime_config(
        root,
        display_timezone="Africa/Gaborone",
    )

    assert config.profile is RuntimeProfile.DEVELOPMENT
    assert config.paths.state_dir == root / ".lea" / "state"
    assert config.paths.config_file == (root / ".lea" / "config" / "lea.toml")


def test_test_template_uses_explicit_root(
    tmp_path: Path,
) -> None:
    """Test configuration should use an isolated test layout."""
    root = tmp_path / "runtime"

    config = isolated_test_runtime_config(root)

    assert config.profile is RuntimeProfile.TEST
    assert config.paths.state_dir == root / "state"
    assert config.paths.config_file == (root / "config" / "lea.toml")


def test_default_display_timezone_is_utc(
    tmp_path: Path,
) -> None:
    """Templates should default to canonical UTC presentation."""
    config = isolated_test_runtime_config(tmp_path / "runtime")

    assert config.display_timezone == "UTC"


def test_template_accepts_secret_path_reference(
    tmp_path: Path,
) -> None:
    """Templates may contain a secret path but never its value."""
    root = tmp_path / "runtime"
    secret_path = root / "secrets" / "telegram-token"

    config = isolated_test_runtime_config(
        root,
        telegram_token_file=secret_path,
    )

    assert config.secrets.telegram_token_file == secret_path


@pytest.mark.parametrize(
    "display_timezone",
    [
        "",
        "   ",
    ],
)
def test_blank_display_timezone_is_rejected(
    tmp_path: Path,
    display_timezone: str,
) -> None:
    """Templates should reject blank timezone identifiers."""
    with pytest.raises(
        ValueError,
        match="non-empty IANA timezone",
    ):
        isolated_test_runtime_config(
            tmp_path / "runtime",
            display_timezone=display_timezone,
        )


def test_unknown_display_timezone_is_rejected(
    tmp_path: Path,
) -> None:
    """Templates should reject unknown IANA identifiers."""
    with pytest.raises(
        ValueError,
        match="recognised IANA timezone",
    ):
        isolated_test_runtime_config(
            tmp_path / "runtime",
            display_timezone="Invalid/Timezone",
        )


def test_template_construction_creates_nothing(
    tmp_path: Path,
) -> None:
    """Constructing a template must not mutate the filesystem."""
    root = tmp_path / "runtime"

    isolated_test_runtime_config(root)

    assert root.exists() is False


def test_template_is_deterministic(
    tmp_path: Path,
) -> None:
    """Identical inputs should produce identical configurations."""
    root = tmp_path / "runtime"

    first = isolated_test_runtime_config(
        root,
        display_timezone="Africa/Gaborone",
    )
    second = isolated_test_runtime_config(
        root,
        display_timezone="Africa/Gaborone",
    )

    assert first == second
