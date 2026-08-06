"""Tests for calendar toolchain installer preflight checks."""

import hashlib
import os
import stat
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from lea.installers.calendar import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
    calculate_calendar_sha256,
    check_calendar_directory_parent_writable,
    run_calendar_toolchain_installer_preflight,
    verify_calendar_sha256,
)


def _write_file(
    path: Path,
    payload: bytes,
) -> str:
    """Write one file and return its SHA-256 digest."""
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _make_executable(path: Path) -> None:
    """Create one executable test script."""
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _network_config(
    tmp_path: Path,
) -> CalendarToolchainInstallerConfig:
    """Return one valid verified-network configuration."""
    uv_executable = tmp_path / "uv"
    python_executable = tmp_path / "python3"
    requirements_lock = tmp_path / "calendar-requirements.txt"

    _make_executable(uv_executable)
    _make_executable(python_executable)
    lock_sha256 = _write_file(
        requirements_lock,
        b"khal==0.11.4\nvdirsyncer==0.19.3\n",
    )

    return CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.VERIFIED_NETWORK,
        toolchain_version="1",
        khal_version="0.11.4",
        vdirsyncer_version="0.19.3",
        platform="linux-aarch64",
        tools_root=tmp_path / "install" / "tools",
        configuration_dir=tmp_path / "install" / "config",
        state_root=tmp_path / "install" / "state",
        installation_record=tmp_path / "install" / "record.json",
        service_user="lea",
        service_group="lea",
        uv_executable=uv_executable,
        python_executable=python_executable,
        requirements_lock=requirements_lock,
        expected_lock_sha256=lock_sha256,
        package_index_url="https://pypi.org/simple",
    )


def _bundled_config(
    tmp_path: Path,
) -> CalendarToolchainInstallerConfig:
    """Return one valid bundled-wheelhouse configuration."""
    archive = tmp_path / "calendar-wheelhouse.tar.gz"
    archive_sha256 = _write_file(
        archive,
        b"verified wheelhouse",
    )

    return replace(
        _network_config(tmp_path),
        mode=CalendarToolchainInstallMode.BUNDLED_WHEELHOUSE,
        package_index_url=None,
        wheelhouse_archive=archive,
        expected_wheelhouse_sha256=archive_sha256,
    )


def _external_config(
    tmp_path: Path,
) -> CalendarToolchainInstallerConfig:
    """Return one valid external-executables configuration."""
    khal_executable = tmp_path / "khal"
    vdirsyncer_executable = tmp_path / "vdirsyncer"
    _make_executable(khal_executable)
    _make_executable(vdirsyncer_executable)

    return CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES,
        toolchain_version="external-1",
        khal_version="0.11.4",
        vdirsyncer_version="0.19.3",
        platform="linux-aarch64",
        tools_root=tmp_path / "install" / "tools",
        configuration_dir=tmp_path / "install" / "config",
        state_root=tmp_path / "install" / "state",
        installation_record=tmp_path / "install" / "record.json",
        service_user="lea",
        service_group="lea",
        external_khal_executable=khal_executable,
        external_vdirsyncer_executable=vdirsyncer_executable,
    )


def test_calculate_calendar_sha256(
    tmp_path: Path,
) -> None:
    """Checksum calculation should match hashlib."""
    artefact = tmp_path / "calendar.lock"
    artefact.write_bytes(b"calendar")

    assert (
        calculate_calendar_sha256(artefact) == hashlib.sha256(b"calendar").hexdigest()
    )


def test_calculate_calendar_sha256_requires_absolute_path() -> None:
    """Checksum calculation should reject ambiguous paths."""
    with pytest.raises(
        ValueError,
        match="path must be absolute",
    ):
        calculate_calendar_sha256(Path("calendar.lock"))


def test_verify_calendar_sha256_succeeds(
    tmp_path: Path,
) -> None:
    """Matching artefact checksums should pass."""
    artefact = tmp_path / "calendar.lock"
    expected = _write_file(artefact, b"calendar")

    assert (
        verify_calendar_sha256(
            artefact,
            expected,
            field_name="requirements_lock",
            checksum_field="expected_lock_sha256",
            artefact_name="calendar requirements lock",
        )
        == ()
    )


def test_verify_calendar_sha256_reports_mismatch(
    tmp_path: Path,
) -> None:
    """Checksum mismatches should fail closed."""
    artefact = tmp_path / "calendar.lock"
    artefact.write_bytes(b"calendar")

    issues = verify_calendar_sha256(
        artefact,
        "0" * 64,
        field_name="requirements_lock",
        checksum_field="expected_lock_sha256",
        artefact_name="calendar requirements lock",
    )

    assert len(issues) == 1
    assert issues[0].code is CalendarToolchainInstallFailureCode.CHECKSUM_MISMATCH
    assert issues[0].path == artefact


def test_verify_calendar_sha256_reports_missing_artefact(
    tmp_path: Path,
) -> None:
    """Missing artefacts should return a structured issue."""
    artefact = tmp_path / "missing.lock"

    issues = verify_calendar_sha256(
        artefact,
        "0" * 64,
        field_name="requirements_lock",
        checksum_field="expected_lock_sha256",
        artefact_name="calendar requirements lock",
    )

    assert len(issues) == 1
    assert issues[0].code is CalendarToolchainInstallFailureCode.ARTEFACT_MISSING


def test_verify_calendar_sha256_rejects_symbolic_link(
    tmp_path: Path,
) -> None:
    """Installer artefacts should not be accepted through symbolic links."""
    target = tmp_path / "target.lock"
    link = tmp_path / "calendar.lock"
    expected = _write_file(target, b"calendar")
    link.symlink_to(target)

    issues = verify_calendar_sha256(
        link,
        expected,
        field_name="requirements_lock",
        checksum_field="expected_lock_sha256",
        artefact_name="calendar requirements lock",
    )

    assert len(issues) == 1
    assert issues[0].code is CalendarToolchainInstallFailureCode.INVALID_ARGUMENT


def test_parent_writable_check_accepts_creatable_path(
    tmp_path: Path,
) -> None:
    """A missing destination beneath a writable parent should pass."""
    destination = tmp_path / "new" / "nested"

    assert (
        check_calendar_directory_parent_writable(
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

    issues = check_calendar_directory_parent_writable(
        blocker / "nested",
        field_name="state_root",
    )

    assert len(issues) == 1
    assert issues[0].code is CalendarToolchainInstallFailureCode.INVALID_ARGUMENT


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

    issues = check_calendar_directory_parent_writable(
        destination,
        field_name="configuration_dir",
    )

    assert len(issues) == 1
    assert issues[0].code is CalendarToolchainInstallFailureCode.PERMISSION_DENIED


def test_parent_writable_check_accepts_existing_record(
    tmp_path: Path,
) -> None:
    """An existing record should use its writable parent directory."""
    destination = tmp_path / "install" / "calendar.json"
    destination.parent.mkdir()
    destination.write_text("{}\n", encoding="utf-8")

    assert (
        check_calendar_directory_parent_writable(
            destination,
            field_name="installation_record",
        )
        == ()
    )


@pytest.mark.parametrize(
    "config_factory",
    (
        _network_config,
        _bundled_config,
        _external_config,
    ),
)
def test_preflight_succeeds_for_supported_modes(
    tmp_path: Path,
    config_factory: Callable[[Path], CalendarToolchainInstallerConfig],
) -> None:
    """Valid volatile filesystem state should pass in every mode."""
    config = config_factory(tmp_path)

    assert run_calendar_toolchain_installer_preflight(config) == ()


def test_preflight_detects_requirements_lock_change(
    tmp_path: Path,
) -> None:
    """Preflight should detect a lock file changed after validation."""
    config = _network_config(tmp_path)
    assert config.requirements_lock is not None
    config.requirements_lock.write_text(
        "changed\n",
        encoding="utf-8",
    )

    issues = run_calendar_toolchain_installer_preflight(config)

    assert any(
        issue.code is CalendarToolchainInstallFailureCode.CHECKSUM_MISMATCH
        and issue.field == "expected_lock_sha256"
        for issue in issues
    )


def test_preflight_detects_wheelhouse_change(
    tmp_path: Path,
) -> None:
    """Offline preflight should detect a changed wheelhouse archive."""
    config = _bundled_config(tmp_path)
    assert config.wheelhouse_archive is not None
    config.wheelhouse_archive.write_bytes(b"changed")

    issues = run_calendar_toolchain_installer_preflight(config)

    assert any(
        issue.code is CalendarToolchainInstallFailureCode.CHECKSUM_MISMATCH
        and issue.field == "expected_wheelhouse_sha256"
        for issue in issues
    )


def test_preflight_detects_missing_managed_executable(
    tmp_path: Path,
) -> None:
    """Managed preflight should recheck the exact uv executable."""
    config = _network_config(tmp_path)
    assert config.uv_executable is not None
    config.uv_executable.unlink()

    issues = run_calendar_toolchain_installer_preflight(config)

    assert any(
        issue.code is CalendarToolchainInstallFailureCode.ARTEFACT_MISSING
        and issue.field == "uv_executable"
        for issue in issues
    )


def test_preflight_detects_non_executable_external_tool(
    tmp_path: Path,
) -> None:
    """External preflight should recheck both selected commands."""
    config = _external_config(tmp_path)
    executable = config.external_vdirsyncer_executable
    assert executable is not None
    executable.chmod(executable.stat().st_mode & ~0o111)

    issues = run_calendar_toolchain_installer_preflight(config)

    assert any(
        issue.code is CalendarToolchainInstallFailureCode.PERMISSION_DENIED
        and issue.field == "external_vdirsyncer_executable"
        for issue in issues
    )
