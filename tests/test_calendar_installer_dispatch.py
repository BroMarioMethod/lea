"""Tests for mode-based calendar toolchain installer dispatch."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lea.installers.calendar import (
    CalendarBundledWheelhouseInstallResult,
    CalendarExternalInstallResult,
    CalendarToolchainInstallationRecord,
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
    CalendarToolchainInstallResult,
    CalendarVerifiedNetworkInstallResult,
    create_calendar_toolchain_installation_record,
    create_external_calendar_toolchain_installation_record,
    install_calendar_toolchain,
)

INSTALLED_AT = datetime(2026, 7, 31, 15, 30, tzinfo=UTC)
LOCK_SHA256 = "a" * 64


def _make_executable(path: Path) -> None:
    """Create one executable placeholder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o750)


def _managed_config(
    tmp_path: Path,
    *,
    mode: CalendarToolchainInstallMode,
) -> CalendarToolchainInstallerConfig:
    """Return one valid managed-mode configuration."""
    root = tmp_path / mode.value
    uv = root / "uv"
    python = root / "python3.13"
    lock = root / "requirements.lock"
    _make_executable(uv)
    _make_executable(python)
    lock.write_text("khal==0.11.4\n", encoding="utf-8")

    if mode is CalendarToolchainInstallMode.VERIFIED_NETWORK:
        return CalendarToolchainInstallerConfig(
            mode=mode,
            toolchain_version=f"{mode.value}-1",
            khal_version="0.11.4",
            vdirsyncer_version="0.19.3",
            platform="linux-aarch64",
            tools_root=root / "tools",
            configuration_dir=root / "config",
            state_root=root / "state",
            installation_record=(root / "install" / "calendar.json"),
            service_user="lea",
            service_group="lea",
            uv_executable=uv,
            python_executable=python,
            requirements_lock=lock,
            expected_lock_sha256=LOCK_SHA256,
            package_index_url="https://pypi.org/simple",
            timeout_seconds=30.0,
        )

    if mode is not CalendarToolchainInstallMode.BUNDLED_WHEELHOUSE:
        raise ValueError("mode must be a managed installation mode.")

    archive = root / "wheelhouse.tar.gz"
    archive.write_bytes(b"wheelhouse")

    return CalendarToolchainInstallerConfig(
        mode=mode,
        toolchain_version=f"{mode.value}-1",
        khal_version="0.11.4",
        vdirsyncer_version="0.19.3",
        platform="linux-aarch64",
        tools_root=root / "tools",
        configuration_dir=root / "config",
        state_root=root / "state",
        installation_record=root / "install" / "calendar.json",
        service_user="lea",
        service_group="lea",
        uv_executable=uv,
        python_executable=python,
        requirements_lock=lock,
        expected_lock_sha256=LOCK_SHA256,
        wheelhouse_archive=archive,
        expected_wheelhouse_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        timeout_seconds=30.0,
    )


def _external_config(
    tmp_path: Path,
) -> CalendarToolchainInstallerConfig:
    """Return one valid external-executables configuration."""
    khal = tmp_path / "external" / "khal"
    vdirsyncer = tmp_path / "external" / "vdirsyncer"
    _make_executable(khal)
    _make_executable(vdirsyncer)

    return CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES,
        toolchain_version="external-1",
        khal_version="0.11.4",
        vdirsyncer_version="0.19.3",
        platform="linux-aarch64",
        tools_root=tmp_path / "external" / "unused-tools",
        configuration_dir=tmp_path / "external" / "config",
        state_root=tmp_path / "external" / "state",
        installation_record=(tmp_path / "external" / "install" / "calendar.json"),
        service_user="lea",
        service_group="lea",
        external_khal_executable=khal,
        external_vdirsyncer_executable=vdirsyncer,
        timeout_seconds=30.0,
    )


def _managed_record(
    config: CalendarToolchainInstallerConfig,
) -> CalendarToolchainInstallationRecord:
    """Return one deterministic managed installation record."""
    root = config.tools_root / config.toolchain_version / ".venv" / "bin"

    return create_calendar_toolchain_installation_record(
        config,
        python_version="3.13.5",
        khal_executable=root / "khal",
        vdirsyncer_executable=root / "vdirsyncer",
        lock_or_manifest_sha256=LOCK_SHA256,
        installed_at=INSTALLED_AT,
    )


def _external_record(
    config: CalendarToolchainInstallerConfig,
) -> CalendarToolchainInstallationRecord:
    """Return one deterministic external installation record."""
    return create_external_calendar_toolchain_installation_record(
        config,
        khal_executable_sha256="b" * 64,
        vdirsyncer_executable_sha256="c" * 64,
        installed_at=INSTALLED_AT,
    )


def _ownership(
    _path: Path,
    _owner: str,
    _group: str,
) -> bool:
    """Return one deterministic ownership result."""
    return False


def test_dispatches_verified_network_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verified-network mode should call only its coordinator."""
    config = _managed_config(
        tmp_path,
        mode=CalendarToolchainInstallMode.VERIFIED_NETWORK,
    )
    record = _managed_record(config)
    cleanup_issue = CalendarToolchainInstallerIssue(
        code=CalendarToolchainInstallFailureCode.COPY_FAILED,
        message="Staging cleanup warning.",
        field="staging_root",
        path=config.tools_root,
    )

    def selected(
        value: CalendarToolchainInstallerConfig,
        *,
        display_timezone: str,
        clock: object,
        fsync: bool,
        apply_ownership: object,
    ) -> CalendarVerifiedNetworkInstallResult:
        assert value is config
        assert display_timezone == "Africa/Gaborone"
        assert clock is _clock
        assert fsync is True
        assert apply_ownership is _ownership
        return CalendarVerifiedNetworkInstallResult(
            success=True,
            already_installed=False,
            record=record,
            issues=(),
            cleanup_issues=(cleanup_issue,),
        )

    monkeypatch.setattr(
        "lea.installers.calendar.dispatch.install_verified_network_calendar_toolchain",
        selected,
    )

    result = install_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
        clock=_clock,
        fsync=True,
        apply_ownership=_ownership,
    )

    assert result.success is True
    assert result.record == record
    assert result.cleanup_issues == (cleanup_issue,)


def test_dispatches_bundled_wheelhouse_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bundled-wheelhouse mode should call only its coordinator."""
    config = _managed_config(
        tmp_path,
        mode=CalendarToolchainInstallMode.BUNDLED_WHEELHOUSE,
    )
    record = _managed_record(config)

    def selected(
        value: CalendarToolchainInstallerConfig,
        *,
        display_timezone: str,
        clock: object,
        fsync: bool,
        apply_ownership: object,
    ) -> CalendarBundledWheelhouseInstallResult:
        assert value is config
        assert display_timezone == "Africa/Gaborone"
        assert clock is _clock
        assert fsync is True
        assert apply_ownership is _ownership
        return CalendarBundledWheelhouseInstallResult(
            success=True,
            already_installed=True,
            record=record,
            issues=(),
            cleanup_issues=(),
        )

    monkeypatch.setattr(
        "lea.installers.calendar.dispatch.install_bundled_calendar_toolchain",
        selected,
    )

    result = install_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
        clock=_clock,
        fsync=True,
        apply_ownership=_ownership,
    )

    assert result.success is True
    assert result.already_installed is True
    assert result.record == record
    assert result.cleanup_issues == ()


def test_dispatches_external_executables_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """External mode should call only its coordinator."""
    config = _external_config(tmp_path)
    record = _external_record(config)

    def selected(
        value: CalendarToolchainInstallerConfig,
        *,
        display_timezone: str,
        clock: object,
        fsync: bool,
        apply_ownership: object,
    ) -> CalendarExternalInstallResult:
        assert value is config
        assert display_timezone == "Africa/Gaborone"
        assert clock is _clock
        assert fsync is True
        assert apply_ownership is _ownership
        return CalendarExternalInstallResult(
            success=True,
            already_installed=False,
            record=record,
            issues=(),
        )

    monkeypatch.setattr(
        "lea.installers.calendar.dispatch.install_external_calendar_toolchain",
        selected,
    )

    result = install_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
        clock=_clock,
        fsync=True,
        apply_ownership=_ownership,
    )

    assert result.success is True
    assert result.record == record
    assert result.cleanup_issues == ()


def test_generic_success_requires_record() -> None:
    """A successful generic result must contain installation evidence."""
    with pytest.raises(
        ValueError,
        match="must contain a record",
    ):
        CalendarToolchainInstallResult(
            success=True,
            already_installed=False,
            record=None,
            issues=(),
        )


def test_dispatch_requires_calendar_configuration() -> None:
    """The dispatcher should reject unrelated configuration values."""
    with pytest.raises(
        TypeError,
        match="CalendarToolchainInstallerConfig",
    ):
        install_calendar_toolchain(
            object(),  # type: ignore[arg-type]
            display_timezone="Africa/Gaborone",
        )


def _clock() -> datetime:
    """Return one deterministic installer timestamp."""
    return INSTALLED_AT
