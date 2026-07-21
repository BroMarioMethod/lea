"""Tests for the external Taskwarrior installer."""

import hashlib
import stat
from pathlib import Path

from lea.installers.taskwarrior import (
    TaskwarriorInstallerConfig,
    TaskwarriorInstallMode,
    install_external_taskwarrior,
)


def make_executable(tmp_path: Path) -> Path:
    """Create one real executable that reports an unsupported lifecycle."""
    executable = tmp_path / "bin" / "task"
    executable.parent.mkdir(parents=True)
    executable.write_text(
        "#!/bin/sh\nprintf '%s\\n' '3.4.2'\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def make_config(
    tmp_path: Path,
    executable: Path,
) -> TaskwarriorInstallerConfig:
    """Return one external-executable installer configuration."""
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


def test_external_installer_rejects_wrong_mode(
    tmp_path: Path,
) -> None:
    """External installation should reject bundled mode."""
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

    result = install_external_taskwarrior(config)

    assert result.success is False
    assert result.record is None


def test_external_installer_requires_full_lifecycle(
    tmp_path: Path,
) -> None:
    """A version-only executable must fail the lifecycle smoke test."""
    executable = make_executable(tmp_path)
    config = make_config(tmp_path, executable)

    result = install_external_taskwarrior(config)

    assert result.success is False
    assert result.record is None
    assert result.issues
    assert not config.installation_record.exists()
