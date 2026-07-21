"""Real Taskwarrior bundled-installer integration tests."""

import hashlib
import os
from pathlib import Path

import pytest

from lea.adapters.taskwarrior import (
    TaskwarriorCliProvider,
    TaskwarriorConfig,
)
from lea.installers.taskwarrior import (
    TaskwarriorInstallerConfig,
    TaskwarriorInstallMode,
    install_bundled_taskwarrior,
    read_taskwarrior_installation_record,
)

_DEFAULT_EXECUTABLE = Path("/opt/lea-tools/taskwarrior/3.4.2/bin/task")


def _taskwarrior_executable() -> Path:
    """Return the configured real Taskwarrior executable."""
    configured = os.environ.get("LEA_TEST_TASKWARRIOR_EXECUTABLE")
    return Path(configured) if configured is not None else _DEFAULT_EXECUTABLE


def _require_real_taskwarrior() -> Path:
    """Skip when the real Taskwarrior binary is unavailable."""
    executable = _taskwarrior_executable()

    if not executable.is_file():
        pytest.skip(f"Taskwarrior executable not found: {executable}")

    if not os.access(executable, os.X_OK):
        pytest.skip(f"Taskwarrior executable is not executable: {executable}")

    return executable


def _installer_config(
    tmp_path: Path,
    *,
    artefact: Path,
) -> TaskwarriorInstallerConfig:
    """Return one isolated bundled-installer configuration."""
    return TaskwarriorInstallerConfig(
        mode=TaskwarriorInstallMode.BUNDLED_BINARY,
        version="3.4.2",
        platform="arm64",
        tools_root=tmp_path / "lea-tools" / "taskwarrior",
        configuration_dir=(tmp_path / "etc" / "lea" / "taskwarrior"),
        state_root=(tmp_path / "var" / "lib" / "lea" / "taskwarrior"),
        installation_record=(
            tmp_path / "var" / "lib" / "lea" / "install" / "taskwarrior.json"
        ),
        service_user="lea",
        service_group="lea",
        artefact_path=artefact,
        expected_sha256=_sha256(artefact),
    )


def _sha256(path: Path) -> str:
    """Return one file's SHA-256 digest."""
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for chunk in iter(
            lambda: stream.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def test_real_bundled_installer_end_to_end(
    tmp_path: Path,
) -> None:
    """Install and inspect a real isolated Taskwarrior binary."""
    source = _require_real_taskwarrior()
    source_checksum = _sha256(source)
    config = _installer_config(
        tmp_path,
        artefact=source,
    )

    result = install_bundled_taskwarrior(
        config,
        fsync=True,
    )

    assert result.success is True
    assert result.already_installed is False
    assert result.record is not None
    assert result.record.version == "3.4.2"
    assert result.record.platform == "linux-aarch64"
    assert result.record.sha256 == source_checksum
    assert result.record.executable.is_file()
    assert os.access(result.record.executable, os.X_OK)
    assert _sha256(result.record.executable) == source_checksum

    persisted, issues = read_taskwarrior_installation_record(config.installation_record)

    assert issues == ()
    assert persisted == result.record

    working_dir = tmp_path / "installed-working"
    working_dir.mkdir()

    provider = TaskwarriorCliProvider(
        TaskwarriorConfig(
            executable=result.record.executable,
            taskrc=result.record.taskrc,
            data_dir=result.record.data,
            home_dir=result.record.home,
            working_dir=working_dir,
            timeout_seconds=10.0,
        )
    )
    inspection = provider.inspect()

    assert inspection.available is True
    assert inspection.version == "3.4.2"
    assert inspection.issues == ()

    assert _sha256(source) == source_checksum


def test_real_bundled_installer_is_idempotent(
    tmp_path: Path,
) -> None:
    """A second real installation should reuse the persisted record."""
    source = _require_real_taskwarrior()
    config = _installer_config(
        tmp_path,
        artefact=source,
    )

    first = install_bundled_taskwarrior(
        config,
        fsync=True,
    )
    second = install_bundled_taskwarrior(
        config,
        fsync=True,
    )

    assert first.success is True
    assert first.already_installed is False
    assert first.record is not None

    assert second.success is True
    assert second.already_installed is True
    assert second.record == first.record
    assert second.issues == ()

    staged_directories = tuple(config.tools_root.glob(".taskwarrior-*"))
    assert staged_directories == ()
