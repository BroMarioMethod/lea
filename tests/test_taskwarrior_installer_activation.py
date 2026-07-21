"""Tests for atomic Taskwarrior activation and record persistence."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lea.installers.taskwarrior import (
    TaskwarriorInstallationRecord,
    TaskwarriorInstallerConfig,
    TaskwarriorInstallFailureCode,
    TaskwarriorInstallMode,
    TaskwarriorStagedBinary,
    activate_staged_taskwarrior,
    render_taskwarrior_installation_record,
)

INSTALLED_AT = datetime(2026, 7, 21, 18, 30, tzinfo=UTC)


def make_staged_binary(
    tmp_path: Path,
    *,
    content: bytes = b"taskwarrior-binary",
) -> TaskwarriorStagedBinary:
    """Create one deterministic staged binary."""
    staging_root = tmp_path / "staging" / ".taskwarrior-test"
    executable = staging_root / "bin" / "task"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(content)
    executable.chmod(0o750)

    return TaskwarriorStagedBinary(
        staging_root=staging_root,
        executable=executable,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def make_config(tmp_path: Path) -> TaskwarriorInstallerConfig:
    """Create one deterministic installer configuration."""
    return TaskwarriorInstallerConfig(
        mode=TaskwarriorInstallMode.BUNDLED_BINARY,
        version="3.4.2",
        platform="linux-aarch64",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "install" / "taskwarrior.json",
        service_user="lea",
        service_group="lea",
        artefact_path=tmp_path / "source-task",
        expected_sha256="a" * 64,
    )


def test_render_installation_record_is_deterministic(
    tmp_path: Path,
) -> None:
    """Installation records should be stable and newline terminated."""
    record = TaskwarriorInstallationRecord(
        schema_version=1,
        component="taskwarrior",
        version="3.4.2",
        mode="bundled-binary",
        platform="linux-aarch64",
        executable=tmp_path / "tools" / "3.4.2" / "bin" / "task",
        sha256="a" * 64,
        taskrc=tmp_path / "config" / "taskrc",
        home=tmp_path / "state" / "home",
        data=tmp_path / "state" / "data",
        smoke_test="passed",
        installed_at=INSTALLED_AT,
    )

    document = render_taskwarrior_installation_record(record)
    payload = json.loads(document)

    assert document.endswith("\n")
    assert payload["installed_at"] == "2026-07-21T18:30:00Z"
    assert payload["schema_version"] == 1
    assert payload["executable"].endswith("/3.4.2/bin/task")


def test_activation_moves_staging_and_writes_record(
    tmp_path: Path,
) -> None:
    """Successful activation should move staging and persist metadata."""
    staged = make_staged_binary(tmp_path)
    config = make_config(tmp_path)

    result = activate_staged_taskwarrior(
        staged,
        config,
        clock=lambda: INSTALLED_AT,
    )

    final_executable = config.tools_root / config.version / "bin" / "task"

    assert result.success is True
    assert result.already_installed is False
    assert result.record is not None
    assert result.record.executable == final_executable
    assert final_executable.read_bytes() == b"taskwarrior-binary"
    assert not staged.staging_root.exists()
    assert config.installation_record.is_file()

    payload = json.loads(config.installation_record.read_text(encoding="utf-8"))
    assert payload["sha256"] == staged.sha256
    assert payload["platform"] == "linux-aarch64"


def test_activation_is_idempotent_for_matching_binary(
    tmp_path: Path,
) -> None:
    """A matching installed version should return already-installed."""
    config = make_config(tmp_path)
    final_executable = config.tools_root / config.version / "bin" / "task"
    final_executable.parent.mkdir(parents=True)
    final_executable.write_bytes(b"taskwarrior-binary")
    staged = make_staged_binary(tmp_path)

    result = activate_staged_taskwarrior(
        staged,
        config,
        clock=lambda: INSTALLED_AT,
    )

    assert result.success is True
    assert result.already_installed is True
    assert result.record is not None
    assert staged.staging_root.exists()


def test_activation_rejects_existing_checksum_mismatch(
    tmp_path: Path,
) -> None:
    """An existing version with different bytes must not be replaced."""
    config = make_config(tmp_path)
    final_executable = config.tools_root / config.version / "bin" / "task"
    final_executable.parent.mkdir(parents=True)
    final_executable.write_bytes(b"different")
    staged = make_staged_binary(tmp_path)

    result = activate_staged_taskwarrior(
        staged,
        config,
        clock=lambda: INSTALLED_AT,
    )

    assert result.success is False
    assert result.issues[0].code is TaskwarriorInstallFailureCode.ACTIVATION_FAILED
    assert final_executable.read_bytes() == b"different"
    assert staged.staging_root.exists()


def test_record_failure_rolls_back_new_installation(
    tmp_path: Path,
) -> None:
    """A record-write failure should remove only the new version."""
    staged = make_staged_binary(tmp_path)
    config = make_config(tmp_path)

    config.installation_record.parent.mkdir(parents=True)
    config.installation_record.parent.chmod(0o500)

    try:
        result = activate_staged_taskwarrior(
            staged,
            config,
            clock=lambda: INSTALLED_AT,
        )
    finally:
        config.installation_record.parent.chmod(0o700)

    final_root = config.tools_root / config.version

    if result.success:
        pytest.skip("The test process can bypass directory permissions.")

    assert result.issues[0].code is TaskwarriorInstallFailureCode.RECORD_FAILED
    assert not final_root.exists()


def test_record_requires_canonical_utc(
    tmp_path: Path,
) -> None:
    """Installation timestamps should remain canonical UTC."""
    with pytest.raises(
        ValueError,
        match="canonical UTC",
    ):
        TaskwarriorInstallationRecord(
            schema_version=1,
            component="taskwarrior",
            version="3.4.2",
            mode="bundled-binary",
            platform="linux-aarch64",
            executable=tmp_path / "task",
            sha256="a" * 64,
            taskrc=tmp_path / "taskrc",
            home=tmp_path / "home",
            data=tmp_path / "data",
            smoke_test="passed",
            installed_at=datetime.fromisoformat("2026-07-21T20:30:00+02:00"),
        )
