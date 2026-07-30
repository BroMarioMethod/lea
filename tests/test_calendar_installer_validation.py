"""Tests for calendar toolchain installer validation."""

import hashlib
import stat
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from lea.installers.calendar import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
    is_supported_khal_version,
    is_supported_vdirsyncer_version,
    is_valid_calendar_sha256,
    is_valid_https_package_index_url,
    normalise_calendar_platform,
    validate_calendar_executable_path,
    validate_calendar_toolchain_installer_config,
)


def _write_file(
    path: Path,
    payload: bytes,
) -> str:
    """Write one file and return its SHA-256 digest."""
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _make_executable(path: Path) -> None:
    """Create one executable test script."""
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _network_config(
    tmp_path: Path,
) -> CalendarToolchainInstallerConfig:
    """Return one valid verified-network configuration."""
    uv_executable = tmp_path / "uv"
    python_executable = tmp_path / "python3"
    requirements_lock = tmp_path / "calendar-requirements.txt"

    _make_executable(uv_executable)
    _make_executable(python_executable)
    lock_sha256 = _write_file(
        requirements_lock,
        b"khal==0.11.4\nvdirsyncer==0.19.3\n",
    )

    return CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.VERIFIED_NETWORK,
        toolchain_version=" 1 ",
        khal_version=" 0.11.4 ",
        vdirsyncer_version=" 0.19.3 ",
        platform=" ARM64 ",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "install.json",
        service_user=" lea ",
        service_group=" lea ",
        uv_executable=uv_executable,
        python_executable=python_executable,
        requirements_lock=requirements_lock,
        expected_lock_sha256=lock_sha256,
        package_index_url=" https://pypi.org/simple ",
    )


def _bundled_config(
    tmp_path: Path,
) -> CalendarToolchainInstallerConfig:
    """Return one valid bundled-wheelhouse configuration."""
    wheelhouse_archive = tmp_path / "calendar-wheelhouse.tar.gz"
    wheelhouse_sha256 = _write_file(
        wheelhouse_archive,
        b"verified wheelhouse",
    )

    return replace(
        _network_config(tmp_path),
        mode=CalendarToolchainInstallMode.BUNDLED_WHEELHOUSE,
        package_index_url=None,
        wheelhouse_archive=wheelhouse_archive,
        expected_wheelhouse_sha256=wheelhouse_sha256,
    )


def _external_config(
    tmp_path: Path,
) -> CalendarToolchainInstallerConfig:
    """Return one valid external-executables configuration."""
    khal_executable = tmp_path / "khal"
    vdirsyncer_executable = tmp_path / "vdirsyncer"
    _make_executable(khal_executable)
    _make_executable(vdirsyncer_executable)

    return CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES,
        toolchain_version=" external-1 ",
        khal_version=" 0.11.4 ",
        vdirsyncer_version=" 0.19.3 ",
        platform=" aarch64 ",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "install.json",
        service_user=" lea ",
        service_group=" lea ",
        external_khal_executable=khal_executable,
        external_vdirsyncer_executable=vdirsyncer_executable,
    )


def test_platform_aliases_are_normalised() -> None:
    """Common Debian and kernel architecture names should map canonically."""
    assert normalise_calendar_platform("arm64") == "linux-aarch64"
    assert normalise_calendar_platform("aarch64") == "linux-aarch64"
    assert normalise_calendar_platform("amd64") == "linux-x86_64"
    assert normalise_calendar_platform("x86_64") == "linux-x86_64"
    assert normalise_calendar_platform("mips64") is None


def test_initial_tool_versions_are_exact() -> None:
    """The first compatibility policy should accept only tested versions."""
    assert is_supported_khal_version("0.11.4") is True
    assert is_supported_khal_version("0.11.5") is False
    assert is_supported_vdirsyncer_version("0.19.3") is True
    assert is_supported_vdirsyncer_version("0.19.4") is False


def test_sha256_requires_lower_case_hex() -> None:
    """Checksums should use deterministic lower-case hexadecimal text."""
    assert is_valid_calendar_sha256("a" * 64) is True
    assert is_valid_calendar_sha256("A" * 64) is False
    assert is_valid_calendar_sha256("a" * 63) is False
    assert is_valid_calendar_sha256("g" * 64) is False


@pytest.mark.parametrize(
    "value",
    (
        "http://pypi.org/simple",
        "https://user:secret@pypi.org/simple",
        "https://pypi.org/simple?source=other",
        "https://pypi.org/simple#fragment",
        "not-a-url",
    ),
)
def test_package_index_requires_safe_https_url(value: str) -> None:
    """The online installer should reject ambiguous or credentialled URLs."""
    assert is_valid_https_package_index_url(value) is False

    assert is_valid_https_package_index_url("https://pypi.org/simple") is True


def test_executable_validation_inspects_mode(
    tmp_path: Path,
) -> None:
    """Executable validation should inspect existence and execute bits."""
    executable = tmp_path / "khal"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")

    issues = validate_calendar_executable_path(
        executable,
        field_name="external_khal_executable",
        tool_name="external khal",
    )

    assert len(issues) == 1
    assert issues[0].code is CalendarToolchainInstallFailureCode.PERMISSION_DENIED

    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

    assert (
        validate_calendar_executable_path(
            executable,
            field_name="external_khal_executable",
            tool_name="external khal",
        )
        == ()
    )


@pytest.mark.parametrize(
    "config_factory",
    (
        _network_config,
        _bundled_config,
        _external_config,
    ),
)
def test_valid_configurations_are_normalised(
    tmp_path: Path,
    config_factory: Callable[[Path], CalendarToolchainInstallerConfig],
) -> None:
    """Validated configurations should contain canonical values."""
    config = config_factory(tmp_path)

    result = validate_calendar_toolchain_installer_config(config)

    assert result.valid is True
    assert result.config is not None
    assert result.config.platform == "linux-aarch64"
    assert result.config.toolchain_version in {"1", "external-1"}
    assert result.config.khal_version == "0.11.4"
    assert result.config.vdirsyncer_version == "0.19.3"
    assert result.config.service_user == "lea"
    assert result.config.service_group == "lea"
    assert result.issues == ()


def test_unsupported_platform_fails(
    tmp_path: Path,
) -> None:
    """Unknown platform aliases should fail closed."""
    config = replace(
        _network_config(tmp_path),
        platform="mips64",
    )

    result = validate_calendar_toolchain_installer_config(config)

    assert result.valid is False
    assert any(
        issue.code is CalendarToolchainInstallFailureCode.UNSUPPORTED_PLATFORM
        for issue in result.issues
    )


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("khal_version", "0.11.5"),
        ("vdirsyncer_version", "0.19.4"),
    ),
)
def test_unsupported_tool_version_fails(
    tmp_path: Path,
    field_name: str,
    value: str,
) -> None:
    """Untested calendar-tool versions should fail closed."""
    config = _network_config(tmp_path)

    if field_name == "khal_version":
        config = replace(config, khal_version=value)
    else:
        config = replace(config, vdirsyncer_version=value)

    result = validate_calendar_toolchain_installer_config(config)

    assert result.valid is False
    assert any(
        issue.code is CalendarToolchainInstallFailureCode.UNSUPPORTED_VERSION
        and issue.field == field_name
        for issue in result.issues
    )


def test_missing_requirements_lock_fails(
    tmp_path: Path,
) -> None:
    """Managed installation should require the exact lock file."""
    config = _network_config(tmp_path)
    assert config.requirements_lock is not None
    config.requirements_lock.unlink()

    result = validate_calendar_toolchain_installer_config(config)

    assert result.valid is False
    assert any(
        issue.code is CalendarToolchainInstallFailureCode.ARTEFACT_MISSING
        and issue.field == "requirements_lock"
        for issue in result.issues
    )


def test_requirements_lock_checksum_mismatch_fails(
    tmp_path: Path,
) -> None:
    """Managed installation should verify the lock file before use."""
    config = replace(
        _network_config(tmp_path),
        expected_lock_sha256="b" * 64,
    )

    result = validate_calendar_toolchain_installer_config(config)

    assert result.valid is False
    assert any(
        issue.code is CalendarToolchainInstallFailureCode.CHECKSUM_MISMATCH
        and issue.field == "expected_lock_sha256"
        for issue in result.issues
    )


def test_wheelhouse_checksum_mismatch_fails(
    tmp_path: Path,
) -> None:
    """Offline installation should verify its wheelhouse archive."""
    config = replace(
        _bundled_config(tmp_path),
        expected_wheelhouse_sha256="b" * 64,
    )

    result = validate_calendar_toolchain_installer_config(config)

    assert result.valid is False
    assert any(
        issue.code is CalendarToolchainInstallFailureCode.CHECKSUM_MISMATCH
        and issue.field == "expected_wheelhouse_sha256"
        for issue in result.issues
    )


def test_invalid_package_index_fails(
    tmp_path: Path,
) -> None:
    """Online installation should require a safe explicit package index."""
    config = replace(
        _network_config(tmp_path),
        package_index_url="http://pypi.org/simple",
    )

    result = validate_calendar_toolchain_installer_config(config)

    assert result.valid is False
    assert any(issue.field == "package_index_url" for issue in result.issues)


def test_external_executable_must_exist(
    tmp_path: Path,
) -> None:
    """External mode should fail when either selected command disappears."""
    config = _external_config(tmp_path)
    assert config.external_khal_executable is not None
    config.external_khal_executable.unlink()

    result = validate_calendar_toolchain_installer_config(config)

    assert result.valid is False
    assert any(
        issue.code is CalendarToolchainInstallFailureCode.ARTEFACT_MISSING
        and issue.field == "external_khal_executable"
        for issue in result.issues
    )
