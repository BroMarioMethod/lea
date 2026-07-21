"""Tests for the pinned-source Taskwarrior installer."""

import hashlib
import stat
from datetime import UTC, datetime
from pathlib import Path

from lea.installers.taskwarrior import (
    TaskwarriorInstallationRecord,
    TaskwarriorInstallerConfig,
    TaskwarriorInstallMode,
    write_taskwarrior_installation_record,
)
from lea.installers.taskwarrior.source_installer import (
    TaskwarriorSourceInstallResult,
    install_source_taskwarrior,
)


def _executable(path: Path) -> Path:
    """Create one executable regular file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"taskwarrior-built")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _source_config(tmp_path: Path) -> TaskwarriorInstallerConfig:
    """Return one source-build configuration."""
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


def test_wrong_mode_is_rejected(tmp_path: Path) -> None:
    """The source installer should reject bundled mode."""
    artefact = tmp_path / "task"
    artefact.write_bytes(b"task")
    config = TaskwarriorInstallerConfig(
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

    result = install_source_taskwarrior(config)

    assert result.success is False
    assert result.record is None
    assert result.build is None


def test_existing_source_installation_skips_rebuild(tmp_path: Path) -> None:
    """A matching source installation should return immediately."""
    config = _source_config(tmp_path)
    executable = _executable(config.tools_root / config.version / "bin" / "task")
    sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
    record = TaskwarriorInstallationRecord(
        schema_version=1,
        component="taskwarrior",
        version="3.4.2",
        mode=TaskwarriorInstallMode.SOURCE_BUILD.value,
        platform="linux-aarch64",
        executable=executable,
        sha256=sha256,
        taskrc=config.configuration_dir / "taskrc",
        home=config.state_root / "home",
        data=config.state_root / "data",
        smoke_test="passed",
        installed_at=datetime(2026, 7, 22, 8, 0, tzinfo=UTC),
    )
    assert (
        write_taskwarrior_installation_record(
            record,
            destination=config.installation_record,
        )
        == ()
    )

    result = install_source_taskwarrior(config)

    assert result.success is True
    assert result.already_installed is True
    assert result.record == record
    assert result.build is None


def test_existing_other_mode_is_rejected(tmp_path: Path) -> None:
    """Idempotency must not reuse an installation from another mode."""
    config = _source_config(tmp_path)
    executable = _executable(config.tools_root / config.version / "bin" / "task")
    sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
    record = TaskwarriorInstallationRecord(
        schema_version=1,
        component="taskwarrior",
        version="3.4.2",
        mode=TaskwarriorInstallMode.BUNDLED_BINARY.value,
        platform="linux-aarch64",
        executable=executable,
        sha256=sha256,
        taskrc=config.configuration_dir / "taskrc",
        home=config.state_root / "home",
        data=config.state_root / "data",
        smoke_test="passed",
        installed_at=datetime(2026, 7, 22, 8, 0, tzinfo=UTC),
    )
    assert (
        write_taskwarrior_installation_record(
            record,
            destination=config.installation_record,
        )
        == ()
    )

    result = install_source_taskwarrior(config)

    assert result.success is False
    assert result.record is None
    assert result.issues


def test_success_result_requires_record() -> None:
    """Successful source-install results must contain a record."""
    try:
        TaskwarriorSourceInstallResult(
            success=True,
            already_installed=False,
            record=None,
            build=None,
            issues=(),
        )
    except ValueError as error:
        assert "must contain a record" in str(error)
    else:
        raise AssertionError("Expected invalid success result rejection.")
