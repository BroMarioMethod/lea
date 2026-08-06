"""Tests for external calendar tool registration orchestration."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from lea.installers.calendar import (
    CalendarExternalInstallResult,
    CalendarToolchainConfigurationResult,
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallerValidationResult,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
    CalendarToolchainRuntimeLayoutResult,
    create_calendar_toolchain_configuration_plan,
    create_calendar_toolchain_runtime_layout,
    create_external_calendar_toolchain_installation_record,
    install_external_calendar_toolchain,
    run_calendar_toolchain_installer_preflight,
)

INSTALLED_AT = datetime(2026, 7, 31, 15, 0, tzinfo=UTC)


def _make_executable(
    path: Path,
    payload: bytes,
) -> str:
    """Create one executable placeholder and return its digest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    path.chmod(0o750)
    return hashlib.sha256(payload).hexdigest()


def _config(
    tmp_path: Path,
) -> CalendarToolchainInstallerConfig:
    """Return one valid external-executables configuration."""
    khal = tmp_path / "external" / "khal"
    vdirsyncer = tmp_path / "external" / "vdirsyncer"
    _make_executable(khal, b"#!/bin/sh\necho khal 0.11.4\n")
    _make_executable(
        vdirsyncer,
        b"#!/bin/sh\necho vdirsyncer 0.19.3\n",
    )
    (tmp_path / "base").mkdir()

    return CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES,
        toolchain_version="external-calendar-1",
        khal_version="0.11.4",
        vdirsyncer_version="0.19.3",
        platform="linux-aarch64",
        tools_root=tmp_path / "unmanaged-tools",
        configuration_dir=tmp_path / "base" / "config",
        state_root=tmp_path / "base" / "state",
        installation_record=tmp_path / "base" / "calendar.json",
        service_user="lea",
        service_group="lea",
        external_khal_executable=khal,
        external_vdirsyncer_executable=vdirsyncer,
        timeout_seconds=30.0,
    )


def _digest(path: Path | None) -> str:
    """Return one required executable digest."""
    assert path is not None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _successful_validation(
    config: CalendarToolchainInstallerConfig,
) -> CalendarToolchainInstallerValidationResult:
    """Return successful normalised validation."""
    return CalendarToolchainInstallerValidationResult(
        valid=True,
        config=config,
        issues=(),
    )


def _successful_runtime(
    config: CalendarToolchainInstallerConfig,
) -> CalendarToolchainRuntimeLayoutResult:
    """Return one successful runtime result."""
    return CalendarToolchainRuntimeLayoutResult(
        success=True,
        layout=create_calendar_toolchain_runtime_layout(config),
        directories_changed=(),
        issues=(),
    )


def _successful_configuration(
    config: CalendarToolchainInstallerConfig,
) -> CalendarToolchainConfigurationResult:
    """Return one successful configuration result."""
    layout = create_calendar_toolchain_runtime_layout(config)
    plan = create_calendar_toolchain_configuration_plan(
        config,
        layout,
        display_timezone="Africa/Gaborone",
    )
    return CalendarToolchainConfigurationResult(
        success=True,
        plan=plan,
        files_changed=(),
        issues=(),
    )


def _record_phase(
    calls: list[str],
    phase: str,
) -> None:
    """Record one deterministic coordinator phase."""
    calls.append(phase)


def _patch_successful_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    config: CalendarToolchainInstallerConfig,
    calls: list[str],
) -> None:
    """Patch all subordinate phases for a successful new registration."""
    khal = config.external_khal_executable
    vdirsyncer = config.external_vdirsyncer_executable
    assert khal is not None
    assert vdirsyncer is not None
    digests = {
        khal: _digest(khal),
        vdirsyncer: _digest(vdirsyncer),
    }

    def validate(
        value: CalendarToolchainInstallerConfig,
    ) -> CalendarToolchainInstallerValidationResult:
        _record_phase(calls, "validate")
        return _successful_validation(value)

    def preflight(
        _value: CalendarToolchainInstallerConfig,
    ) -> tuple[CalendarToolchainInstallerIssue, ...]:
        _record_phase(calls, "preflight")
        return ()

    def hash_executable(
        path: Path,
        *,
        field_name: str,
        tool_name: str,
    ) -> tuple[
        str | None,
        tuple[CalendarToolchainInstallerIssue, ...],
    ]:
        del field_name, tool_name
        _record_phase(calls, f"hash-{path.name}")
        return digests[path], ()

    def versions(**_kwargs: object) -> SimpleNamespace:
        _record_phase(calls, "versions")
        return SimpleNamespace(passed=True, issues=())

    def read_record(
        _path: Path,
    ) -> tuple[None, tuple[CalendarToolchainInstallerIssue, ...]]:
        raise AssertionError("No existing record should be read.")

    def smoke(**_kwargs: object) -> SimpleNamespace:
        _record_phase(calls, "smoke")
        return SimpleNamespace(passed=True, issues=())

    def runtime(
        _value: CalendarToolchainInstallerConfig,
        **_kwargs: object,
    ) -> CalendarToolchainRuntimeLayoutResult:
        _record_phase(calls, "runtime")
        return _successful_runtime(config)

    def configuration(
        *_args: object,
        **_kwargs: object,
    ) -> CalendarToolchainConfigurationResult:
        _record_phase(calls, "configuration")
        return _successful_configuration(config)

    def write_record(
        *_args: object,
        **_kwargs: object,
    ) -> tuple[CalendarToolchainInstallerIssue, ...]:
        _record_phase(calls, "record")
        return ()

    monkeypatch.setattr(
        "lea.installers.calendar.external.validate_calendar_toolchain_installer_config",
        validate,
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.run_calendar_toolchain_installer_preflight",
        preflight,
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external._hash_external_executable",
        hash_executable,
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.validate_calendar_tool_versions",
        versions,
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.read_calendar_toolchain_installation_record",
        read_record,
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.run_calendar_toolchain_smoke_test",
        smoke,
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.provision_calendar_toolchain_runtime_layout",
        runtime,
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.persist_calendar_toolchain_configuration",
        configuration,
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.write_calendar_toolchain_installation_record",
        write_record,
    )


def test_successful_new_registration_runs_external_only_phases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """External registration should avoid every managed-toolchain phase."""
    config = _config(tmp_path)
    calls: list[str] = []
    _patch_successful_dependencies(monkeypatch, config, calls)

    result = install_external_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
        clock=lambda: INSTALLED_AT,
    )

    assert result.success is True
    assert result.already_installed is False
    assert result.record is not None
    assert result.record.python_version is None
    assert result.record.lock_or_manifest_sha256 is None
    assert result.record.khal_executable_sha256 == (
        _digest(config.external_khal_executable)
    )
    assert result.record.vdirsyncer_executable_sha256 == (
        _digest(config.external_vdirsyncer_executable)
    )
    assert calls == [
        "validate",
        "preflight",
        "hash-khal",
        "hash-vdirsyncer",
        "versions",
        "hash-khal",
        "hash-vdirsyncer",
        "smoke",
        "hash-khal",
        "hash-vdirsyncer",
        "runtime",
        "configuration",
        "hash-khal",
        "hash-vdirsyncer",
        "record",
    ]


def test_matching_existing_record_skips_smoke_and_record_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matching external evidence should be an idempotent registration."""
    config = _config(tmp_path)
    khal_sha256 = _digest(config.external_khal_executable)
    vdirsyncer_sha256 = _digest(config.external_vdirsyncer_executable)
    record = create_external_calendar_toolchain_installation_record(
        config,
        khal_executable_sha256=khal_sha256,
        vdirsyncer_executable_sha256=vdirsyncer_sha256,
        installed_at=INSTALLED_AT,
    )
    config.installation_record.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        "lea.installers.calendar.external.validate_calendar_toolchain_installer_config",
        lambda value: _successful_validation(value),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.run_calendar_toolchain_installer_preflight",
        lambda _value: (),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.validate_calendar_tool_versions",
        lambda **_kwargs: SimpleNamespace(passed=True, issues=()),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.read_calendar_toolchain_installation_record",
        lambda _path: (record, ()),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.provision_calendar_toolchain_runtime_layout",
        lambda *_args, **_kwargs: _successful_runtime(config),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.persist_calendar_toolchain_configuration",
        lambda *_args, **_kwargs: _successful_configuration(config),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.run_calendar_toolchain_smoke_test",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Existing registration must skip smoke.")
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.write_calendar_toolchain_installation_record",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Existing registration must skip record write.")
        ),
    )

    result = install_external_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
    )

    assert result.success is True
    assert result.already_installed is True
    assert result.record == record


def test_mismatched_existing_record_fails_before_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A record for different executable bytes must fail closed."""
    config = _config(tmp_path)
    record = create_external_calendar_toolchain_installation_record(
        config,
        khal_executable_sha256="a" * 64,
        vdirsyncer_executable_sha256="b" * 64,
        installed_at=INSTALLED_AT,
    )
    config.installation_record.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        "lea.installers.calendar.external.validate_calendar_tool_versions",
        lambda **_kwargs: SimpleNamespace(passed=True, issues=()),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.read_calendar_toolchain_installation_record",
        lambda _path: (record, ()),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.run_calendar_toolchain_smoke_test",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Mismatched records must skip smoke.")
        ),
    )

    result = install_external_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
    )

    assert result.success is False
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.RECORD_FAILED


def test_version_failure_stops_before_smoke_and_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Incompatible external versions must cause no managed mutation."""
    config = _config(tmp_path)
    issue = CalendarToolchainInstallerIssue(
        code=CalendarToolchainInstallFailureCode.VERSION_CHECK_FAILED,
        message="Wrong version.",
        field="khal_version",
        path=config.external_khal_executable,
    )

    monkeypatch.setattr(
        "lea.installers.calendar.external.validate_calendar_tool_versions",
        lambda **_kwargs: SimpleNamespace(
            passed=False,
            issues=(issue,),
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.run_calendar_toolchain_smoke_test",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("Smoke must not run.")),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.provision_calendar_toolchain_runtime_layout",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Runtime provisioning must not run.")
        ),
    )

    result = install_external_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
    )

    assert result.success is False
    assert result.issues == (issue,)


def test_smoke_failure_stops_before_runtime_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed disposable lifecycle test must not provision runtime state."""
    config = _config(tmp_path)
    issue = CalendarToolchainInstallerIssue(
        code=CalendarToolchainInstallFailureCode.SMOKE_TEST_FAILED,
        message="Smoke failed.",
        field="external_executables",
    )

    monkeypatch.setattr(
        "lea.installers.calendar.external.validate_calendar_tool_versions",
        lambda **_kwargs: SimpleNamespace(passed=True, issues=()),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.run_calendar_toolchain_smoke_test",
        lambda **_kwargs: SimpleNamespace(
            passed=False,
            issues=(issue,),
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.provision_calendar_toolchain_runtime_layout",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Runtime provisioning must not run.")
        ),
    )

    result = install_external_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
    )

    assert result.success is False
    assert result.issues == (issue,)


def test_executable_change_after_smoke_fails_before_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Executable bytes changing during verification must fail closed."""
    config = _config(tmp_path)
    khal = config.external_khal_executable
    assert khal is not None

    monkeypatch.setattr(
        "lea.installers.calendar.external.validate_calendar_tool_versions",
        lambda **_kwargs: SimpleNamespace(passed=True, issues=()),
    )

    def smoke(**_kwargs: object) -> SimpleNamespace:
        khal.write_bytes(b"changed after smoke")
        khal.chmod(0o750)
        return SimpleNamespace(passed=True, issues=())

    monkeypatch.setattr(
        "lea.installers.calendar.external.run_calendar_toolchain_smoke_test",
        smoke,
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.provision_calendar_toolchain_runtime_layout",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Runtime provisioning must not run.")
        ),
    )

    result = install_external_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
    )

    assert result.success is False
    assert (
        result.issues[0].code is CalendarToolchainInstallFailureCode.CHECKSUM_MISMATCH
    )
    assert result.issues[0].field == "khal_executable_sha256"


def test_runtime_failure_stops_configuration_and_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runtime-layout failure must stop configuration and persistence."""
    config = _config(tmp_path)
    issue = CalendarToolchainInstallerIssue(
        code=CalendarToolchainInstallFailureCode.ACTIVATION_FAILED,
        message="Runtime failed.",
        field="state_root",
        path=config.state_root,
    )

    monkeypatch.setattr(
        "lea.installers.calendar.external.validate_calendar_tool_versions",
        lambda **_kwargs: SimpleNamespace(passed=True, issues=()),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.run_calendar_toolchain_smoke_test",
        lambda **_kwargs: SimpleNamespace(passed=True, issues=()),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.provision_calendar_toolchain_runtime_layout",
        lambda *_args, **_kwargs: CalendarToolchainRuntimeLayoutResult(
            success=False,
            layout=None,
            directories_changed=(),
            issues=(issue,),
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.external.persist_calendar_toolchain_configuration",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Configuration must not run.")
        ),
    )

    result = install_external_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
    )

    assert result.success is False
    assert result.issues == (issue,)


def test_preflight_does_not_require_external_tools_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """External mode should inspect only paths it actually manages."""
    config = _config(tmp_path)
    inspected: list[str] = []

    def inspect_parent(
        _path: Path,
        *,
        field_name: str,
    ) -> tuple[CalendarToolchainInstallerIssue, ...]:
        inspected.append(field_name)
        return ()

    monkeypatch.setattr(
        "lea.installers.calendar.preflight.check_calendar_directory_parent_writable",
        inspect_parent,
    )

    issues = run_calendar_toolchain_installer_preflight(config)

    assert issues == ()
    assert inspected == [
        "configuration_dir",
        "state_root",
        "installation_record",
    ]


def test_wrong_mode_is_rejected(tmp_path: Path) -> None:
    """Managed installation modes must not enter the external workflow."""
    external = _config(tmp_path)
    khal = external.external_khal_executable
    vdirsyncer = external.external_vdirsyncer_executable
    assert khal is not None
    assert vdirsyncer is not None
    lock = tmp_path / "requirements.lock"
    lock.write_text("khal==0.11.4\n", encoding="utf-8")

    managed = CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.VERIFIED_NETWORK,
        toolchain_version="managed-1",
        khal_version=external.khal_version,
        vdirsyncer_version=external.vdirsyncer_version,
        platform=external.platform,
        tools_root=external.tools_root,
        configuration_dir=external.configuration_dir,
        state_root=external.state_root,
        installation_record=external.installation_record,
        service_user=external.service_user,
        service_group=external.service_group,
        uv_executable=khal,
        python_executable=vdirsyncer,
        requirements_lock=lock,
        expected_lock_sha256="a" * 64,
        package_index_url="https://pypi.org/simple",
    )

    result = install_external_calendar_toolchain(
        managed,
        display_timezone="Africa/Gaborone",
    )

    assert result.success is False
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.INVALID_ARGUMENT


def test_success_result_requires_record() -> None:
    """A successful external result cannot omit registration evidence."""
    with pytest.raises(
        ValueError,
        match="must contain a record",
    ):
        CalendarExternalInstallResult(
            success=True,
            already_installed=False,
            record=None,
            issues=(),
        )
