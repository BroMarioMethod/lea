"""Tests for safe LEA runtime configuration initialisation."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from lea.runtime import (
    RuntimeConfig,
    RuntimeInitialisationResult,
    RuntimeInitialisationStatus,
    initialise_runtime_config,
    isolated_test_runtime_config,
    load_runtime_config,
    render_runtime_config,
)


def create_config(tmp_path: Path) -> RuntimeConfig:
    """Create one isolated runtime configuration."""
    return isolated_test_runtime_config(
        tmp_path / "runtime",
        display_timezone="Africa/Gaborone",
    )


def prepare_config_parent(tmp_path: Path) -> None:
    """Create only the canonical configuration parent directory."""
    config = create_config(tmp_path)
    config.paths.config_file.parent.mkdir(parents=True)


def test_dry_run_reports_configuration_creation(
    tmp_path: Path,
) -> None:
    """Dry-run mode should report without writing a file."""
    config = create_config(tmp_path)
    prepare_config_parent(tmp_path)

    result = initialise_runtime_config(
        config,
        dry_run=True,
    )

    assert result.success is True
    assert result.dry_run is True
    assert result.status is RuntimeInitialisationStatus.WOULD_CREATE
    assert result.destination == config.paths.config_file
    assert config.paths.config_file.exists() is False


def test_initialisation_creates_configuration(
    tmp_path: Path,
) -> None:
    """Initialisation should create deterministic TOML."""
    config = create_config(tmp_path)
    prepare_config_parent(tmp_path)

    result = initialise_runtime_config(config)

    assert result.success is True
    assert result.dry_run is False
    assert result.status is RuntimeInitialisationStatus.CREATED
    assert result.destination == config.paths.config_file
    assert config.paths.config_file.read_text(
        encoding="utf-8"
    ) == render_runtime_config(config)


def test_created_configuration_round_trips(
    tmp_path: Path,
) -> None:
    """An initialised configuration should load successfully."""
    config = create_config(tmp_path)
    prepare_config_parent(tmp_path)

    result = initialise_runtime_config(config)
    loaded = load_runtime_config(result.destination)

    assert result.success is True
    assert loaded.success is True
    assert loaded.config == config


def test_existing_configuration_is_not_overwritten(
    tmp_path: Path,
) -> None:
    """Existing configuration content must be preserved."""
    config = create_config(tmp_path)
    prepare_config_parent(tmp_path)
    config.paths.config_file.write_text(
        "existing configuration\n",
        encoding="utf-8",
    )

    result = initialise_runtime_config(config)

    assert result.success is False
    assert result.status is RuntimeInitialisationStatus.ALREADY_EXISTS
    assert (
        config.paths.config_file.read_text(encoding="utf-8")
        == "existing configuration\n"
    )


def test_dry_run_detects_existing_configuration(
    tmp_path: Path,
) -> None:
    """Dry-run mode should report an existing destination."""
    config = create_config(tmp_path)
    prepare_config_parent(tmp_path)
    config.paths.config_file.write_text(
        "existing configuration\n",
        encoding="utf-8",
    )

    result = initialise_runtime_config(
        config,
        dry_run=True,
    )

    assert result.success is False
    assert result.dry_run is True
    assert result.status is RuntimeInitialisationStatus.ALREADY_EXISTS


def test_destination_directory_is_a_conflict(
    tmp_path: Path,
) -> None:
    """A directory at the file destination should fail closed."""
    config = create_config(tmp_path)
    config.paths.config_file.mkdir(parents=True)

    result = initialise_runtime_config(config)

    assert result.success is False
    assert result.status is RuntimeInitialisationStatus.CONFLICT
    assert config.paths.config_file.is_dir()


def test_missing_parent_directory_is_reported(
    tmp_path: Path,
) -> None:
    """Initialisation should not create the config parent."""
    config = create_config(tmp_path)

    result = initialise_runtime_config(config)

    assert result.success is False
    assert result.status is RuntimeInitialisationStatus.FAILED
    assert config.paths.config_file.parent.exists() is False


def test_initialisation_creates_no_runtime_directories(
    tmp_path: Path,
) -> None:
    """Configuration creation must not bootstrap runtime state."""
    config = create_config(tmp_path)
    prepare_config_parent(tmp_path)

    result = initialise_runtime_config(config)

    assert result.success is True
    assert config.paths.state_dir.exists() is False
    assert config.paths.log_dir.exists() is False
    assert config.paths.run_dir.exists() is False


def test_initialisation_creates_no_output_files(
    tmp_path: Path,
) -> None:
    """Initialisation should create only the configuration file."""
    config = create_config(tmp_path)
    prepare_config_parent(tmp_path)

    initialise_runtime_config(config)

    assert config.paths.audit_file.exists() is False
    assert config.paths.log_file.exists() is False


def test_repeated_initialisation_is_safe(
    tmp_path: Path,
) -> None:
    """A second call should preserve the first configuration."""
    config = create_config(tmp_path)
    prepare_config_parent(tmp_path)

    first = initialise_runtime_config(config)
    original = config.paths.config_file.read_text(encoding="utf-8")
    second = initialise_runtime_config(config)

    assert first.status is RuntimeInitialisationStatus.CREATED
    assert second.status is RuntimeInitialisationStatus.ALREADY_EXISTS
    assert config.paths.config_file.read_text(encoding="utf-8") == original


def test_initialisation_result_is_immutable() -> None:
    """Initialisation results should not permit reassignment."""
    result = RuntimeInitialisationResult(
        success=True,
        dry_run=True,
        status=RuntimeInitialisationStatus.WOULD_CREATE,
        destination=Path("/etc/lea/lea.toml"),
        message="The configuration would be created.",
    )

    with pytest.raises(FrozenInstanceError):
        result.success = False  # type: ignore[misc]


def test_success_result_rejects_failure_status() -> None:
    """Successful results must use successful statuses."""
    with pytest.raises(
        ValueError,
        match="must use a successful status",
    ):
        RuntimeInitialisationResult(
            success=True,
            dry_run=False,
            status=RuntimeInitialisationStatus.FAILED,
            destination=Path("/etc/lea/lea.toml"),
            message="The configuration could not be created.",
        )


def test_failed_result_rejects_success_status() -> None:
    """Failed results must not use successful statuses."""
    with pytest.raises(
        ValueError,
        match="must use a failure status",
    ):
        RuntimeInitialisationResult(
            success=False,
            dry_run=True,
            status=RuntimeInitialisationStatus.WOULD_CREATE,
            destination=Path("/etc/lea/lea.toml"),
            message="The configuration would be created.",
        )


def test_dry_run_rejects_created_status() -> None:
    """Dry-run results must not claim filesystem mutation."""
    with pytest.raises(
        ValueError,
        match="must not report a created configuration",
    ):
        RuntimeInitialisationResult(
            success=True,
            dry_run=True,
            status=RuntimeInitialisationStatus.CREATED,
            destination=Path("/etc/lea/lea.toml"),
            message="The configuration was created.",
        )


def test_non_dry_run_rejects_would_create_status() -> None:
    """Real results must not use the dry-run success status."""
    with pytest.raises(
        ValueError,
        match="must not report that it would create",
    ):
        RuntimeInitialisationResult(
            success=True,
            dry_run=False,
            status=RuntimeInitialisationStatus.WOULD_CREATE,
            destination=Path("/etc/lea/lea.toml"),
            message="The configuration would be created.",
        )


def test_blank_result_message_is_rejected() -> None:
    """Initialisation messages must contain useful text."""
    with pytest.raises(
        ValueError,
        match="message must be non-empty",
    ):
        RuntimeInitialisationResult(
            success=True,
            dry_run=True,
            status=RuntimeInitialisationStatus.WOULD_CREATE,
            destination=Path("/etc/lea/lea.toml"),
            message="   ",
        )
