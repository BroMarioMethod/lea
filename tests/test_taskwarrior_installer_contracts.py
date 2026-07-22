"""Tests for immutable Taskwarrior installer contracts."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import TypedDict

import pytest

from lea.installers.taskwarrior import (
    TaskwarriorInstallerConfig,
    TaskwarriorInstallerIssue,
    TaskwarriorInstallerValidationResult,
    TaskwarriorInstallFailureCode,
    TaskwarriorInstallMode,
)

SHA256 = "a" * 64


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
        "platform": "linux-aarch64",
        "tools_root": tmp_path / "tools",
        "configuration_dir": tmp_path / "config",
        "state_root": tmp_path / "state",
        "installation_record": tmp_path / "install.json",
        "service_user": "lea",
        "service_group": "lea",
    }


def test_bundled_binary_config_is_immutable(
    tmp_path: Path,
) -> None:
    """Bundled-binary configuration should be frozen."""
    config = TaskwarriorInstallerConfig(
        mode=TaskwarriorInstallMode.BUNDLED_BINARY,
        artefact_path=tmp_path / "task",
        expected_sha256=SHA256,
        **common_kwargs(tmp_path),
    )

    with pytest.raises(FrozenInstanceError):
        config.version = "3.4.3"  # type: ignore[misc]


def test_bundled_binary_requires_artefact(
    tmp_path: Path,
) -> None:
    """Bundled-binary mode should require an artefact path."""
    with pytest.raises(
        ValueError,
        match="artefact_path is required",
    ):
        TaskwarriorInstallerConfig(
            mode=TaskwarriorInstallMode.BUNDLED_BINARY,
            expected_sha256=SHA256,
            **common_kwargs(tmp_path),
        )


def test_source_build_requires_archive_and_build_directory(
    tmp_path: Path,
) -> None:
    """Source-build mode should require explicit build inputs."""
    with pytest.raises(
        ValueError,
        match="source_archive is required",
    ):
        TaskwarriorInstallerConfig(
            mode=TaskwarriorInstallMode.SOURCE_BUILD,
            build_directory=tmp_path / "build",
            expected_sha256=SHA256,
            **common_kwargs(tmp_path),
        )


def test_external_mode_rejects_checksum(
    tmp_path: Path,
) -> None:
    """External mode should not accept bundled artefact checksums."""
    with pytest.raises(
        ValueError,
        match="expected_sha256 must not be set",
    ):
        TaskwarriorInstallerConfig(
            mode=TaskwarriorInstallMode.EXTERNAL_EXECUTABLE,
            external_executable=tmp_path / "task",
            expected_sha256=SHA256,
            **common_kwargs(tmp_path),
        )


def test_paths_must_be_absolute() -> None:
    """Persisted installer paths should be absolute."""
    with pytest.raises(
        ValueError,
        match="tools_root must be an absolute path",
    ):
        TaskwarriorInstallerConfig(
            mode=TaskwarriorInstallMode.BUNDLED_BINARY,
            version="3.4.2",
            platform="linux-aarch64",
            tools_root=Path("tools"),
            configuration_dir=Path("/tmp/config"),
            state_root=Path("/tmp/state"),
            installation_record=Path("/tmp/install.json"),
            service_user="lea",
            service_group="lea",
            artefact_path=Path("/tmp/task"),
            expected_sha256=SHA256,
        )


def test_issue_requires_absolute_path() -> None:
    """Structured issue paths should remain unambiguous."""
    with pytest.raises(
        ValueError,
        match="path must be absolute",
    ):
        TaskwarriorInstallerIssue(
            code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
            message="Invalid.",
            path=Path("relative"),
        )


def test_validation_result_consistency(
    tmp_path: Path,
) -> None:
    """Validation results should not mix success and failure data."""
    config = TaskwarriorInstallerConfig(
        mode=TaskwarriorInstallMode.BUNDLED_BINARY,
        artefact_path=tmp_path / "task",
        expected_sha256=SHA256,
        **common_kwargs(tmp_path),
    )

    valid = TaskwarriorInstallerValidationResult(
        valid=True,
        config=config,
        issues=(),
    )

    invalid = TaskwarriorInstallerValidationResult(
        valid=False,
        config=None,
        issues=(
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
                message="Invalid.",
            ),
        ),
    )

    assert valid.config == config
    assert invalid.config is None
