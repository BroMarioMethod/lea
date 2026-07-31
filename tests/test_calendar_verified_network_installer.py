"""Tests for verified-network calendar installer orchestration."""

import hashlib
import stat
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from lea.installers.calendar import (
    CalendarToolchainActivatedLayout,
    CalendarToolchainActivationResult,
    CalendarToolchainInstallationRecord,
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallerValidationResult,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
    CalendarToolchainPythonVersionResult,
    CalendarToolchainRuntimeLayoutResult,
    CalendarToolchainStagingLayout,
    CalendarToolchainStagingResult,
    CalendarVerifiedNetworkInstallResult,
    create_calendar_toolchain_installation_record,
    create_calendar_toolchain_runtime_layout,
    install_verified_network_calendar_toolchain,
    render_calendar_toolchain_installation_record,
)

INSTALLED_AT = datetime(2026, 7, 31, 13, 0, tzinfo=UTC)


def _record_call(
    calls: list[str],
    phase: str,
) -> bool:
    """Record one test phase and return false for expression stubs."""
    calls.append(phase)
    return False


def _make_executable(path: Path) -> None:
    """Create one executable placeholder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _config(
    tmp_path: Path,
) -> CalendarToolchainInstallerConfig:
    """Return one valid verified-network configuration."""
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
        installation_record=(tmp_path / "install" / "calendar-toolchain.json"),
        service_user="lea",
        service_group="lea",
        uv_executable=uv,
        python_executable=python,
        requirements_lock=lock,
        expected_lock_sha256=hashlib.sha256(payload).hexdigest(),
        package_index_url="https://packages.example.invalid/simple",
        timeout_seconds=30.0,
    )


def _staged(
    config: CalendarToolchainInstallerConfig,
) -> CalendarToolchainStagingLayout:
    """Create one private staged-layout contract."""
    root = config.tools_root / ".calendar-test"
    toolchain = root / "toolchain"
    environment = toolchain / ".venv"
    bin_directory = environment / "bin"
    inputs = root / "inputs"

    inputs.mkdir(parents=True)
    bin_directory.mkdir(parents=True)

    lock = inputs / "requirements.lock"
    assert config.requirements_lock is not None
    lock.write_bytes(config.requirements_lock.read_bytes())

    _make_executable(bin_directory / "python")
    _make_executable(bin_directory / "khal")
    _make_executable(bin_directory / "vdirsyncer")

    assert config.expected_lock_sha256 is not None

    return CalendarToolchainStagingLayout(
        staging_parent=config.tools_root,
        staging_root=root,
        toolchain_root=toolchain,
        environment_root=environment,
        khal_executable=bin_directory / "khal",
        vdirsyncer_executable=bin_directory / "vdirsyncer",
        requirements_lock=lock,
        requirements_lock_sha256=config.expected_lock_sha256,
        wheelhouse_directory=None,
    )


def _activated_layout(
    config: CalendarToolchainInstallerConfig,
) -> CalendarToolchainActivatedLayout:
    """Return canonical paths for the activated toolchain."""
    root = config.tools_root / config.toolchain_version
    environment = root / ".venv"
    bin_directory = environment / "bin"

    return CalendarToolchainActivatedLayout(
        toolchain_root=root,
        environment_root=environment,
        python_executable=bin_directory / "python",
        khal_executable=bin_directory / "khal",
        vdirsyncer_executable=bin_directory / "vdirsyncer",
    )


def _create_activated_tree(
    config: CalendarToolchainInstallerConfig,
) -> CalendarToolchainActivatedLayout:
    """Create one minimal activated tree for idempotency tests."""
    activated = _activated_layout(config)
    _make_executable(activated.python_executable)
    _make_executable(activated.khal_executable)
    _make_executable(activated.vdirsyncer_executable)
    return activated


def _python_result(
    executable: Path,
    *,
    version: str = "3.13.5",
) -> CalendarToolchainPythonVersionResult:
    """Return one successful deterministic Python-version result."""
    return CalendarToolchainPythonVersionResult(
        passed=True,
        version=version,
        command=(str(executable), "-c", "version"),
        returncode=0,
        stdout=f"{version}\n",
        stderr="",
        duration_seconds=0.1,
        timed_out=False,
        issues=(),
    )


def _record(
    config: CalendarToolchainInstallerConfig,
    activated: CalendarToolchainActivatedLayout,
    *,
    python_version: str = "3.13.5",
) -> CalendarToolchainInstallationRecord:
    """Return one deterministic installation record."""
    assert config.expected_lock_sha256 is not None

    return create_calendar_toolchain_installation_record(
        config,
        python_version=python_version,
        khal_executable=activated.khal_executable,
        vdirsyncer_executable=activated.vdirsyncer_executable,
        lock_or_manifest_sha256=config.expected_lock_sha256,
        installed_at=INSTALLED_AT,
    )


def _patch_successful_new_install(
    monkeypatch: pytest.MonkeyPatch,
    config: CalendarToolchainInstallerConfig,
    calls: list[str],
) -> tuple[
    CalendarToolchainStagingLayout,
    CalendarToolchainActivatedLayout,
]:
    """Patch all subordinate phases for one successful new installation."""
    staged = _staged(config)
    activated = _activated_layout(config)
    layout = create_calendar_toolchain_runtime_layout(config)

    monkeypatch.setattr(
        "lea.installers.calendar.verified_network."
        "validate_calendar_toolchain_installer_config",
        lambda value: (
            _record_call(calls, "validate")
            or CalendarToolchainInstallerValidationResult(
                valid=True,
                config=value,
                issues=(),
            )
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network."
        "run_calendar_toolchain_installer_preflight",
        lambda _value: _record_call(calls, "preflight") or (),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network.create_calendar_toolchain_staging",
        lambda _value: (
            _record_call(calls, "stage")
            or CalendarToolchainStagingResult(
                staged=staged,
                issues=(),
            )
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network."
        "create_calendar_toolchain_environment_plan",
        lambda _config, _staged: _record_call(calls, "plan") or object(),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network."
        "execute_calendar_toolchain_environment_plan",
        lambda _plan: (
            _record_call(calls, "environment")
            or SimpleNamespace(success=True, issues=())
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network."
        "inspect_staged_calendar_python_version",
        lambda _config, value: (
            _record_call(calls, "staged-python")
            or _python_result(value.environment_root / "bin" / "python")
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network."
        "validate_staged_calendar_tool_versions",
        lambda _config, _staged: (
            _record_call(calls, "versions") or SimpleNamespace(passed=True, issues=())
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network."
        "run_staged_calendar_toolchain_smoke_test",
        lambda _config, _staged: (
            _record_call(calls, "smoke") or SimpleNamespace(passed=True, issues=())
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network."
        "provision_calendar_toolchain_runtime_layout",
        lambda _config, **_kwargs: (
            _record_call(calls, "layout")
            or CalendarToolchainRuntimeLayoutResult(
                success=True,
                layout=layout,
                directories_changed=(),
                issues=(),
            )
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network."
        "persist_calendar_toolchain_configuration",
        lambda *_args, **_kwargs: (
            _record_call(calls, "configuration")
            or SimpleNamespace(success=True, issues=())
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network.activate_staged_calendar_toolchain",
        lambda *_args, **_kwargs: (
            _record_call(calls, "activate")
            or CalendarToolchainActivationResult(
                success=True,
                changed=True,
                activated=activated,
                issues=(),
            )
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network.inspect_calendar_python_version",
        lambda **_kwargs: (
            _record_call(calls, "final-python")
            or _python_result(activated.python_executable)
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network."
        "write_calendar_toolchain_installation_record",
        lambda *_args, **_kwargs: _record_call(calls, "record") or (),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network.remove_calendar_toolchain_staging",
        lambda _value: _record_call(calls, "cleanup") or (),
    )

    return staged, activated


def test_successful_new_install_runs_exact_phase_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The coordinator should run every verified phase in order."""
    config = _config(tmp_path)
    calls: list[str] = []
    _patch_successful_new_install(monkeypatch, config, calls)

    result = install_verified_network_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
        clock=lambda: INSTALLED_AT,
    )

    assert result.success is True
    assert result.already_installed is False
    assert result.record is not None
    assert result.cleanup_issues == ()
    assert calls == [
        "validate",
        "preflight",
        "stage",
        "plan",
        "environment",
        "staged-python",
        "versions",
        "smoke",
        "layout",
        "configuration",
        "activate",
        "final-python",
        "record",
        "cleanup",
    ]


def test_preflight_failure_stops_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preflight issues should stop every staging and network phase."""
    config = _config(tmp_path)
    issue = CalendarToolchainInstallerIssue(
        code=CalendarToolchainInstallFailureCode.PERMISSION_DENIED,
        message="No write access.",
        field="tools_root",
        path=config.tools_root,
    )

    monkeypatch.setattr(
        "lea.installers.calendar.verified_network."
        "validate_calendar_toolchain_installer_config",
        lambda value: CalendarToolchainInstallerValidationResult(
            valid=True,
            config=value,
            issues=(),
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network."
        "run_calendar_toolchain_installer_preflight",
        lambda _value: (issue,),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network.create_calendar_toolchain_staging",
        lambda _value: (_ for _ in ()).throw(AssertionError("Staging must not run.")),
    )

    result = install_verified_network_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
    )

    assert result.success is False
    assert result.issues == (issue,)


def test_record_failure_rolls_back_and_cleans_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Record failure should roll back only the new activation."""
    config = _config(tmp_path)
    calls: list[str] = []
    staged, activated = _patch_successful_new_install(
        monkeypatch,
        config,
        calls,
    )
    issue = CalendarToolchainInstallerIssue(
        code=CalendarToolchainInstallFailureCode.RECORD_FAILED,
        message="Record write failed.",
        field="installation_record",
        path=config.installation_record,
    )

    monkeypatch.setattr(
        "lea.installers.calendar.verified_network."
        "write_calendar_toolchain_installation_record",
        lambda *_args, **_kwargs: _record_call(calls, "record-failed") or (issue,),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network."
        "rollback_activated_calendar_toolchain",
        lambda value, layout: (
            _record_call(calls, "rollback")
            or (
                ()
                if value is config and layout == activated
                else (_ for _ in ()).throw(AssertionError())
            )
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network.remove_calendar_toolchain_staging",
        lambda value: (
            _record_call(calls, "cleanup-after-failure")
            or (() if value == staged else (_ for _ in ()).throw(AssertionError()))
        ),
    )

    result = install_verified_network_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
        clock=lambda: INSTALLED_AT,
    )

    assert result.success is False
    assert result.issues == (issue,)
    assert "rollback" in calls
    assert calls[-1] == "cleanup-after-failure"


def test_cleanup_failure_is_retained_without_losing_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A residual staging root should be reported separately."""
    config = _config(tmp_path)
    calls: list[str] = []
    _patch_successful_new_install(monkeypatch, config, calls)
    cleanup_issue = CalendarToolchainInstallerIssue(
        code=CalendarToolchainInstallFailureCode.ACTIVATION_FAILED,
        message="Staging cleanup failed.",
        field="staging_root",
        path=config.tools_root / ".calendar-test",
    )

    monkeypatch.setattr(
        "lea.installers.calendar.verified_network.remove_calendar_toolchain_staging",
        lambda _value: (cleanup_issue,),
    )

    result = install_verified_network_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
        clock=lambda: INSTALLED_AT,
    )

    assert result.success is True
    assert result.record is not None
    assert result.issues == ()
    assert result.cleanup_issues == (cleanup_issue,)


def test_matching_existing_installation_skips_preflight_and_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A matching toolchain and record should return idempotently."""
    config = _config(tmp_path)
    activated = _create_activated_tree(config)
    record = _record(config, activated)
    config.installation_record.parent.mkdir(parents=True)
    config.installation_record.write_text(
        render_calendar_toolchain_installation_record(record),
        encoding="utf-8",
    )
    calls: list[str] = []
    layout = create_calendar_toolchain_runtime_layout(config)

    monkeypatch.setattr(
        "lea.installers.calendar.verified_network.inspect_activated_calendar_toolchain",
        lambda *_args: (),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network.inspect_calendar_python_version",
        lambda **_kwargs: _python_result(activated.python_executable),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network.validate_calendar_tool_versions",
        lambda **_kwargs: SimpleNamespace(passed=True, issues=()),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network."
        "provision_calendar_toolchain_runtime_layout",
        lambda *_args, **_kwargs: (
            _record_call(calls, "layout")
            or CalendarToolchainRuntimeLayoutResult(
                success=True,
                layout=layout,
                directories_changed=(),
                issues=(),
            )
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network."
        "persist_calendar_toolchain_configuration",
        lambda *_args, **_kwargs: (
            _record_call(calls, "configuration")
            or SimpleNamespace(success=True, issues=())
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network."
        "run_calendar_toolchain_installer_preflight",
        lambda _value: (_ for _ in ()).throw(AssertionError("Preflight must not run.")),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network.create_calendar_toolchain_staging",
        lambda _value: (_ for _ in ()).throw(AssertionError("Staging must not run.")),
    )

    result = install_verified_network_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
    )

    assert result.success is True
    assert result.already_installed is True
    assert result.record == record
    assert calls == ["layout", "configuration"]


def test_existing_record_mismatch_fails_before_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing identity mismatch must not start replacement work."""
    config = _config(tmp_path)
    activated = _create_activated_tree(config)
    record = _record(
        config,
        activated,
        python_version="3.13.6",
    )
    config.installation_record.parent.mkdir(parents=True)
    config.installation_record.write_text(
        render_calendar_toolchain_installation_record(record),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "lea.installers.calendar.verified_network.inspect_activated_calendar_toolchain",
        lambda *_args: (),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network.inspect_calendar_python_version",
        lambda **_kwargs: _python_result(activated.python_executable),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network.validate_calendar_tool_versions",
        lambda **_kwargs: SimpleNamespace(passed=True, issues=()),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.verified_network."
        "run_calendar_toolchain_installer_preflight",
        lambda _value: (_ for _ in ()).throw(AssertionError("Preflight must not run.")),
    )

    result = install_verified_network_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
    )

    assert result.success is False
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.RECORD_FAILED


def test_wrong_mode_is_rejected(
    tmp_path: Path,
) -> None:
    """The verified-network coordinator should reject other modes."""
    khal = tmp_path / "external" / "khal"
    vdirsyncer = tmp_path / "external" / "vdirsyncer"
    _make_executable(khal)
    _make_executable(vdirsyncer)

    config = CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES,
        toolchain_version="external-1",
        khal_version="0.11.4",
        vdirsyncer_version="0.19.3",
        platform="linux-aarch64",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "record.json",
        service_user="lea",
        service_group="lea",
        external_khal_executable=khal,
        external_vdirsyncer_executable=vdirsyncer,
    )

    result = install_verified_network_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
    )

    assert result.success is False
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.INVALID_ARGUMENT


def test_success_result_requires_record() -> None:
    """A successful coordinator result cannot omit its record."""
    with pytest.raises(
        ValueError,
        match="must contain a record",
    ):
        CalendarVerifiedNetworkInstallResult(
            success=True,
            already_installed=False,
            record=None,
            issues=(),
        )
