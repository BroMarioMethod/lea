"""Real external Taskwarrior installer integration tests."""

import os
from pathlib import Path

import pytest

from lea.installers.taskwarrior import (
    TaskwarriorInstallerConfig,
    TaskwarriorInstallMode,
    install_external_taskwarrior,
)

_DEFAULT_EXECUTABLE = Path("/opt/lea-tools/taskwarrior/3.4.2/bin/task")


def _require_real_taskwarrior() -> Path:
    """Return the real executable or skip when unavailable."""
    configured = os.environ.get("LEA_TEST_TASKWARRIOR_EXECUTABLE")
    executable = Path(configured) if configured is not None else _DEFAULT_EXECUTABLE

    try:
        available = executable.is_file() and os.access(executable, os.X_OK)
    except OSError:
        available = False

    if not available:
        pytest.skip(f"Taskwarrior executable unavailable: {executable}")

    return executable


def test_real_external_installer_is_idempotent(
    tmp_path: Path,
) -> None:
    """Validate and register one exact external Taskwarrior executable."""
    executable = _require_real_taskwarrior()
    config = TaskwarriorInstallerConfig(
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

    first = install_external_taskwarrior(
        config,
        fsync=True,
    )
    second = install_external_taskwarrior(
        config,
        fsync=True,
    )

    assert first.success is True
    assert first.already_installed is False
    assert first.record is not None
    assert first.record.executable == executable

    assert second.success is True
    assert second.already_installed is True
    assert second.record == first.record
