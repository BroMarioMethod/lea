"""Tests for tightly scoped calendar activation rollback."""

import hashlib
import stat
from pathlib import Path

from lea.installers.calendar import (
    CalendarToolchainActivatedLayout,
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
    rollback_activated_calendar_toolchain,
)


def _make_executable(path: Path) -> None:
    """Create one executable placeholder required by installer contracts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _config(
    tmp_path: Path,
) -> CalendarToolchainInstallerConfig:
    """Return one managed verified-network configuration."""
    uv = tmp_path / "uv"
    python = tmp_path / "python3.13"
    lock = tmp_path / "requirements.lock"
    payload = b"khal==0.11.4\nvdirsyncer==0.19.3\n"

    _make_executable(uv)
    _make_executable(python)
    lock.write_bytes(payload)

    return CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.VERIFIED_NETWORK,
        toolchain_version="calendar-1",
        khal_version="0.11.4",
        vdirsyncer_version="0.19.3",
        platform="linux-aarch64",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "install.json",
        service_user="lea",
        service_group="lea",
        uv_executable=uv,
        python_executable=python,
        requirements_lock=lock,
        expected_lock_sha256=hashlib.sha256(payload).hexdigest(),
        package_index_url="https://packages.example.invalid/simple",
    )


def _activated(
    config: CalendarToolchainInstallerConfig,
) -> CalendarToolchainActivatedLayout:
    """Create one exact activated layout and its directory tree."""
    root = config.tools_root / config.toolchain_version
    environment = root / ".venv"
    bin_directory = environment / "bin"
    bin_directory.mkdir(parents=True)
    _make_executable(bin_directory / "python")
    _make_executable(bin_directory / "khal")
    _make_executable(bin_directory / "vdirsyncer")
    (root / "sentinel").write_text("new activation\n", encoding="utf-8")

    return CalendarToolchainActivatedLayout(
        toolchain_root=root,
        environment_root=environment,
        python_executable=bin_directory / "python",
        khal_executable=bin_directory / "khal",
        vdirsyncer_executable=bin_directory / "vdirsyncer",
    )


def test_rollback_removes_only_exact_new_activation(
    tmp_path: Path,
) -> None:
    """The public boundary should remove the exact activated version root."""
    config = _config(tmp_path)
    activated = _activated(config)
    sibling = config.tools_root / "calendar-existing"
    sibling.mkdir()
    sentinel = sibling / "preserve"
    sentinel.write_text("existing\n", encoding="utf-8")

    issues = rollback_activated_calendar_toolchain(
        config,
        activated,
    )

    assert issues == ()
    assert activated.toolchain_root.exists() is False
    assert sentinel.read_text(encoding="utf-8") == "existing\n"
    assert config.tools_root.is_dir()


def test_rollback_is_idempotent_when_root_is_already_absent(
    tmp_path: Path,
) -> None:
    """A previously completed rollback should remain a no-op."""
    config = _config(tmp_path)
    activated = _activated(config)
    activated.toolchain_root.rename(tmp_path / "already-removed")

    issues = rollback_activated_calendar_toolchain(
        config,
        activated,
    )

    assert issues == ()


def test_rollback_rejects_layout_from_another_configuration(
    tmp_path: Path,
) -> None:
    """The coordinator must not be able to remove an unrelated root."""
    first = _config(tmp_path / "first")
    second = _config(tmp_path / "second")
    activated = _activated(first)

    issues = rollback_activated_calendar_toolchain(
        second,
        activated,
    )

    assert len(issues) == 1
    assert issues[0].code is CalendarToolchainInstallFailureCode.INVALID_ARGUMENT
    assert activated.toolchain_root.is_dir()


def test_external_mode_has_no_managed_rollback(
    tmp_path: Path,
) -> None:
    """External executable registration must not remove managed trees."""
    managed = _config(tmp_path)
    activated = _activated(managed)
    khal = tmp_path / "external" / "khal"
    vdirsyncer = tmp_path / "external" / "vdirsyncer"
    _make_executable(khal)
    _make_executable(vdirsyncer)

    external = CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES,
        toolchain_version=managed.toolchain_version,
        khal_version=managed.khal_version,
        vdirsyncer_version=managed.vdirsyncer_version,
        platform=managed.platform,
        tools_root=managed.tools_root,
        configuration_dir=managed.configuration_dir,
        state_root=managed.state_root,
        installation_record=managed.installation_record,
        service_user=managed.service_user,
        service_group=managed.service_group,
        external_khal_executable=khal,
        external_vdirsyncer_executable=vdirsyncer,
    )

    issues = rollback_activated_calendar_toolchain(
        external,
        activated,
    )

    assert len(issues) == 1
    assert issues[0].code is CalendarToolchainInstallFailureCode.INVALID_ARGUMENT
    assert activated.toolchain_root.is_dir()
