"""Tests for bundled-wheelhouse calendar installer orchestration."""

import hashlib
import stat
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from lea.installers.calendar import (
    CalendarBundledWheelhouseInstallResult,
    CalendarExtractedWheelhouse,
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
    CalendarWheelhouseExtractionResult,
    create_calendar_toolchain_installation_record,
    create_calendar_toolchain_runtime_layout,
    install_bundled_calendar_toolchain,
    render_calendar_toolchain_installation_record,
)

INSTALLED_AT = datetime(2026, 7, 31, 14, 0, tzinfo=UTC)


def _record_call(
    calls: list[str],
    phase: str,
) -> bool:
    """Record one phase and return false for expression stubs."""
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
    """Return one valid bundled-wheelhouse configuration."""
    uv = tmp_path / "uv"
    python = tmp_path / "python3.13"
    lock = tmp_path / "requirements.lock"
    archive = tmp_path / "calendar-wheelhouse.tar.gz"
    lock_payload = b"khal==0.11.4\nvdirsyncer==0.19.3\n"
    archive_payload = b"verified archive"

    _make_executable(uv)
    _make_executable(python)
    lock.write_bytes(lock_payload)
    archive.write_bytes(archive_payload)

    return CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.BUNDLED_WHEELHOUSE,
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
        expected_lock_sha256=hashlib.sha256(lock_payload).hexdigest(),
        wheelhouse_archive=archive,
        expected_wheelhouse_sha256=hashlib.sha256(archive_payload).hexdigest(),
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
    wheelhouse = root / "wheelhouse"

    inputs.mkdir(parents=True)
    wheelhouse.mkdir()
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
        wheelhouse_directory=wheelhouse,
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
    material_sha256: str | None = None,
) -> CalendarToolchainInstallationRecord:
    """Return one deterministic bundled installation record."""
    expected = material_sha256 or config.expected_lock_sha256
    assert expected is not None

    return create_calendar_toolchain_installation_record(
        config,
        python_version="3.13.5",
        khal_executable=activated.khal_executable,
        vdirsyncer_executable=activated.vdirsyncer_executable,
        lock_or_manifest_sha256=expected,
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
    """Patch subordinate phases for one successful bundled install."""
    staged = _staged(config)
    activated = _activated_layout(config)
    layout = create_calendar_toolchain_runtime_layout(config)
    wheelhouse = staged.wheelhouse_directory
    assert wheelhouse is not None
    wheel = wheelhouse / "khal.whl"
    wheel.write_bytes(b"wheel")
    archive_sha256 = config.expected_wheelhouse_sha256
    assert archive_sha256 is not None

    monkeypatch.setattr(
        "lea.installers.calendar.bundled.validate_calendar_toolchain_installer_config",
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
        "lea.installers.calendar.bundled.run_calendar_toolchain_installer_preflight",
        lambda _value: _record_call(calls, "preflight") or (),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.create_calendar_toolchain_staging",
        lambda _value: (
            _record_call(calls, "stage")
            or CalendarToolchainStagingResult(
                staged=staged,
                issues=(),
            )
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.extract_staged_calendar_wheelhouse",
        lambda _config, _staged: (
            _record_call(calls, "extract")
            or CalendarWheelhouseExtractionResult(
                extracted=CalendarExtractedWheelhouse(
                    directory=wheelhouse,
                    archive_sha256=archive_sha256,
                    wheel_files=(wheel,),
                    manifest=None,
                ),
                issues=(),
            )
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.create_calendar_toolchain_environment_plan",
        lambda _config, _staged: _record_call(calls, "plan") or object(),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.execute_calendar_toolchain_environment_plan",
        lambda _plan: (
            _record_call(calls, "environment")
            or SimpleNamespace(success=True, issues=())
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.inspect_staged_calendar_python_version",
        lambda _config, value: (
            _record_call(calls, "staged-python")
            or _python_result(value.environment_root / "bin" / "python")
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.validate_staged_calendar_tool_versions",
        lambda _config, _staged: (
            _record_call(calls, "versions") or SimpleNamespace(passed=True, issues=())
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.run_staged_calendar_toolchain_smoke_test",
        lambda _config, _staged: (
            _record_call(calls, "smoke") or SimpleNamespace(passed=True, issues=())
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.provision_calendar_toolchain_runtime_layout",
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
        "lea.installers.calendar.bundled.persist_calendar_toolchain_configuration",
        lambda *_args, **_kwargs: (
            _record_call(calls, "configuration")
            or SimpleNamespace(success=True, issues=())
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.activate_staged_calendar_toolchain",
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
        "lea.installers.calendar.bundled.inspect_calendar_python_version",
        lambda **_kwargs: (
            _record_call(calls, "final-python")
            or _python_result(activated.python_executable)
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.write_calendar_toolchain_installation_record",
        lambda *_args, **_kwargs: _record_call(calls, "record") or (),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.remove_calendar_toolchain_staging",
        lambda _value: _record_call(calls, "cleanup") or (),
    )

    return staged, activated


def test_successful_new_install_runs_exact_phase_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bundled coordinator should run every phase in order."""
    config = _config(tmp_path)
    calls: list[str] = []
    _patch_successful_new_install(monkeypatch, config, calls)

    result = install_bundled_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
        clock=lambda: INSTALLED_AT,
    )

    assert result.success is True
    assert result.already_installed is False
    assert result.record is not None
    assert result.record.lock_or_manifest_sha256 == (config.expected_lock_sha256)
    assert result.record.lock_or_manifest_sha256 != (config.expected_wheelhouse_sha256)
    assert calls == [
        "validate",
        "preflight",
        "stage",
        "extract",
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


def test_extraction_failure_cleans_staging_and_stops_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unsafe archive extraction should stop before environment planning."""
    config = _config(tmp_path)
    staged = _staged(config)
    issue = CalendarToolchainInstallerIssue(
        code=CalendarToolchainInstallFailureCode.ARCHIVE_UNSAFE,
        message="Unsafe archive.",
        field="wheelhouse_archive",
        path=config.wheelhouse_archive,
    )
    removed: list[CalendarToolchainStagingLayout] = []

    def remove_staging(
        value: CalendarToolchainStagingLayout,
    ) -> tuple[CalendarToolchainInstallerIssue, ...]:
        removed.append(value)
        return ()

    monkeypatch.setattr(
        "lea.installers.calendar.bundled.create_calendar_toolchain_staging",
        lambda _value: CalendarToolchainStagingResult(
            staged=staged,
            issues=(),
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.extract_staged_calendar_wheelhouse",
        lambda *_args: CalendarWheelhouseExtractionResult(
            extracted=None,
            issues=(issue,),
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.create_calendar_toolchain_environment_plan",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("Environment planning must not run.")
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.remove_calendar_toolchain_staging",
        remove_staging,
    )

    result = install_bundled_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
    )

    assert result.success is False
    assert result.issues == (issue,)
    assert removed == [staged]


def test_record_failure_rolls_back_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Record persistence failure should roll back the new activation."""
    config = _config(tmp_path)
    calls: list[str] = []
    staged, activated = _patch_successful_new_install(
        monkeypatch,
        config,
        calls,
    )
    issue = CalendarToolchainInstallerIssue(
        code=CalendarToolchainInstallFailureCode.RECORD_FAILED,
        message="Record failed.",
        field="installation_record",
        path=config.installation_record,
    )

    monkeypatch.setattr(
        "lea.installers.calendar.bundled.write_calendar_toolchain_installation_record",
        lambda *_args, **_kwargs: (issue,),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.rollback_activated_calendar_toolchain",
        lambda value, layout: (
            ()
            if value is config and layout == activated
            else (_ for _ in ()).throw(AssertionError())
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.remove_calendar_toolchain_staging",
        lambda value: (
            () if value == staged else (_ for _ in ()).throw(AssertionError())
        ),
    )

    result = install_bundled_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
        clock=lambda: INSTALLED_AT,
    )

    assert result.success is False
    assert result.issues == (issue,)


def test_matching_existing_installation_skips_archive_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matching active identity should skip preflight, staging and archive."""
    config = _config(tmp_path)
    activated = _create_activated_tree(config)
    record = _record(config, activated)
    config.installation_record.parent.mkdir(parents=True)
    config.installation_record.write_text(
        render_calendar_toolchain_installation_record(record),
        encoding="utf-8",
    )
    layout = create_calendar_toolchain_runtime_layout(config)

    monkeypatch.setattr(
        "lea.installers.calendar.bundled.inspect_activated_calendar_toolchain",
        lambda *_args: (),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.inspect_calendar_python_version",
        lambda **_kwargs: _python_result(activated.python_executable),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.validate_calendar_tool_versions",
        lambda **_kwargs: SimpleNamespace(passed=True, issues=()),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.provision_calendar_toolchain_runtime_layout",
        lambda *_args, **_kwargs: CalendarToolchainRuntimeLayoutResult(
            success=True,
            layout=layout,
            directories_changed=(),
            issues=(),
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.persist_calendar_toolchain_configuration",
        lambda *_args, **_kwargs: SimpleNamespace(
            success=True,
            issues=(),
        ),
    )

    for name in (
        "run_calendar_toolchain_installer_preflight",
        "create_calendar_toolchain_staging",
        "extract_staged_calendar_wheelhouse",
    ):
        monkeypatch.setattr(
            f"lea.installers.calendar.bundled.{name}",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("Archive work must not run.")
            ),
        )

    result = install_bundled_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
    )

    assert result.success is True
    assert result.already_installed is True
    assert result.record == record


def test_archive_checksum_is_not_record_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing only archive identity should not invalidate an installed lock."""
    config = _config(tmp_path)
    activated = _create_activated_tree(config)
    record = _record(config, activated)
    config.installation_record.parent.mkdir(parents=True)
    config.installation_record.write_text(
        render_calendar_toolchain_installation_record(record),
        encoding="utf-8",
    )
    layout = create_calendar_toolchain_runtime_layout(config)
    replacement_archive = tmp_path / "replacement-wheelhouse.tar.gz"
    replacement_archive.write_bytes(b"replacement verified archive")
    changed = replace(
        config,
        wheelhouse_archive=replacement_archive,
        expected_wheelhouse_sha256=hashlib.sha256(
            replacement_archive.read_bytes()
        ).hexdigest(),
    )

    monkeypatch.setattr(
        "lea.installers.calendar.bundled.inspect_activated_calendar_toolchain",
        lambda *_args: (),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.inspect_calendar_python_version",
        lambda **_kwargs: _python_result(activated.python_executable),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.validate_calendar_tool_versions",
        lambda **_kwargs: SimpleNamespace(passed=True, issues=()),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.provision_calendar_toolchain_runtime_layout",
        lambda *_args, **_kwargs: CalendarToolchainRuntimeLayoutResult(
            success=True,
            layout=layout,
            directories_changed=(),
            issues=(),
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.persist_calendar_toolchain_configuration",
        lambda *_args, **_kwargs: SimpleNamespace(
            success=True,
            issues=(),
        ),
    )

    result = install_bundled_calendar_toolchain(
        changed,
        display_timezone="Africa/Gaborone",
    )

    assert result.success is True
    assert result.already_installed is True
    assert result.record == record


def test_wrong_mode_is_rejected(tmp_path: Path) -> None:
    """The bundled coordinator should reject verified-network mode."""
    bundled = _config(tmp_path)
    assert bundled.package_index_url is None

    network = CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.VERIFIED_NETWORK,
        toolchain_version=bundled.toolchain_version,
        khal_version=bundled.khal_version,
        vdirsyncer_version=bundled.vdirsyncer_version,
        platform=bundled.platform,
        tools_root=bundled.tools_root,
        configuration_dir=bundled.configuration_dir,
        state_root=bundled.state_root,
        installation_record=bundled.installation_record,
        service_user=bundled.service_user,
        service_group=bundled.service_group,
        uv_executable=bundled.uv_executable,
        python_executable=bundled.python_executable,
        requirements_lock=bundled.requirements_lock,
        expected_lock_sha256=bundled.expected_lock_sha256,
        package_index_url="https://pypi.org/simple",
    )

    result = install_bundled_calendar_toolchain(
        network,
        display_timezone="Africa/Gaborone",
    )

    assert result.success is False
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.INVALID_ARGUMENT


def test_success_result_requires_record() -> None:
    """A successful bundled result cannot omit its record."""
    with pytest.raises(
        ValueError,
        match="must contain a record",
    ):
        CalendarBundledWheelhouseInstallResult(
            success=True,
            already_installed=False,
            record=None,
            issues=(),
        )


def test_approved_record_refresh_updates_bundled_lock_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bundled repair may refresh only verified lock evidence."""
    config = _config(tmp_path)
    activated = _create_activated_tree(config)
    expected_record = _record(config, activated)
    stale_record = replace(
        expected_record,
        lock_or_manifest_sha256="b" * 64,
    )
    config.installation_record.parent.mkdir(parents=True)
    config.installation_record.write_text(
        render_calendar_toolchain_installation_record(stale_record),
        encoding="utf-8",
    )
    layout = create_calendar_toolchain_runtime_layout(config)

    monkeypatch.setattr(
        "lea.installers.calendar.bundled.inspect_activated_calendar_toolchain",
        lambda *_args: (),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.inspect_calendar_python_version",
        lambda **_kwargs: _python_result(activated.python_executable),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.validate_calendar_tool_versions",
        lambda **_kwargs: SimpleNamespace(passed=True, issues=()),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.provision_calendar_toolchain_runtime_layout",
        lambda *_args, **_kwargs: CalendarToolchainRuntimeLayoutResult(
            success=True,
            layout=layout,
            directories_changed=(),
            issues=(),
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.persist_calendar_toolchain_configuration",
        lambda *_args, **_kwargs: SimpleNamespace(
            success=True,
            issues=(),
        ),
    )
    monkeypatch.setattr(
        "lea.installers.calendar.bundled.run_calendar_toolchain_installer_preflight",
        lambda _value: (_ for _ in ()).throw(AssertionError("Preflight must not run.")),
    )

    result = install_bundled_calendar_toolchain(
        config,
        display_timezone="Africa/Gaborone",
        approve_record_refresh=True,
    )

    assert result.success is True
    assert result.already_installed is True
    assert result.record == expected_record
    assert config.installation_record.read_text(
        encoding="utf-8"
    ) == render_calendar_toolchain_installation_record(expected_record)
