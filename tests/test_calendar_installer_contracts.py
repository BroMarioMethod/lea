"""Tests for immutable calendar toolchain installer contracts."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from lea.installers.calendar import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallerValidationResult,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
)

_CHECKSUM = "a" * 64
_ConfigFactory = Callable[[], CalendarToolchainInstallerConfig]


def _network_config() -> CalendarToolchainInstallerConfig:
    """Return one valid verified-network configuration."""
    return CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.VERIFIED_NETWORK,
        toolchain_version="1",
        khal_version="0.11.4",
        vdirsyncer_version="0.19.3",
        platform="linux-aarch64",
        tools_root=Path("/opt/lea-tools/calendar"),
        configuration_dir=Path("/etc/lea/calendar"),
        state_root=Path("/var/lib/lea/calendar"),
        installation_record=Path("/var/lib/lea/install/calendar-toolchain.json"),
        service_user="lea",
        service_group="lea",
        uv_executable=Path("/opt/lea-tools/uv/bin/uv"),
        python_executable=Path("/usr/bin/python3.13"),
        requirements_lock=Path("/opt/lea-assets/calendar-requirements.txt"),
        expected_lock_sha256=_CHECKSUM,
        package_index_url="https://pypi.org/simple",
    )


def _bundled_config() -> CalendarToolchainInstallerConfig:
    """Return one valid bundled-wheelhouse configuration."""
    return replace(
        _network_config(),
        mode=CalendarToolchainInstallMode.BUNDLED_WHEELHOUSE,
        package_index_url=None,
        wheelhouse_archive=Path("/opt/lea-assets/calendar-toolchain-1.tar.gz"),
        expected_wheelhouse_sha256=_CHECKSUM,
    )


def _external_config() -> CalendarToolchainInstallerConfig:
    """Return one valid external-executables configuration."""
    return CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES,
        toolchain_version="external-1",
        khal_version="0.11.4",
        vdirsyncer_version="0.19.3",
        platform="linux-aarch64",
        tools_root=Path("/opt/lea-tools/calendar"),
        configuration_dir=Path("/etc/lea/calendar"),
        state_root=Path("/var/lib/lea/calendar"),
        installation_record=Path("/var/lib/lea/install/calendar-toolchain.json"),
        service_user="lea",
        service_group="lea",
        external_khal_executable=Path("/usr/bin/khal"),
        external_vdirsyncer_executable=Path("/usr/bin/vdirsyncer"),
    )


def test_install_modes_have_stable_values() -> None:
    """Installation mode identifiers should remain stable."""
    assert CalendarToolchainInstallMode.VERIFIED_NETWORK.value == "verified-network"
    assert CalendarToolchainInstallMode.BUNDLED_WHEELHOUSE.value == "bundled-wheelhouse"
    assert (
        CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES.value
        == "external-executables"
    )


@pytest.mark.parametrize(
    "config",
    (
        _network_config(),
        _bundled_config(),
        _external_config(),
    ),
)
def test_supported_configurations_are_valid(
    config: CalendarToolchainInstallerConfig,
) -> None:
    """Every supported installation mode should accept its exact inputs."""
    assert config.khal_version == "0.11.4"
    assert config.vdirsyncer_version == "0.19.3"
    assert config.non_interactive is True


@pytest.mark.parametrize(
    "factory",
    (
        lambda: replace(
            _network_config(),
            tools_root=Path("relative/path"),
        ),
        lambda: replace(
            _network_config(),
            configuration_dir=Path("relative/path"),
        ),
        lambda: replace(
            _network_config(),
            state_root=Path("relative/path"),
        ),
        lambda: replace(
            _network_config(),
            installation_record=Path("relative/path"),
        ),
    ),
)
def test_required_paths_must_be_absolute(
    factory: _ConfigFactory,
) -> None:
    """Every required managed path should be absolute."""
    with pytest.raises(ValueError, match="must be an absolute path"):
        factory()


@pytest.mark.parametrize(
    "factory",
    (
        lambda: replace(
            _network_config(),
            uv_executable=None,
        ),
        lambda: replace(
            _network_config(),
            python_executable=None,
        ),
        lambda: replace(
            _network_config(),
            requirements_lock=None,
        ),
        lambda: replace(
            _bundled_config(),
            uv_executable=None,
        ),
        lambda: replace(
            _bundled_config(),
            python_executable=None,
        ),
        lambda: replace(
            _bundled_config(),
            requirements_lock=None,
        ),
    ),
)
def test_managed_modes_require_environment_inputs(
    factory: _ConfigFactory,
) -> None:
    """Managed modes should require exact environment-building inputs."""
    with pytest.raises(ValueError, match="is required"):
        factory()


def test_network_mode_requires_package_index() -> None:
    """Verified-network mode should require one explicit package index."""
    with pytest.raises(ValueError, match="package_index_url is required"):
        replace(
            _network_config(),
            package_index_url=None,
        )


@pytest.mark.parametrize(
    "factory",
    (
        lambda: replace(
            _network_config(),
            wheelhouse_archive=Path("/tmp/wheelhouse.tar.gz"),
        ),
        lambda: replace(
            _network_config(),
            expected_wheelhouse_sha256=_CHECKSUM,
        ),
    ),
)
def test_network_mode_rejects_wheelhouse_inputs(
    factory: _ConfigFactory,
) -> None:
    """Verified-network mode should reject offline-only inputs."""
    with pytest.raises(ValueError, match="verified-network mode"):
        factory()


def test_bundled_mode_requires_wheelhouse_archive() -> None:
    """Bundled mode should require its verified wheelhouse archive."""
    with pytest.raises(ValueError, match="wheelhouse_archive is required"):
        replace(
            _bundled_config(),
            wheelhouse_archive=None,
        )


def test_bundled_mode_requires_wheelhouse_checksum() -> None:
    """Bundled mode should require its wheelhouse SHA-256 value."""
    with pytest.raises(
        ValueError,
        match="expected_wheelhouse_sha256 is required",
    ):
        replace(
            _bundled_config(),
            expected_wheelhouse_sha256=None,
        )


def test_bundled_mode_rejects_package_index() -> None:
    """Bundled mode should remain independent of package indexes."""
    with pytest.raises(
        ValueError,
        match="package_index_url must not be set",
    ):
        replace(
            _bundled_config(),
            package_index_url="https://pypi.org/simple",
        )


@pytest.mark.parametrize(
    "factory",
    (
        lambda: replace(
            _network_config(),
            expected_lock_sha256="invalid",
        ),
        lambda: replace(
            _bundled_config(),
            expected_wheelhouse_sha256="invalid",
        ),
    ),
)
def test_managed_modes_require_canonical_checksums(
    factory: _ConfigFactory,
) -> None:
    """Managed artefacts should require canonical SHA-256 text."""
    with pytest.raises(
        ValueError,
        match="lower-case hexadecimal SHA-256",
    ):
        factory()


@pytest.mark.parametrize(
    "factory",
    (
        lambda: replace(
            _network_config(),
            external_khal_executable=Path("/usr/bin/khal"),
        ),
        lambda: replace(
            _bundled_config(),
            external_vdirsyncer_executable=Path("/usr/bin/vdirsyncer"),
        ),
    ),
)
def test_managed_modes_reject_external_executables(
    factory: _ConfigFactory,
) -> None:
    """Managed modes should not mix administrator-selected commands."""
    with pytest.raises(ValueError, match="must not be set for managed modes"):
        factory()


@pytest.mark.parametrize(
    "factory",
    (
        lambda: replace(
            _external_config(),
            external_khal_executable=None,
        ),
        lambda: replace(
            _external_config(),
            external_vdirsyncer_executable=None,
        ),
    ),
)
def test_external_mode_requires_both_executables(
    factory: _ConfigFactory,
) -> None:
    """External mode should require an exact path for both tools."""
    with pytest.raises(ValueError, match="is required"):
        factory()


@pytest.mark.parametrize(
    "factory",
    (
        lambda: replace(
            _external_config(),
            uv_executable=Path("/usr/bin/uv"),
        ),
        lambda: replace(
            _external_config(),
            python_executable=Path("/usr/bin/python3"),
        ),
        lambda: replace(
            _external_config(),
            requirements_lock=Path("/tmp/requirements.txt"),
        ),
        lambda: replace(
            _external_config(),
            expected_lock_sha256=_CHECKSUM,
        ),
        lambda: replace(
            _external_config(),
            package_index_url="https://pypi.org/simple",
        ),
        lambda: replace(
            _external_config(),
            wheelhouse_archive=Path("/tmp/wheelhouse.tar.gz"),
        ),
        lambda: replace(
            _external_config(),
            expected_wheelhouse_sha256=_CHECKSUM,
        ),
    ),
)
def test_external_mode_rejects_managed_inputs(
    factory: _ConfigFactory,
) -> None:
    """External mode should reject managed-environment inputs."""
    with pytest.raises(
        ValueError,
        match="must not be set for external-executables mode",
    ):
        factory()


def test_timeout_must_be_positive() -> None:
    """Installer subprocesses should always have a finite positive timeout."""
    with pytest.raises(
        ValueError,
        match="timeout_seconds must be greater than zero",
    ):
        replace(
            _network_config(),
            timeout_seconds=0,
        )


def test_issue_paths_must_be_absolute() -> None:
    """Structured installer issues should not contain ambiguous paths."""
    with pytest.raises(ValueError, match="path must be an absolute path"):
        CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.ARTEFACT_MISSING,
            message="The archive is missing.",
            path=Path("relative/archive.tar.gz"),
        )


def test_successful_validation_result_requires_configuration() -> None:
    """A successful validation result should contain its configuration."""
    result = CalendarToolchainInstallerValidationResult(
        valid=True,
        config=_network_config(),
        issues=(),
    )

    assert result.valid is True
    assert result.config is not None


def test_failed_validation_result_requires_issues() -> None:
    """A failed validation result should contain structured issues."""
    issue = CalendarToolchainInstallerIssue(
        code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
        message="The installer configuration is invalid.",
    )
    result = CalendarToolchainInstallerValidationResult(
        valid=False,
        config=None,
        issues=(issue,),
    )

    assert result.valid is False
    assert result.issues == (issue,)


def test_invalid_validation_result_is_rejected() -> None:
    """Failure without configuration or issues should be impossible."""
    with pytest.raises(
        ValueError,
        match="must contain at least one issue",
    ):
        CalendarToolchainInstallerValidationResult(
            valid=False,
            config=None,
            issues=(),
        )
