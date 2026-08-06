"""Tests for external calendar installation-record evidence."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lea.installers.calendar import (
    CalendarToolchainInstallationRecord,
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
    create_external_calendar_toolchain_installation_record,
    external_calendar_toolchain_installation_record_matches,
    read_calendar_toolchain_installation_record,
    render_calendar_toolchain_installation_record,
    validate_calendar_toolchain_installer_config,
)

INSTALLED_AT = datetime(2026, 7, 31, 14, 30, tzinfo=UTC)


def _make_executable(
    path: Path,
    payload: bytes,
) -> str:
    """Create one executable and return its exact SHA-256 digest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    path.chmod(0o750)
    return hashlib.sha256(payload).hexdigest()


def _config(
    tmp_path: Path,
) -> tuple[
    CalendarToolchainInstallerConfig,
    str,
    str,
]:
    """Return one valid external-executables configuration and digests."""
    khal = tmp_path / "external" / "khal"
    vdirsyncer = tmp_path / "external" / "vdirsyncer"
    khal_sha256 = _make_executable(
        khal,
        b"#!/bin/sh\necho khal 0.11.4\n",
    )
    vdirsyncer_sha256 = _make_executable(
        vdirsyncer,
        b"#!/bin/sh\necho vdirsyncer 0.19.3\n",
    )

    return (
        CalendarToolchainInstallerConfig(
            mode=CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES,
            toolchain_version="external-calendar-1",
            khal_version="0.11.4",
            vdirsyncer_version="0.19.3",
            platform="linux-aarch64",
            tools_root=tmp_path / "tools",
            configuration_dir=tmp_path / "config",
            state_root=tmp_path / "state",
            installation_record=tmp_path / "install" / "calendar.json",
            service_user="lea",
            service_group="lea",
            external_khal_executable=khal,
            external_vdirsyncer_executable=vdirsyncer,
        ),
        khal_sha256,
        vdirsyncer_sha256,
    )


def _record(
    tmp_path: Path,
) -> tuple[
    CalendarToolchainInstallationRecord,
    CalendarToolchainInstallerConfig,
    str,
    str,
]:
    """Return one deterministic external installation record."""
    config, khal_sha256, vdirsyncer_sha256 = _config(tmp_path)
    record = create_external_calendar_toolchain_installation_record(
        config,
        khal_executable_sha256=khal_sha256,
        vdirsyncer_executable_sha256=vdirsyncer_sha256,
        installed_at=INSTALLED_AT,
    )
    return record, config, khal_sha256, vdirsyncer_sha256


def test_external_record_creation_uses_exact_executable_evidence(
    tmp_path: Path,
) -> None:
    """External records should contain paths and independent digests."""
    record, config, khal_sha256, vdirsyncer_sha256 = _record(tmp_path)

    assert record.schema_version == 2
    assert record.installation_mode is CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES
    assert record.python_version is None
    assert record.lock_or_manifest_sha256 is None
    assert record.khal_executable == config.external_khal_executable
    assert record.vdirsyncer_executable == config.external_vdirsyncer_executable
    assert record.khal_executable_sha256 == khal_sha256
    assert record.vdirsyncer_executable_sha256 == vdirsyncer_sha256


def test_external_record_rendering_uses_explicit_nulls(
    tmp_path: Path,
) -> None:
    """Mode-inapplicable managed fields should remain explicit JSON null."""
    record, _, khal_sha256, vdirsyncer_sha256 = _record(tmp_path)

    payload = json.loads(render_calendar_toolchain_installation_record(record))

    assert payload["schema_version"] == 2
    assert payload["python_version"] is None
    assert payload["lock_or_manifest_sha256"] is None
    assert payload["khal_executable_sha256"] == khal_sha256
    assert payload["vdirsyncer_executable_sha256"] == vdirsyncer_sha256


def test_external_record_round_trip_is_lossless(
    tmp_path: Path,
) -> None:
    """A strict schema-v2 external record should round-trip exactly."""
    record, _, _, _ = _record(tmp_path)
    path = tmp_path / "record.json"
    path.write_text(
        render_calendar_toolchain_installation_record(record),
        encoding="utf-8",
    )

    parsed, issues = read_calendar_toolchain_installation_record(path)

    assert issues == ()
    assert parsed == record


def test_external_matcher_compares_both_digests(
    tmp_path: Path,
) -> None:
    """Either external executable changing must invalidate identity."""
    record, config, khal_sha256, vdirsyncer_sha256 = _record(tmp_path)

    assert external_calendar_toolchain_installation_record_matches(
        record,
        config=config,
        khal_executable_sha256=khal_sha256,
        vdirsyncer_executable_sha256=vdirsyncer_sha256,
    )

    assert not external_calendar_toolchain_installation_record_matches(
        record,
        config=config,
        khal_executable_sha256="a" * 64,
        vdirsyncer_executable_sha256=vdirsyncer_sha256,
    )

    assert not external_calendar_toolchain_installation_record_matches(
        record,
        config=config,
        khal_executable_sha256=khal_sha256,
        vdirsyncer_executable_sha256="b" * 64,
    )


def test_external_record_rejects_managed_material(
    tmp_path: Path,
) -> None:
    """External mode cannot carry fabricated Python or lock identity."""
    record, _, _, _ = _record(tmp_path)

    with pytest.raises(
        ValueError,
        match="must not contain python_version",
    ):
        replace(
            record,
            python_version="3.13.5",
        )

    with pytest.raises(
        ValueError,
        match="must not contain lock_or_manifest_sha256",
    ):
        replace(
            record,
            lock_or_manifest_sha256="a" * 64,
        )


def test_external_record_requires_both_digests(
    tmp_path: Path,
) -> None:
    """Neither executable may be represented without its digest."""
    record, _, _, _ = _record(tmp_path)

    with pytest.raises(
        ValueError,
        match="require khal_executable_sha256",
    ):
        replace(
            record,
            khal_executable_sha256=None,
        )

    with pytest.raises(
        ValueError,
        match="require vdirsyncer_executable_sha256",
    ):
        replace(
            record,
            vdirsyncer_executable_sha256=None,
        )


def test_managed_mode_cannot_use_external_creator(
    tmp_path: Path,
) -> None:
    """The external creator should reject managed installation modes."""
    config, khal_sha256, vdirsyncer_sha256 = _config(tmp_path)
    khal = config.external_khal_executable
    vdirsyncer = config.external_vdirsyncer_executable
    assert khal is not None
    assert vdirsyncer is not None

    lock = tmp_path / "requirements.lock"
    lock.write_text("khal==0.11.4\n", encoding="utf-8")

    managed = CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.VERIFIED_NETWORK,
        toolchain_version="managed-1",
        khal_version=config.khal_version,
        vdirsyncer_version=config.vdirsyncer_version,
        platform=config.platform,
        tools_root=config.tools_root,
        configuration_dir=config.configuration_dir,
        state_root=config.state_root,
        installation_record=config.installation_record,
        service_user=config.service_user,
        service_group=config.service_group,
        uv_executable=khal,
        python_executable=vdirsyncer,
        requirements_lock=lock,
        expected_lock_sha256="c" * 64,
        package_index_url="https://pypi.org/simple",
    )

    with pytest.raises(
        ValueError,
        match="requires external-executables mode",
    ):
        create_external_calendar_toolchain_installation_record(
            managed,
            khal_executable_sha256=khal_sha256,
            vdirsyncer_executable_sha256=vdirsyncer_sha256,
            installed_at=INSTALLED_AT,
        )


@pytest.mark.parametrize(
    "tool",
    ("khal", "vdirsyncer"),
)
def test_external_validation_rejects_symbolic_executable(
    tmp_path: Path,
    tool: str,
) -> None:
    """External registration must not accept a symbolic executable path."""
    config, _, _ = _config(tmp_path)
    original = (
        config.external_khal_executable
        if tool == "khal"
        else config.external_vdirsyncer_executable
    )
    assert original is not None

    target = original.with_name(f"{original.name}-target")
    original.rename(target)
    original.symlink_to(target)

    result = validate_calendar_toolchain_installer_config(config)

    assert result.valid is False
    assert any(
        issue.code is CalendarToolchainInstallFailureCode.INVALID_ARGUMENT
        and issue.path == original
        and "non-symbolic" in issue.message
        for issue in result.issues
    )


def test_schema_version_one_record_is_rejected(
    tmp_path: Path,
) -> None:
    """The strict reader should reject the superseded schema shape."""
    record, _, _, _ = _record(tmp_path)
    payload = json.loads(render_calendar_toolchain_installation_record(record))
    payload["schema_version"] = 1
    path = tmp_path / "record.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    parsed, issues = read_calendar_toolchain_installation_record(path)

    assert parsed is None
    assert len(issues) == 1
    assert issues[0].code is CalendarToolchainInstallFailureCode.RECORD_FAILED
