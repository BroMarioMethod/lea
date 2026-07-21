"""Tests for Taskwarrior installer preflight checks."""

import hashlib
import os
from pathlib import Path

import pytest

from lea.installers.taskwarrior import (
    TaskwarriorInstallerConfig,
    TaskwarriorInstallFailureCode,
    TaskwarriorInstallMode,
    calculate_sha256,
    check_directory_parent_writable,
    run_taskwarrior_installer_preflight,
    verify_expected_sha256,
)


def make_config(
    tmp_path: Path,
    *,
    artefact_path: Path,
    expected_sha256: str,
) -> TaskwarriorInstallerConfig:
    """Return one valid bundled-binary installer configuration."""
    return TaskwarriorInstallerConfig(
        mode=TaskwarriorInstallMode.BUNDLED_BINARY,
        version="3.4.2",
        platform="linux-aarch64",
        tools_root=tmp_path / "install" / "tools",
        configuration_dir=tmp_path / "install" / "config",
        state_root=tmp_path / "install" / "state",
        installation_record=tmp_path / "install" / "record.json",
        service_user="lea",
        service_group="lea",
        artefact_path=artefact_path,
        expected_sha256=expected_sha256,
    )


def test_calculate_sha256(
    tmp_path: Path,
) -> None:
    """Checksum calculation should match hashlib."""
    artefact = tmp_path / "task"
    artefact.write_bytes(b"taskwarrior")

    assert calculate_sha256(artefact) == hashlib.sha256(b"taskwarrior").hexdigest()


def test_calculate_sha256_requires_absolute_path() -> None:
    """Checksum calculation should reject ambiguous paths."""
    with pytest.raises(
        ValueError,
        match="path must be absolute",
    ):
        calculate_sha256(Path("task"))


def test_verify_expected_sha256_succeeds(
    tmp_path: Path,
) -> None:
    """Matching artefact checksums should pass."""
    artefact = tmp_path / "task"
    artefact.write_bytes(b"taskwarrior")
    expected = hashlib.sha256(b"taskwarrior").hexdigest()

    assert verify_expected_sha256(artefact, expected) == ()


def test_verify_expected_sha256_reports_mismatch(
    tmp_path: Path,
) -> None:
    """Checksum mismatches should fail closed."""
    artefact = tmp_path / "task"
    artefact.write_bytes(b"taskwarrior")

    issues = verify_expected_sha256(
        artefact,
        "0" * 64,
    )

    assert len(issues) == 1
    assert issues[0].code is TaskwarriorInstallFailureCode.CHECKSUM_MISMATCH
    assert issues[0].path == artefact


def test_verify_expected_sha256_reports_missing_artefact(
    tmp_path: Path,
) -> None:
    """Missing artefacts should return a structured issue."""
    artefact = tmp_path / "missing-task"

    issues = verify_expected_sha256(
        artefact,
        "0" * 64,
    )

    assert len(issues) == 1
    assert issues[0].code is TaskwarriorInstallFailureCode.ARTEFACT_MISSING


def test_parent_writable_check_accepts_creatable_path(
    tmp_path: Path,
) -> None:
    """A missing destination beneath a writable parent should pass."""
    destination = tmp_path / "new" / "nested"

    assert (
        check_directory_parent_writable(
            destination,
            field_name="tools_root",
        )
        == ()
    )


def test_parent_writable_check_reports_non_directory_parent(
    tmp_path: Path,
) -> None:
    """A file blocking the destination path should fail."""
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")

    issues = check_directory_parent_writable(
        blocker / "nested",
        field_name="state_root",
    )

    assert len(issues) == 1
    assert issues[0].code is TaskwarriorInstallFailureCode.INVALID_ARGUMENT


def test_parent_writable_check_reports_permission_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unwritable parent should return a permission issue."""
    destination = tmp_path / "new"

    original_access = os.access

    def deny_access(
        path: os.PathLike[str] | str,
        mode: int,
    ) -> bool:
        if Path(path) == tmp_path:
            return False

        return original_access(path, mode)

    monkeypatch.setattr(os, "access", deny_access)

    issues = check_directory_parent_writable(
        destination,
        field_name="configuration_dir",
    )

    assert len(issues) == 1
    assert issues[0].code is TaskwarriorInstallFailureCode.PERMISSION_DENIED


def test_preflight_combines_destination_and_checksum_checks(
    tmp_path: Path,
) -> None:
    """Preflight should collect all non-destructive issues."""
    artefact = tmp_path / "task"
    artefact.write_bytes(b"taskwarrior")
    config = make_config(
        tmp_path,
        artefact_path=artefact,
        expected_sha256="0" * 64,
    )

    issues = run_taskwarrior_installer_preflight(config)

    assert len(issues) == 1
    assert issues[0].code is TaskwarriorInstallFailureCode.CHECKSUM_MISMATCH


def test_preflight_succeeds_for_valid_bundle(
    tmp_path: Path,
) -> None:
    """A valid bundle and writable destinations should pass."""
    artefact = tmp_path / "task"
    artefact.write_bytes(b"taskwarrior")
    expected = hashlib.sha256(b"taskwarrior").hexdigest()
    config = make_config(
        tmp_path,
        artefact_path=artefact,
        expected_sha256=expected,
    )

    assert run_taskwarrior_installer_preflight(config) == ()
