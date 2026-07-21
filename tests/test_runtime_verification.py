"""Tests for LEA runtime setup and health verification."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from lea.runtime import (
    RuntimeBootstrapResult,
    RuntimeConfig,
    RuntimeHealthIssue,
    RuntimeHealthResult,
    RuntimeHealthStatus,
    RuntimeInitialisationResult,
    RuntimeInitialisationStatus,
    RuntimeSetupResult,
    RuntimeSetupVerificationResult,
    isolated_test_runtime_config,
    setup_and_verify_runtime,
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


def successful_setup_result(
    *,
    dry_run: bool,
) -> RuntimeSetupResult:
    """Return one internally consistent successful setup result."""
    initialisation = RuntimeInitialisationResult(
        success=True,
        dry_run=dry_run,
        status=(
            RuntimeInitialisationStatus.WOULD_CREATE
            if dry_run
            else RuntimeInitialisationStatus.CREATED
        ),
        destination=Path("/etc/lea/lea.toml"),
        message=(
            "The configuration would be created."
            if dry_run
            else "The configuration was created."
        ),
    )
    bootstrap = RuntimeBootstrapResult(
        success=True,
        dry_run=dry_run,
        paths=(),
    )

    return RuntimeSetupResult(
        success=True,
        dry_run=dry_run,
        initialisation=initialisation,
        bootstrap=bootstrap,
    )


def failed_setup_result() -> RuntimeSetupResult:
    """Return one internally consistent failed setup result."""
    initialisation = RuntimeInitialisationResult(
        success=False,
        dry_run=False,
        status=RuntimeInitialisationStatus.FAILED,
        destination=Path("/etc/lea/lea.toml"),
        message="The configuration could not be created.",
    )

    return RuntimeSetupResult(
        success=False,
        dry_run=False,
        initialisation=initialisation,
        bootstrap=None,
    )


def healthy_result() -> RuntimeHealthResult:
    """Return one healthy runtime result."""
    return RuntimeHealthResult(
        healthy=True,
        issues=(
            RuntimeHealthIssue(
                code="runtime_available",
                message="The runtime is available.",
                status=RuntimeHealthStatus.PASSED,
            ),
        ),
    )


def unhealthy_result() -> RuntimeHealthResult:
    """Return one unhealthy runtime result."""
    return RuntimeHealthResult(
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


def test_real_setup_is_verified_as_healthy(
    tmp_path: Path,
) -> None:
    """Successful real setup should be checked for health."""
    config = create_config(tmp_path)
    prepare_config_parent(config)

    result = setup_and_verify_runtime(config)

    assert result.setup.success is True
    assert result.dry_run is False
    assert result.health is not None
    assert result.health.healthy is True
    assert result.verified is True


def test_dry_run_is_not_claimed_as_verified(
    tmp_path: Path,
) -> None:
    """Dry-run planning must not claim a healthy live runtime."""
    config = create_config(tmp_path)
    prepare_config_parent(config)

    result = setup_and_verify_runtime(
        config,
        dry_run=True,
    )

    assert result.setup.success is True
    assert result.dry_run is True
    assert result.verified is False
    assert result.health is None
    assert config.paths.config_file.exists() is False
    assert config.paths.state_dir.exists() is False


def test_failed_setup_skips_health_check(
    tmp_path: Path,
) -> None:
    """Health checking should not run after setup failure."""
    config = create_config(tmp_path)

    result = setup_and_verify_runtime(config)

    assert result.setup.success is False
    assert result.verified is False
    assert result.health is None


def test_existing_configuration_stops_verification(
    tmp_path: Path,
) -> None:
    """Existing configuration should stop before health checking."""
    config = create_config(tmp_path)
    prepare_config_parent(config)
    config.paths.config_file.write_text(
        "existing configuration\n",
        encoding="utf-8",
    )

    result = setup_and_verify_runtime(config)

    assert result.setup.success is False
    assert (
        result.setup.initialisation.status is RuntimeInitialisationStatus.ALREADY_EXISTS
    )
    assert result.health is None
    assert result.verified is False


def test_verified_setup_creates_expected_runtime(
    tmp_path: Path,
) -> None:
    """Verified setup should leave required runtime paths present."""
    config = create_config(tmp_path)
    prepare_config_parent(config)

    result = setup_and_verify_runtime(config)

    assert result.verified is True
    assert config.paths.config_file.is_file()
    assert config.paths.state_dir.is_dir()
    assert config.paths.log_dir.is_dir()
    assert config.paths.run_dir.is_dir()


def test_verified_setup_does_not_create_output_files(
    tmp_path: Path,
) -> None:
    """Verification should not create audit or log data files."""
    config = create_config(tmp_path)
    prepare_config_parent(config)

    result = setup_and_verify_runtime(config)

    assert result.verified is True
    assert config.paths.audit_file.exists() is False
    assert config.paths.log_file.exists() is False


def test_verification_result_is_immutable() -> None:
    """Setup-verification results should be immutable."""
    result = RuntimeSetupVerificationResult(
        verified=True,
        dry_run=False,
        setup=successful_setup_result(dry_run=False),
        health=healthy_result(),
    )

    with pytest.raises(FrozenInstanceError):
        result.verified = False  # type: ignore[misc]


def test_result_rejects_setup_dry_run_mismatch() -> None:
    """The outer dry-run value must match the setup result."""
    with pytest.raises(
        ValueError,
        match="setup result dry-run value must match",
    ):
        RuntimeSetupVerificationResult(
            verified=False,
            dry_run=False,
            setup=successful_setup_result(dry_run=True),
            health=None,
        )


def test_failed_setup_rejects_health_result() -> None:
    """Health results must be absent after setup failure."""
    with pytest.raises(
        ValueError,
        match="must not be checked after setup fails",
    ):
        RuntimeSetupVerificationResult(
            verified=False,
            dry_run=False,
            setup=failed_setup_result(),
            health=unhealthy_result(),
        )


def test_failed_setup_cannot_be_verified() -> None:
    """Failed setup must never be marked verified."""
    with pytest.raises(
        ValueError,
        match="failed runtime setup must not be verified",
    ):
        RuntimeSetupVerificationResult(
            verified=True,
            dry_run=False,
            setup=failed_setup_result(),
            health=None,
        )


def test_dry_run_rejects_health_result() -> None:
    """Dry-run setup must not inspect nonexistent runtime state."""
    with pytest.raises(
        ValueError,
        match="must not produce a runtime health result",
    ):
        RuntimeSetupVerificationResult(
            verified=False,
            dry_run=True,
            setup=successful_setup_result(dry_run=True),
            health=healthy_result(),
        )


def test_dry_run_cannot_be_verified() -> None:
    """Dry-run setup must never claim successful verification."""
    with pytest.raises(
        ValueError,
        match="must not claim that the runtime was verified",
    ):
        RuntimeSetupVerificationResult(
            verified=True,
            dry_run=True,
            setup=successful_setup_result(dry_run=True),
            health=None,
        )


def test_real_success_requires_health_result() -> None:
    """Successful real setup must always include health checking."""
    with pytest.raises(
        ValueError,
        match="must include a runtime health result",
    ):
        RuntimeSetupVerificationResult(
            verified=False,
            dry_run=False,
            setup=successful_setup_result(dry_run=False),
            health=None,
        )


def test_verified_value_must_match_healthy_result() -> None:
    """Verification must reflect the health-check outcome."""
    with pytest.raises(
        ValueError,
        match="must match the health result",
    ):
        RuntimeSetupVerificationResult(
            verified=False,
            dry_run=False,
            setup=successful_setup_result(dry_run=False),
            health=healthy_result(),
        )


def test_unhealthy_result_produces_unverified_outcome() -> None:
    """An unhealthy result should support a valid unverified outcome."""
    result = RuntimeSetupVerificationResult(
        verified=False,
        dry_run=False,
        setup=successful_setup_result(dry_run=False),
        health=unhealthy_result(),
    )

    assert result.verified is False
    assert result.health is not None
    assert result.health.healthy is False
