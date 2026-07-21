"""Tests for coordinated LEA runtime setup."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from lea.runtime import (
    RuntimeBootstrapResult,
    RuntimeConfig,
    RuntimeInitialisationResult,
    RuntimeInitialisationStatus,
    RuntimePathResult,
    RuntimePathStatus,
    RuntimeSetupResult,
    bootstrap_runtime,
    isolated_test_runtime_config,
    load_runtime_config,
    setup_runtime,
)


def create_config(tmp_path: Path) -> RuntimeConfig:
    """Create one isolated runtime configuration."""
    return isolated_test_runtime_config(
        tmp_path / "runtime",
        display_timezone="Africa/Gaborone",
    )


def prepare_config_parent(config: RuntimeConfig) -> None:
    """Create only the explicit configuration parent."""
    config.paths.config_file.parent.mkdir(parents=True)


def test_dry_run_reports_complete_setup(
    tmp_path: Path,
) -> None:
    """Dry-run setup should report both planned operations."""
    config = create_config(tmp_path)
    prepare_config_parent(config)

    result = setup_runtime(
        config,
        dry_run=True,
    )

    assert result.success is True
    assert result.dry_run is True
    assert result.initialisation.status is RuntimeInitialisationStatus.WOULD_CREATE
    assert result.bootstrap is not None
    assert result.bootstrap.success is True
    assert all(
        item.status is RuntimePathStatus.WOULD_CREATE for item in result.bootstrap.paths
    )
    assert config.paths.config_file.exists() is False
    assert config.paths.state_dir.exists() is False


def test_setup_creates_configuration_and_directories(
    tmp_path: Path,
) -> None:
    """Real setup should create configuration and runtime directories."""
    config = create_config(tmp_path)
    prepare_config_parent(config)

    result = setup_runtime(config)

    assert result.success is True
    assert result.dry_run is False
    assert result.initialisation.status is RuntimeInitialisationStatus.CREATED
    assert result.bootstrap is not None
    assert result.bootstrap.success is True
    assert config.paths.config_file.is_file()
    assert config.paths.state_dir.is_dir()
    assert config.paths.log_dir.is_dir()
    assert config.paths.run_dir.is_dir()


def test_setup_configuration_round_trips(
    tmp_path: Path,
) -> None:
    """A setup-created configuration should load successfully."""
    config = create_config(tmp_path)
    prepare_config_parent(config)

    result = setup_runtime(config)
    loaded = load_runtime_config(config.paths.config_file)

    assert result.success is True
    assert loaded.success is True
    assert loaded.config == config


def test_existing_configuration_stops_setup(
    tmp_path: Path,
) -> None:
    """Existing configuration should prevent runtime bootstrap."""
    config = create_config(tmp_path)
    prepare_config_parent(config)
    config.paths.config_file.write_text(
        "existing configuration\n",
        encoding="utf-8",
    )

    result = setup_runtime(config)

    assert result.success is False
    assert result.initialisation.status is RuntimeInitialisationStatus.ALREADY_EXISTS
    assert result.bootstrap is None
    assert config.paths.state_dir.exists() is False


def test_missing_configuration_parent_stops_setup(
    tmp_path: Path,
) -> None:
    """Setup should preserve the explicit-parent requirement."""
    config = create_config(tmp_path)

    result = setup_runtime(config)

    assert result.success is False
    assert result.initialisation.status is RuntimeInitialisationStatus.FAILED
    assert result.bootstrap is None
    assert config.paths.config_file.parent.exists() is False
    assert config.paths.state_dir.exists() is False


def test_configuration_destination_conflict_stops_setup(
    tmp_path: Path,
) -> None:
    """A directory at config_file should prevent bootstrap."""
    config = create_config(tmp_path)
    config.paths.config_file.mkdir(parents=True)

    result = setup_runtime(config)

    assert result.success is False
    assert result.initialisation.status is RuntimeInitialisationStatus.CONFLICT
    assert result.bootstrap is None
    assert config.paths.state_dir.exists() is False


def test_bootstrap_conflict_is_exposed(
    tmp_path: Path,
) -> None:
    """Directory bootstrap failure should remain visible."""
    config = create_config(tmp_path)
    prepare_config_parent(config)

    config.paths.state_dir.write_text(
        "conflict",
        encoding="utf-8",
    )

    result = setup_runtime(config)

    assert result.success is False
    assert result.initialisation.status is RuntimeInitialisationStatus.CREATED
    assert result.bootstrap is not None
    assert result.bootstrap.success is False
    assert result.bootstrap.paths[-1].status is RuntimePathStatus.CONFLICT
    assert config.paths.config_file.is_file()


def test_dry_run_detects_bootstrap_conflict(
    tmp_path: Path,
) -> None:
    """Dry-run setup should expose existing runtime conflicts."""
    config = create_config(tmp_path)
    prepare_config_parent(config)

    config.paths.state_dir.write_text(
        "conflict",
        encoding="utf-8",
    )

    result = setup_runtime(
        config,
        dry_run=True,
    )

    assert result.success is False
    assert result.initialisation.status is RuntimeInitialisationStatus.WOULD_CREATE
    assert result.bootstrap is not None
    assert result.bootstrap.success is False
    assert config.paths.config_file.exists() is False


def test_setup_does_not_create_output_files(
    tmp_path: Path,
) -> None:
    """Setup should not create audit or log data files."""
    config = create_config(tmp_path)
    prepare_config_parent(config)

    result = setup_runtime(config)

    assert result.success is True
    assert config.paths.audit_file.exists() is False
    assert config.paths.log_file.exists() is False


def test_repeated_setup_preserves_existing_runtime(
    tmp_path: Path,
) -> None:
    """A second setup should stop before changing existing state."""
    config = create_config(tmp_path)
    prepare_config_parent(config)

    first = setup_runtime(config)
    second = setup_runtime(config)

    assert first.success is True
    assert second.success is False
    assert second.initialisation.status is RuntimeInitialisationStatus.ALREADY_EXISTS
    assert second.bootstrap is None
    assert config.paths.state_dir.is_dir()


def test_setup_result_is_immutable() -> None:
    """Combined setup results should be immutable."""
    initialisation = RuntimeInitialisationResult(
        success=True,
        dry_run=True,
        status=RuntimeInitialisationStatus.WOULD_CREATE,
        destination=Path("/etc/lea/lea.toml"),
        message="The configuration would be created.",
    )
    bootstrap = RuntimeBootstrapResult(
        success=True,
        dry_run=True,
        paths=(),
    )
    result = RuntimeSetupResult(
        success=True,
        dry_run=True,
        initialisation=initialisation,
        bootstrap=bootstrap,
    )

    with pytest.raises(FrozenInstanceError):
        result.success = False  # type: ignore[misc]


def test_setup_result_rejects_dry_run_mismatch() -> None:
    """Underlying operations must share the setup dry-run value."""
    initialisation = RuntimeInitialisationResult(
        success=True,
        dry_run=True,
        status=RuntimeInitialisationStatus.WOULD_CREATE,
        destination=Path("/etc/lea/lea.toml"),
        message="The configuration would be created.",
    )
    bootstrap = RuntimeBootstrapResult(
        success=True,
        dry_run=False,
        paths=(),
    )

    with pytest.raises(
        ValueError,
        match="bootstrap result dry-run value must match",
    ):
        RuntimeSetupResult(
            success=True,
            dry_run=True,
            initialisation=initialisation,
            bootstrap=bootstrap,
        )


def test_setup_result_rejects_incorrect_success() -> None:
    """Combined success must match both underlying results."""
    initialisation = RuntimeInitialisationResult(
        success=True,
        dry_run=True,
        status=RuntimeInitialisationStatus.WOULD_CREATE,
        destination=Path("/etc/lea/lea.toml"),
        message="The configuration would be created.",
    )
    bootstrap = RuntimeBootstrapResult(
        success=True,
        dry_run=True,
        paths=(),
    )

    with pytest.raises(
        ValueError,
        match="success must match",
    ):
        RuntimeSetupResult(
            success=False,
            dry_run=True,
            initialisation=initialisation,
            bootstrap=bootstrap,
        )


def test_setup_result_rejects_bootstrap_after_initialisation_failure() -> None:
    """Bootstrap must be absent after initialisation failure."""
    initialisation = RuntimeInitialisationResult(
        success=False,
        dry_run=False,
        status=RuntimeInitialisationStatus.FAILED,
        destination=Path("/etc/lea/lea.toml"),
        message="The configuration could not be created.",
    )
    bootstrap = RuntimeBootstrapResult(
        success=True,
        dry_run=False,
        paths=(),
    )

    with pytest.raises(
        ValueError,
        match="must not run after configuration initialisation fails",
    ):
        RuntimeSetupResult(
            success=False,
            dry_run=False,
            initialisation=initialisation,
            bootstrap=bootstrap,
        )


def test_setup_result_accepts_bootstrap_failure() -> None:
    """A failed bootstrap should produce a valid failed setup."""
    initialisation = RuntimeInitialisationResult(
        success=True,
        dry_run=False,
        status=RuntimeInitialisationStatus.CREATED,
        destination=Path("/etc/lea/lea.toml"),
        message="The configuration was created.",
    )
    path_result = RuntimePathResult(
        path=Path("/var/lib/lea"),
        status=RuntimePathStatus.CONFLICT,
        message="Runtime path conflicts.",
    )
    bootstrap = RuntimeBootstrapResult(
        success=False,
        dry_run=False,
        paths=(path_result,),
    )

    result = RuntimeSetupResult(
        success=False,
        dry_run=False,
        initialisation=initialisation,
        bootstrap=bootstrap,
    )

    assert result.success is False


def test_setup_matches_direct_operations(
    tmp_path: Path,
) -> None:
    """Dry-run setup should preserve direct-operation outcomes."""
    config = create_config(tmp_path)
    prepare_config_parent(config)

    direct_bootstrap = bootstrap_runtime(
        config.paths,
        dry_run=True,
    )
    combined = setup_runtime(
        config,
        dry_run=True,
    )

    assert combined.bootstrap == direct_bootstrap
