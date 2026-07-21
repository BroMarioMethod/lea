"""Tests for read-only LEA runtime configuration inspection."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from lea.runtime import (
    ConfigurationIssue,
    ConfigurationResult,
    RuntimeConfig,
    RuntimeHealthIssue,
    RuntimeHealthResult,
    RuntimeHealthStatus,
    RuntimeInspectionResult,
    RuntimeProfile,
    bootstrap_runtime,
    initialise_runtime_config,
    inspect_runtime,
    isolated_test_runtime_config,
)


def create_config(tmp_path: Path) -> RuntimeConfig:
    """Create one isolated runtime configuration."""
    return isolated_test_runtime_config(
        tmp_path / "runtime",
        display_timezone="Africa/Gaborone",
    )


def prepare_configuration(tmp_path: Path) -> Path:
    """Create one valid runtime configuration file."""
    config = create_config(tmp_path)
    config.paths.config_file.parent.mkdir(parents=True)

    result = initialise_runtime_config(config)
    assert result.success is True

    return config.paths.config_file


def prepare_complete_runtime(tmp_path: Path) -> Path:
    """Create one valid configuration and runtime directory layout."""
    config = create_config(tmp_path)
    config.paths.config_file.parent.mkdir(parents=True)

    initialisation = initialise_runtime_config(config)
    bootstrap = bootstrap_runtime(config.paths)

    assert initialisation.success is True
    assert bootstrap.success is True

    return config.paths.config_file


def test_configuration_only_inspection_succeeds(
    tmp_path: Path,
) -> None:
    """Valid configuration should load without checking runtime state."""
    source_path = prepare_configuration(tmp_path)

    result = inspect_runtime(source_path)

    assert result.success is True
    assert result.configuration.success is True
    assert result.configuration.config is not None
    assert result.configuration.config.profile is RuntimeProfile.TEST
    assert result.health is None


def test_inspection_exposes_canonical_paths(
    tmp_path: Path,
) -> None:
    """Loaded configuration should expose its canonical layout."""
    source_path = prepare_configuration(tmp_path)

    result = inspect_runtime(source_path)

    assert result.configuration.config is not None
    config = result.configuration.config

    assert config.paths.config_file == source_path
    assert config.paths.state_dir == (tmp_path / "runtime" / "state")
    assert config.paths.log_dir == (tmp_path / "runtime" / "log")
    assert config.paths.run_dir == (tmp_path / "runtime" / "run")


def test_missing_configuration_fails_inspection(
    tmp_path: Path,
) -> None:
    """Missing configuration should preserve loader failure details."""
    source_path = tmp_path / "missing.toml"

    result = inspect_runtime(source_path)

    assert result.success is False
    assert result.configuration.success is False
    assert result.configuration.config is None
    assert result.health is None
    assert result.configuration.issues[0].code == "configuration_not_found"


def test_relative_configuration_path_fails_inspection() -> None:
    """Inspection must not depend on the working directory."""
    result = inspect_runtime(Path("lea.toml"))

    assert result.success is False
    assert result.configuration.success is False
    assert result.health is None
    assert result.configuration.issues[0].code == "invalid_path"


def test_configuration_only_inspection_creates_nothing(
    tmp_path: Path,
) -> None:
    """Inspection should not bootstrap missing runtime directories."""
    source_path = prepare_configuration(tmp_path)
    runtime_root = tmp_path / "runtime"

    result = inspect_runtime(source_path)

    assert result.success is True
    assert (runtime_root / "state").exists() is False
    assert (runtime_root / "log").exists() is False
    assert (runtime_root / "run").exists() is False


def test_health_inspection_succeeds_for_complete_runtime(
    tmp_path: Path,
) -> None:
    """Complete runtime state should pass optional health checking."""
    source_path = prepare_complete_runtime(tmp_path)

    result = inspect_runtime(
        source_path,
        include_health=True,
    )

    assert result.success is True
    assert result.configuration.success is True
    assert result.health is not None
    assert result.health.healthy is True


def test_health_inspection_reports_missing_directories(
    tmp_path: Path,
) -> None:
    """Optional health checking should expose incomplete runtime state."""
    source_path = prepare_configuration(tmp_path)

    result = inspect_runtime(
        source_path,
        include_health=True,
    )

    assert result.success is False
    assert result.configuration.success is True
    assert result.health is not None
    assert result.health.healthy is False
    assert any(issue.code == "runtime_path_missing" for issue in result.health.issues)


def test_failed_loading_skips_health_check(
    tmp_path: Path,
) -> None:
    """Health checking must not run without a valid configuration."""
    source_path = tmp_path / "missing.toml"

    result = inspect_runtime(
        source_path,
        include_health=True,
    )

    assert result.configuration.success is False
    assert result.health is None


def test_health_inspection_is_read_only(
    tmp_path: Path,
) -> None:
    """Health inspection must not repair incomplete runtime state."""
    source_path = prepare_configuration(tmp_path)
    runtime_root = tmp_path / "runtime"

    result = inspect_runtime(
        source_path,
        include_health=True,
    )

    assert result.success is False
    assert (runtime_root / "state").exists() is False
    assert (runtime_root / "log").exists() is False
    assert (runtime_root / "run").exists() is False


def test_inspection_result_is_immutable() -> None:
    """Inspection results should not permit reassignment."""
    configuration = ConfigurationResult(
        success=False,
        config=None,
        issues=(
            ConfigurationIssue(
                code="configuration_not_found",
                message="The configuration file is missing.",
            ),
        ),
    )
    result = RuntimeInspectionResult(
        success=False,
        configuration=configuration,
        health=None,
    )

    with pytest.raises(FrozenInstanceError):
        result.success = True  # type: ignore[misc]


def test_failed_configuration_rejects_health_result() -> None:
    """Health must be absent when configuration loading fails."""
    configuration = ConfigurationResult(
        success=False,
        config=None,
        issues=(
            ConfigurationIssue(
                code="configuration_not_found",
                message="The configuration file is missing.",
            ),
        ),
    )
    health = RuntimeHealthResult(
        healthy=False,
        issues=(
            RuntimeHealthIssue(
                code="runtime_path_missing",
                message="A runtime path is missing.",
                status=RuntimeHealthStatus.FAILED,
                path=Path("/var/lib/lea"),
            ),
        ),
    )

    with pytest.raises(
        ValueError,
        match="must not be checked when configuration loading fails",
    ):
        RuntimeInspectionResult(
            success=False,
            configuration=configuration,
            health=health,
        )


def test_failed_configuration_cannot_succeed() -> None:
    """Inspection cannot succeed when loading has failed."""
    configuration = ConfigurationResult(
        success=False,
        config=None,
        issues=(
            ConfigurationIssue(
                code="configuration_not_found",
                message="The configuration file is missing.",
            ),
        ),
    )

    with pytest.raises(
        ValueError,
        match="must fail when configuration loading fails",
    ):
        RuntimeInspectionResult(
            success=True,
            configuration=configuration,
            health=None,
        )


def test_success_must_match_unhealthy_result(
    tmp_path: Path,
) -> None:
    """Inspection success must reflect an unhealthy runtime."""
    source_path = prepare_configuration(tmp_path)
    inspected = inspect_runtime(source_path)

    assert inspected.configuration.success is True

    health = RuntimeHealthResult(
        healthy=False,
        issues=(
            RuntimeHealthIssue(
                code="runtime_path_missing",
                message="A runtime path is missing.",
                status=RuntimeHealthStatus.FAILED,
                path=Path("/var/lib/lea"),
            ),
        ),
    )

    with pytest.raises(
        ValueError,
        match="success must match",
    ):
        RuntimeInspectionResult(
            success=True,
            configuration=inspected.configuration,
            health=health,
        )


def test_successful_configuration_without_health_is_valid(
    tmp_path: Path,
) -> None:
    """Configuration-only inspection may succeed without health data."""
    source_path = prepare_configuration(tmp_path)
    inspected = inspect_runtime(source_path)

    result = RuntimeInspectionResult(
        success=True,
        configuration=inspected.configuration,
        health=None,
    )

    assert result.success is True
    assert result.health is None
