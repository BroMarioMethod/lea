"""Tests for deterministic runtime TOML serialisation."""

from pathlib import Path

import pytest

from lea.runtime import (
    RuntimeConfig,
    RuntimeProfile,
    isolated_test_runtime_config,
    load_runtime_config,
    render_runtime_config,
    write_runtime_config,
)


def create_config(
    tmp_path: Path,
    *,
    with_secret: bool = True,
) -> RuntimeConfig:
    """Return one isolated configuration for serialisation tests."""
    root = tmp_path / "runtime"
    secret_path = root / "secrets" / "telegram-token" if with_secret else None

    return isolated_test_runtime_config(
        root,
        display_timezone="Africa/Gaborone",
        telegram_token_file=secret_path,
    )


def test_rendered_toml_has_deterministic_order(
    tmp_path: Path,
) -> None:
    """Rendered fields should use one stable canonical order."""
    config = create_config(tmp_path)

    rendered = render_runtime_config(config)

    assert rendered.index("schema_version") < rendered.index("profile")
    assert rendered.index("profile") < rendered.index("display_timezone")
    assert rendered.index("[paths]") < rendered.index("[files]")
    assert rendered.index("[files]") < rendered.index("[component_records]")
    assert rendered.index("[component_records]") < rendered.index("[secrets]")


def test_rendered_toml_ends_with_one_newline(
    tmp_path: Path,
) -> None:
    """Generated configuration should have a stable final newline."""
    rendered = render_runtime_config(create_config(tmp_path))

    assert rendered.endswith("\n")
    assert not rendered.endswith("\n\n")


def test_rendering_is_deterministic(
    tmp_path: Path,
) -> None:
    """Repeated rendering should produce identical text."""
    config = create_config(tmp_path)

    assert render_runtime_config(config) == render_runtime_config(config)


def test_secret_table_is_omitted_when_unused(
    tmp_path: Path,
) -> None:
    """Unused optional secret references should not be emitted."""
    config = create_config(
        tmp_path,
        with_secret=False,
    )

    rendered = render_runtime_config(config)

    assert "[secrets]" not in rendered
    assert "telegram_token_file" not in rendered


def test_rendered_configuration_contains_no_secret_value(
    tmp_path: Path,
) -> None:
    """Serialisation should contain only a secret-file reference."""
    config = create_config(tmp_path)

    rendered = render_runtime_config(config)

    assert "telegram_token_file" in rendered
    assert "actual-secret-value" not in rendered


def test_written_configuration_loads_successfully(
    tmp_path: Path,
) -> None:
    """Serialised configuration should round-trip through the loader."""
    config = create_config(tmp_path)
    config.paths.config_file.parent.mkdir(parents=True)

    target = write_runtime_config(config)
    loaded = load_runtime_config(target)

    assert loaded.success is True
    assert loaded.config == config


def test_write_returns_destination_path(
    tmp_path: Path,
) -> None:
    """Successful writing should return the written path."""
    config = create_config(tmp_path)
    config.paths.config_file.parent.mkdir(parents=True)

    result = write_runtime_config(config)

    assert result == config.paths.config_file
    assert result.is_file()


def test_existing_configuration_is_not_overwritten(
    tmp_path: Path,
) -> None:
    """Exclusive writing should preserve existing configuration."""
    config = create_config(tmp_path)
    config.paths.config_file.parent.mkdir(parents=True)
    config.paths.config_file.write_text(
        "existing content\n",
        encoding="utf-8",
    )

    with pytest.raises(FileExistsError):
        write_runtime_config(config)

    assert config.paths.config_file.read_text(encoding="utf-8") == "existing content\n"


def test_explicit_overwrite_replaces_existing_file(
    tmp_path: Path,
) -> None:
    """Overwriting should require an explicit true flag."""
    config = create_config(tmp_path)
    config.paths.config_file.parent.mkdir(parents=True)
    config.paths.config_file.write_text(
        "existing content\n",
        encoding="utf-8",
    )

    write_runtime_config(
        config,
        overwrite=True,
    )

    assert config.paths.config_file.read_text(
        encoding="utf-8"
    ) == render_runtime_config(config)


def test_explicit_destination_is_supported(
    tmp_path: Path,
) -> None:
    """Callers may provide another absolute destination."""
    config = create_config(tmp_path)
    destination = tmp_path / "output" / "custom.toml"
    destination.parent.mkdir()

    result = write_runtime_config(
        config,
        destination=destination,
    )

    assert result == destination
    assert destination.read_text(encoding="utf-8") == render_runtime_config(config)


def test_relative_destination_is_rejected(
    tmp_path: Path,
) -> None:
    """Writing must not depend on the current working directory."""
    config = create_config(tmp_path)

    with pytest.raises(
        ValueError,
        match="destination must be an absolute path",
    ):
        write_runtime_config(
            config,
            destination=Path("lea.toml"),
        )


def test_missing_destination_parent_is_rejected(
    tmp_path: Path,
) -> None:
    """Serialisation should not create parent directories implicitly."""
    config = create_config(tmp_path)
    destination = tmp_path / "missing" / "lea.toml"

    with pytest.raises(
        FileNotFoundError,
        match="parent directory does not exist",
    ):
        write_runtime_config(
            config,
            destination=destination,
        )

    assert destination.parent.exists() is False


def test_rendered_profile_uses_stable_enum_value(
    tmp_path: Path,
) -> None:
    """The TOML profile should use the external string value."""
    config = create_config(tmp_path)

    rendered = render_runtime_config(config)

    assert config.profile is RuntimeProfile.TEST
    assert 'profile = "test"' in rendered


def test_rendered_configuration_contains_component_record(tmp_path: Path) -> None:
    """Serialisation should preserve the Taskwarrior record path."""
    config = create_config(tmp_path)
    rendered = render_runtime_config(config)
    assert "[component_records]" in rendered
    assert f'taskwarrior = "{config.component_records.taskwarrior}"' in rendered
