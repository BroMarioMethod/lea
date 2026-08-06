"""Tests for private calendar toolchain installer staging."""

import hashlib
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from lea.installers.calendar import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
    CalendarToolchainStagingLayout,
    create_calendar_toolchain_staging,
    remove_calendar_toolchain_staging,
)


def _make_executable(path: Path) -> None:
    """Create one executable test script."""
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _network_config(
    tmp_path: Path,
) -> CalendarToolchainInstallerConfig:
    """Return one managed verified-network configuration."""
    uv_executable = tmp_path / "uv"
    python_executable = tmp_path / "python3"
    requirements_lock = tmp_path / "calendar-requirements.txt"
    payload = b"khal==0.11.4\nvdirsyncer==0.19.3\n"

    _make_executable(uv_executable)
    _make_executable(python_executable)
    requirements_lock.write_bytes(payload)

    return CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.VERIFIED_NETWORK,
        toolchain_version="1",
        khal_version="0.11.4",
        vdirsyncer_version="0.19.3",
        platform="linux-aarch64",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "install.json",
        service_user="lea",
        service_group="lea",
        uv_executable=uv_executable,
        python_executable=python_executable,
        requirements_lock=requirements_lock,
        expected_lock_sha256=hashlib.sha256(payload).hexdigest(),
        package_index_url="https://pypi.org/simple",
    )


def _bundled_config(
    tmp_path: Path,
) -> CalendarToolchainInstallerConfig:
    """Return one managed bundled-wheelhouse configuration."""
    archive = tmp_path / "calendar-wheelhouse.tar.gz"
    archive_payload = b"wheelhouse"
    archive.write_bytes(archive_payload)

    return replace(
        _network_config(tmp_path),
        mode=CalendarToolchainInstallMode.BUNDLED_WHEELHOUSE,
        package_index_url=None,
        wheelhouse_archive=archive,
        expected_wheelhouse_sha256=hashlib.sha256(archive_payload).hexdigest(),
    )


def _external_config(
    tmp_path: Path,
) -> CalendarToolchainInstallerConfig:
    """Return one external-executables configuration."""
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
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "install.json",
        service_user="lea",
        service_group="lea",
        external_khal_executable=khal_executable,
        external_vdirsyncer_executable=vdirsyncer_executable,
    )


def test_network_staging_copies_verified_lock_and_reserves_paths(
    tmp_path: Path,
) -> None:
    """Network staging should copy only verified inputs and reserve .venv."""
    config = _network_config(tmp_path)

    result = create_calendar_toolchain_staging(config)

    assert result.issues == ()
    assert result.staged is not None

    staged = result.staged
    assert staged.staging_parent == config.tools_root
    assert staged.staging_root.parent == config.tools_root
    assert staged.staging_root.name.startswith(".calendar-")
    assert staged.toolchain_root.is_dir()
    assert staged.toolchain_root.stat().st_mode & 0o777 == 0o750
    assert staged.requirements_lock.read_bytes() == (
        config.requirements_lock.read_bytes()
        if config.requirements_lock is not None
        else b""
    )
    assert staged.requirements_lock.stat().st_mode & 0o777 == 0o640
    assert staged.wheelhouse_directory is None
    assert staged.environment_root == staged.toolchain_root / ".venv"
    assert not staged.environment_root.exists()
    assert staged.khal_executable == (staged.environment_root / "bin" / "khal")
    assert staged.vdirsyncer_executable == (
        staged.environment_root / "bin" / "vdirsyncer"
    )


def test_staging_roots_are_unique(
    tmp_path: Path,
) -> None:
    """Concurrent or repeated staging operations should not collide."""
    config = _network_config(tmp_path)

    first = create_calendar_toolchain_staging(config)
    second = create_calendar_toolchain_staging(config)

    assert first.staged is not None
    assert second.staged is not None
    assert first.staged.staging_root != second.staged.staging_root


def test_bundled_staging_reserves_private_wheelhouse(
    tmp_path: Path,
) -> None:
    """Bundled mode should reserve a private extraction destination."""
    result = create_calendar_toolchain_staging(_bundled_config(tmp_path))

    assert result.staged is not None
    wheelhouse = result.staged.wheelhouse_directory
    assert wheelhouse is not None
    assert wheelhouse.is_dir()
    assert wheelhouse.stat().st_mode & 0o777 == 0o750


def test_external_mode_does_not_create_managed_staging(
    tmp_path: Path,
) -> None:
    """External executables should bypass managed Python staging."""
    config = _external_config(tmp_path)

    result = create_calendar_toolchain_staging(config)

    assert result.staged is None
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.INVALID_ARGUMENT
    assert not config.tools_root.exists()


def test_changed_requirements_lock_prevents_staging(
    tmp_path: Path,
) -> None:
    """A lock changed after validation should fail before directory creation."""
    config = _network_config(tmp_path)
    assert config.requirements_lock is not None
    config.requirements_lock.write_text("changed\n", encoding="utf-8")

    result = create_calendar_toolchain_staging(config)

    assert result.staged is None
    assert (
        result.issues[0].code is CalendarToolchainInstallFailureCode.CHECKSUM_MISMATCH
    )
    assert not config.tools_root.exists()


def test_missing_requirements_lock_prevents_staging(
    tmp_path: Path,
) -> None:
    """A missing lock should fail without leaving a staging directory."""
    config = _network_config(tmp_path)
    assert config.requirements_lock is not None
    config.requirements_lock.unlink()

    result = create_calendar_toolchain_staging(config)

    assert result.staged is None
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.ARTEFACT_MISSING
    assert not config.tools_root.exists()


def test_remove_staging_preserves_active_and_unrelated_paths(
    tmp_path: Path,
) -> None:
    """Cleanup should remove only the private staging root."""
    config = _network_config(tmp_path)
    active = config.tools_root / config.toolchain_version
    active.mkdir(parents=True)
    marker = active / "active.txt"
    marker.write_text("preserve", encoding="utf-8")

    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("preserve", encoding="utf-8")

    result = create_calendar_toolchain_staging(config)
    assert result.staged is not None
    staging_root = result.staged.staging_root

    assert remove_calendar_toolchain_staging(result.staged) == ()
    assert not staging_root.exists()
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert unrelated.read_text(encoding="utf-8") == "preserve"


def test_remove_missing_staging_is_idempotent(
    tmp_path: Path,
) -> None:
    """Repeated cleanup should remain safe."""
    result = create_calendar_toolchain_staging(_network_config(tmp_path))
    assert result.staged is not None

    assert remove_calendar_toolchain_staging(result.staged) == ()
    assert remove_calendar_toolchain_staging(result.staged) == ()


def test_staging_contract_rejects_root_outside_parent(
    tmp_path: Path,
) -> None:
    """A constructed staging layout must preserve direct containment."""
    parent = tmp_path / "tools"
    root = tmp_path / ".calendar-test"
    toolchain = root / "toolchain"
    environment = toolchain / ".venv"

    with pytest.raises(
        ValueError,
        match="directly inside staging_parent",
    ):
        CalendarToolchainStagingLayout(
            staging_parent=parent,
            staging_root=root,
            toolchain_root=toolchain,
            environment_root=environment,
            khal_executable=environment / "bin" / "khal",
            vdirsyncer_executable=environment / "bin" / "vdirsyncer",
            requirements_lock=root / "inputs" / "requirements.lock",
            requirements_lock_sha256="a" * 64,
            wheelhouse_directory=None,
        )
