"""Tests for source-network checks in the source installer."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lea.installers.taskwarrior import (
    TaskwarriorInstallationRecord,
    TaskwarriorInstallerConfig,
    TaskwarriorInstallerIssue,
    TaskwarriorInstallFailureCode,
    TaskwarriorInstallMode,
    TaskwarriorSourceNetworkConfig,
    TaskwarriorSourceNetworkResult,
    calculate_sha256,
    install_source_taskwarrior,
    write_taskwarrior_installation_record,
)


def _config(tmp_path: Path) -> TaskwarriorInstallerConfig:
    """Return one isolated source-build configuration."""
    archive = tmp_path / "task-3.4.2.tar.gz"
    archive.write_bytes(b"source archive")

    return TaskwarriorInstallerConfig(
        mode=TaskwarriorInstallMode.SOURCE_BUILD,
        version="3.4.2",
        platform="arm64",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "install" / "taskwarrior.json",
        service_user="lea",
        service_group="lea",
        source_archive=archive,
        expected_sha256=hashlib.sha256(b"source archive").hexdigest(),
        build_directory=tmp_path / "build",
        build_concurrency=1,
    )


def test_network_failure_stops_before_dependency_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed network validation must stop before build dependencies."""
    config = _config(tmp_path)
    issue = TaskwarriorInstallerIssue(
        code=TaskwarriorInstallFailureCode.DEPENDENCY_MISSING,
        message="Verified source network unavailable.",
        field="network",
        path=tmp_path / "git",
    )
    dependency_called = False

    def validate_network(
        value: TaskwarriorSourceNetworkConfig,
        *,
        timeout_seconds: float,
    ) -> TaskwarriorSourceNetworkResult:
        return TaskwarriorSourceNetworkResult(
            valid=False,
            issues=(issue,),
        )

    def validate_dependencies(
        *args: object,
        **kwargs: object,
    ) -> object:
        nonlocal dependency_called
        dependency_called = True
        raise AssertionError("Dependency validation must not run.")

    monkeypatch.setattr(
        "lea.installers.taskwarrior.source_installer."
        "validate_taskwarrior_source_network",
        validate_network,
    )
    monkeypatch.setattr(
        "lea.installers.taskwarrior.source_installer."
        "validate_taskwarrior_build_dependencies",
        validate_dependencies,
    )

    result = install_source_taskwarrior(
        config,
        source_network=TaskwarriorSourceNetworkConfig(
            git=tmp_path / "git",
            ca_bundle=tmp_path / "ca.crt",
        ),
    )

    assert result.success is False
    assert result.issues == (issue,)
    assert dependency_called is False


def test_existing_installation_skips_network_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A matching installation must not require network access."""
    config = _config(tmp_path)
    executable = config.tools_root / config.version / "bin" / "task"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"installed task")

    record = TaskwarriorInstallationRecord(
        schema_version=1,
        component="taskwarrior",
        version=config.version,
        mode=TaskwarriorInstallMode.SOURCE_BUILD.value,
        platform="linux-aarch64",
        executable=executable,
        sha256=calculate_sha256(executable),
        taskrc=config.configuration_dir / "taskrc",
        home=config.state_root / "home",
        data=config.state_root / "data",
        smoke_test="passed",
        installed_at=datetime(2026, 7, 22, tzinfo=UTC),
    )

    assert (
        write_taskwarrior_installation_record(
            record,
            destination=config.installation_record,
        )
        == ()
    )

    def fail_network_check(
        *args: object,
        **kwargs: object,
    ) -> TaskwarriorSourceNetworkResult:
        raise AssertionError(
            "Network validation must not run for an existing installation."
        )

    monkeypatch.setattr(
        "lea.installers.taskwarrior.source_installer."
        "validate_taskwarrior_source_network",
        fail_network_check,
    )

    result = install_source_taskwarrior(config)

    assert result.success is True
    assert result.already_installed is True
    assert result.build is None
    assert result.record == record
