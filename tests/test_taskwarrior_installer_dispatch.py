"""Tests for mode-based Taskwarrior installer dispatch."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lea.installers.taskwarrior import (
    TaskwarriorBundledInstallResult,
    TaskwarriorExternalInstallResult,
    TaskwarriorInstallationRecord,
    TaskwarriorInstallerConfig,
    TaskwarriorInstallMode,
    TaskwarriorSourceInstallResult,
)
from lea.installers.taskwarrior.dispatch import (
    TaskwarriorInstallResult,
    install_taskwarrior,
)


def _record(
    config: TaskwarriorInstallerConfig,
) -> TaskwarriorInstallationRecord:
    """Return one deterministic installation record."""
    return TaskwarriorInstallationRecord(
        schema_version=1,
        component="taskwarrior",
        version=config.version,
        mode=config.mode.value,
        platform="linux-aarch64",
        executable=config.tools_root / config.version / "bin" / "task",
        sha256="a" * 64,
        taskrc=config.configuration_dir / "taskrc",
        home=config.state_root / "home",
        data=config.state_root / "data",
        smoke_test="passed",
        installed_at=datetime(2026, 7, 22, tzinfo=UTC),
    )


def _bundled_config(tmp_path: Path) -> TaskwarriorInstallerConfig:
    """Return one bundled-binary configuration."""
    artefact = tmp_path / "task"
    artefact.write_bytes(b"task")

    return TaskwarriorInstallerConfig(
        mode=TaskwarriorInstallMode.BUNDLED_BINARY,
        version="3.4.2",
        platform="arm64",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "install" / "taskwarrior.json",
        service_user="lea",
        service_group="lea",
        artefact_path=artefact,
        expected_sha256=hashlib.sha256(b"task").hexdigest(),
    )


def _source_config(tmp_path: Path) -> TaskwarriorInstallerConfig:
    """Return one source-build configuration."""
    archive = tmp_path / "task.tar.gz"
    archive.write_bytes(b"source")

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
        expected_sha256=hashlib.sha256(b"source").hexdigest(),
        build_directory=tmp_path / "build",
        build_concurrency=1,
    )


def _external_config(tmp_path: Path) -> TaskwarriorInstallerConfig:
    """Return one external-executable configuration."""
    executable = tmp_path / "task"
    executable.write_bytes(b"task")

    return TaskwarriorInstallerConfig(
        mode=TaskwarriorInstallMode.EXTERNAL_EXECUTABLE,
        version="3.4.2",
        platform="arm64",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "install" / "taskwarrior.json",
        service_user="lea",
        service_group="lea",
        external_executable=executable,
    )


def test_dispatches_bundled_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bundled mode should call only the bundled installer."""
    config = _bundled_config(tmp_path)
    record = _record(config)

    def selected(
        value: TaskwarriorInstallerConfig,
        *,
        fsync: bool,
    ) -> TaskwarriorBundledInstallResult:
        assert value is config
        assert fsync is True
        return TaskwarriorBundledInstallResult(
            success=True,
            already_installed=False,
            record=record,
            issues=(),
        )

    monkeypatch.setattr(
        "lea.installers.taskwarrior.dispatch.install_bundled_taskwarrior",
        selected,
    )

    result = install_taskwarrior(config, fsync=True)

    assert result.record == record
    assert result.success is True


def test_dispatches_source_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source mode should call only the source installer."""
    config = _source_config(tmp_path)
    record = _record(config)

    def selected(
        value: TaskwarriorInstallerConfig,
        *,
        fsync: bool,
        progress: object | None,
    ) -> TaskwarriorSourceInstallResult:
        assert value is config
        assert fsync is True
        assert progress is None
        return TaskwarriorSourceInstallResult(
            success=True,
            already_installed=False,
            record=record,
            build=None,
            issues=(),
        )

    monkeypatch.setattr(
        "lea.installers.taskwarrior.dispatch.install_source_taskwarrior",
        selected,
    )

    result = install_taskwarrior(config, fsync=True)

    assert result.record == record
    assert result.success is True


def test_dispatches_external_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """External mode should call only the external installer."""
    config = _external_config(tmp_path)
    record = _record(config)

    def selected(
        value: TaskwarriorInstallerConfig,
        *,
        fsync: bool,
    ) -> TaskwarriorExternalInstallResult:
        assert value is config
        assert fsync is True
        return TaskwarriorExternalInstallResult(
            success=True,
            already_installed=False,
            record=record,
            issues=(),
        )

    monkeypatch.setattr(
        "lea.installers.taskwarrior.dispatch.install_external_taskwarrior",
        selected,
    )

    result = install_taskwarrior(config, fsync=True)

    assert result.record == record
    assert result.success is True


def test_generic_success_requires_record() -> None:
    """A successful generic result must contain a record."""
    with pytest.raises(
        ValueError,
        match="must contain a record",
    ):
        TaskwarriorInstallResult(
            success=True,
            already_installed=False,
            record=None,
            issues=(),
        )
