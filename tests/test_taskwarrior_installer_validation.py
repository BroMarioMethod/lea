"""Tests for Taskwarrior installer validation."""

import stat
from pathlib import Path
from typing import TypedDict

from lea.installers.taskwarrior import (
    TaskwarriorInstallerConfig,
    TaskwarriorInstallFailureCode,
    TaskwarriorInstallMode,
    is_supported_taskwarrior_version,
    is_valid_sha256,
    normalise_taskwarrior_platform,
    validate_external_executable_path,
    validate_taskwarrior_installer_config,
)

SHA256 = "b" * 64


class CommonInstallerArguments(TypedDict):
    """Common required Taskwarrior installer arguments."""

    version: str
    platform: str
    tools_root: Path
    configuration_dir: Path
    state_root: Path
    installation_record: Path
    service_user: str
    service_group: str


def common_kwargs(tmp_path: Path) -> CommonInstallerArguments:
    """Return common valid installer arguments."""
    return {
        "version": "3.4.2",
        "platform": "arm64",
        "tools_root": tmp_path / "tools",
        "configuration_dir": tmp_path / "config",
        "state_root": tmp_path / "state",
        "installation_record": tmp_path / "install.json",
        "service_user": "lea",
        "service_group": "lea",
    }


def test_platform_aliases_are_normalised() -> None:
    """Common Debian and kernel architecture names should map canonically."""
    assert normalise_taskwarrior_platform("arm64") == "linux-aarch64"
    assert normalise_taskwarrior_platform("aarch64") == "linux-aarch64"
    assert normalise_taskwarrior_platform("amd64") == "linux-x86_64"
    assert normalise_taskwarrior_platform("x86_64") == "linux-x86_64"
    assert normalise_taskwarrior_platform("mips64") is None


def test_version_policy_accepts_only_3_4_x() -> None:
    """Milestone 2.2 should accept only Taskwarrior 3.4.x."""
    assert is_supported_taskwarrior_version("3.4.2") is True
    assert is_supported_taskwarrior_version("3.4.99") is True
    assert is_supported_taskwarrior_version("3.5.0") is False
    assert is_supported_taskwarrior_version("2.6.2") is False


def test_sha256_requires_lower_case_hex() -> None:
    """Checksums should use deterministic lower-case hexadecimal text."""
    assert is_valid_sha256("a" * 64) is True
    assert is_valid_sha256("A" * 64) is False
    assert is_valid_sha256("a" * 63) is False
    assert is_valid_sha256("g" * 64) is False


def test_external_executable_validation(
    tmp_path: Path,
) -> None:
    """External executable validation should inspect existence and mode."""
    executable = tmp_path / "task"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")

    issues = validate_external_executable_path(executable)

    assert len(issues) == 1
    assert issues[0].code is TaskwarriorInstallFailureCode.PERMISSION_DENIED

    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

    assert validate_external_executable_path(executable) == ()


def test_valid_config_is_normalised(
    tmp_path: Path,
) -> None:
    """Validated configuration should contain canonical values."""
    artefact = tmp_path / "task"
    artefact.write_text("binary", encoding="utf-8")

    config = TaskwarriorInstallerConfig(
        mode=TaskwarriorInstallMode.BUNDLED_BINARY,
        artefact_path=artefact,
        expected_sha256=SHA256,
        **common_kwargs(tmp_path),
    )

    result = validate_taskwarrior_installer_config(config)

    assert result.valid is True
    assert result.config is not None
    assert result.config.platform == "linux-aarch64"
    assert result.config.version == "3.4.2"
    assert result.issues == ()


def test_unsupported_platform_fails(
    tmp_path: Path,
) -> None:
    """Unknown platform aliases should fail closed."""
    config = TaskwarriorInstallerConfig(
        mode=TaskwarriorInstallMode.BUNDLED_BINARY,
        version="3.4.2",
        platform="mips64",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "install.json",
        service_user="lea",
        service_group="lea",
        artefact_path=tmp_path / "task",
        expected_sha256=SHA256,
    )

    result = validate_taskwarrior_installer_config(config)

    assert result.valid is False
    assert result.issues[0].code is TaskwarriorInstallFailureCode.UNSUPPORTED_PLATFORM


def test_invalid_checksum_fails(
    tmp_path: Path,
) -> None:
    """Invalid checksum syntax should fail before installation."""
    config = TaskwarriorInstallerConfig(
        mode=TaskwarriorInstallMode.BUNDLED_BINARY,
        artefact_path=tmp_path / "task",
        expected_sha256="not-a-checksum",
        **common_kwargs(tmp_path),
    )

    result = validate_taskwarrior_installer_config(config)

    assert result.valid is False
    assert result.issues[0].field == "expected_sha256"
