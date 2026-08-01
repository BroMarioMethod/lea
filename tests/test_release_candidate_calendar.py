"""Tests for release-candidate calendar toolchain integration."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from lea.installers.calendar.contracts import (
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
)
from lea.installers.calendar.dispatch import CalendarToolchainInstallResult
from lea.installers.calendar.records import (
    CalendarToolchainInstallationRecord,
)
from lea.installers.release_candidate import (
    InstallerStepId,
    ReleaseCandidateCalendarInputs,
    ReleaseCandidateInstallMode,
    ReleaseCandidateInstallRequest,
    create_calendar_toolchain_installation_plan,
    install_release_candidate_calendar_toolchain,
)


def _request(tmp_path: Path) -> ReleaseCandidateInstallRequest:
    """Return one isolated release-candidate request."""
    return ReleaseCandidateInstallRequest(
        mode=ReleaseCandidateInstallMode.FRESH_INSTALL,
        display_timezone="Africa/Gaborone",
        enable_telegram=False,
        configuration_root=tmp_path / "etc" / "lea",
        state_root=tmp_path / "var" / "lib" / "lea",
        log_root=tmp_path / "var" / "log" / "lea",
    )


def _inputs(tmp_path: Path) -> ReleaseCandidateCalendarInputs:
    """Return valid pinned verified-network inputs."""
    lock = tmp_path / "calendar-requirements.txt"
    lock.write_text(
        "khal==0.11.4\nvdirsyncer==0.19.3\n",
        encoding="utf-8",
    )
    uv = tmp_path / "bin" / "uv"
    uv.parent.mkdir()
    uv.write_text("#!/bin/sh\n", encoding="utf-8")

    python = tmp_path / "bin" / "python"
    python.write_text("#!/bin/sh\n", encoding="utf-8")

    return ReleaseCandidateCalendarInputs(
        toolchain_version="1.0.0",
        platform="linux-aarch64",
        requirements_lock=lock,
        expected_lock_sha256="a" * 64,
        uv_executable=uv,
        python_executable=python,
        package_index_url="https://pypi.org/simple",
    )


def _record(plan: Any) -> CalendarToolchainInstallationRecord:
    """Return one deterministic successful calendar record."""
    return CalendarToolchainInstallationRecord(
        schema_version=2,
        component="calendar-toolchain",
        toolchain_version=plan.config.toolchain_version,
        installation_mode=CalendarToolchainInstallMode.VERIFIED_NETWORK,
        platform=plan.config.platform,
        python_version="3.13.5",
        khal_version=plan.config.khal_version,
        vdirsyncer_version=plan.config.vdirsyncer_version,
        khal_executable=plan.expected_khal_executable,
        vdirsyncer_executable=plan.expected_vdirsyncer_executable,
        lock_or_manifest_sha256=plan.config.expected_lock_sha256,
        khal_executable_sha256=None,
        vdirsyncer_executable_sha256=None,
        smoke_test="passed",
        installed_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )


def test_plan_reuses_existing_calendar_installer_contract(
    tmp_path: Path,
) -> None:
    """The release-candidate plan should build the existing config contract."""
    request = _request(tmp_path)
    inputs = _inputs(tmp_path)

    plan = create_calendar_toolchain_installation_plan(request, inputs)

    assert plan.config.mode is CalendarToolchainInstallMode.VERIFIED_NETWORK
    assert plan.config.toolchain_version == "1.0.0"
    assert plan.config.khal_version == "0.11.4"
    assert plan.config.vdirsyncer_version == "0.19.3"
    assert plan.config.tools_root == Path("/opt/lea-tools/calendar")
    assert plan.config.uv_executable == inputs.uv_executable
    assert plan.config.python_executable == inputs.python_executable
    assert plan.config.package_index_url == "https://pypi.org/simple"
    assert plan.config.configuration_dir == request.configuration_root / "calendar"
    assert plan.config.state_root == request.state_root / "calendar"
    assert plan.config.installation_record == (
        request.state_root / "install" / "calendar-toolchain.json"
    )
    assert plan.expected_khal_executable == Path(
        "/opt/lea-tools/calendar/1.0.0/.venv/bin/khal"
    )
    assert plan.expected_vdirsyncer_executable == Path(
        "/opt/lea-tools/calendar/1.0.0/.venv/bin/vdirsyncer"
    )


def test_installation_delegates_to_existing_dispatcher(
    tmp_path: Path,
) -> None:
    """The release-candidate boundary should not duplicate install logic."""
    plan = create_calendar_toolchain_installation_plan(
        _request(tmp_path),
        _inputs(tmp_path),
    )
    record = _record(plan)
    calls: list[tuple[Any, str, bool, object]] = []

    def ownership(
        path: Path,
        owner: str,
        group: str,
    ) -> bool:
        del path, owner, group
        return False

    def installer(
        config: Any,
        *,
        display_timezone: str,
        fsync: bool,
        apply_ownership: object,
    ) -> CalendarToolchainInstallResult:
        calls.append(
            (
                config,
                display_timezone,
                fsync,
                apply_ownership,
            )
        )
        return CalendarToolchainInstallResult(
            success=True,
            already_installed=False,
            record=record,
            issues=(),
        )

    result = install_release_candidate_calendar_toolchain(
        plan,
        display_timezone="Africa/Gaborone",
        installer=installer,
        apply_ownership=ownership,
    )

    assert result.success is True
    assert result.khal_executable == plan.expected_khal_executable
    assert result.vdirsyncer_executable == (plan.expected_vdirsyncer_executable)
    assert result.record == record
    assert calls == [
        (
            plan.config,
            "Africa/Gaborone",
            True,
            ownership,
        )
    ]


def test_already_installed_state_is_preserved(
    tmp_path: Path,
) -> None:
    """Idempotent calendar results should remain visible."""
    plan = create_calendar_toolchain_installation_plan(
        _request(tmp_path),
        _inputs(tmp_path),
    )
    record = _record(plan)

    def installer(
        config: Any,
        *,
        display_timezone: str,
        fsync: bool,
        apply_ownership: object,
    ) -> CalendarToolchainInstallResult:
        del config, display_timezone, fsync, apply_ownership
        return CalendarToolchainInstallResult(
            success=True,
            already_installed=True,
            record=record,
            issues=(),
        )

    result = install_release_candidate_calendar_toolchain(
        plan,
        display_timezone="Africa/Gaborone",
        installer=installer,
    )

    assert result.success is True
    assert result.already_installed is True


def test_component_issues_are_translated(
    tmp_path: Path,
) -> None:
    """Calendar failures should become release-candidate step issues."""
    plan = create_calendar_toolchain_installation_plan(
        _request(tmp_path),
        _inputs(tmp_path),
    )
    component_issue = CalendarToolchainInstallerIssue(
        code=CalendarToolchainInstallFailureCode.LOCK_INVALID,
        message="The lock file was invalid.",
        field="requirements_lock",
        path=plan.config.requirements_lock,
    )

    def installer(
        config: Any,
        *,
        display_timezone: str,
        fsync: bool,
        apply_ownership: object,
    ) -> CalendarToolchainInstallResult:
        del config, display_timezone, fsync, apply_ownership
        return CalendarToolchainInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=(component_issue,),
        )

    result = install_release_candidate_calendar_toolchain(
        plan,
        display_timezone="Africa/Gaborone",
        installer=installer,
    )

    assert result.success is False
    assert result.issues[0].step is InstallerStepId.CALENDAR_TOOLCHAIN
    assert result.issues[0].message == "The lock file was invalid."
    assert result.issues[0].field == "requirements_lock"
    assert result.issues[0].path == plan.config.requirements_lock


def test_unexpected_managed_executable_is_rejected(
    tmp_path: Path,
) -> None:
    """Successful records must identify both exact managed executables."""
    plan = create_calendar_toolchain_installation_plan(
        _request(tmp_path),
        _inputs(tmp_path),
    )
    record = CalendarToolchainInstallationRecord(
        schema_version=2,
        component="calendar-toolchain",
        toolchain_version=plan.config.toolchain_version,
        installation_mode=CalendarToolchainInstallMode.VERIFIED_NETWORK,
        platform=plan.config.platform,
        python_version="3.13.5",
        khal_version=plan.config.khal_version,
        vdirsyncer_version=plan.config.vdirsyncer_version,
        khal_executable=tmp_path / "unexpected" / "khal",
        vdirsyncer_executable=plan.expected_vdirsyncer_executable,
        lock_or_manifest_sha256=plan.config.expected_lock_sha256,
        khal_executable_sha256=None,
        vdirsyncer_executable_sha256=None,
        smoke_test="passed",
        installed_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )

    def installer(
        config: Any,
        *,
        display_timezone: str,
        fsync: bool,
        apply_ownership: object,
    ) -> CalendarToolchainInstallResult:
        del config, display_timezone, fsync, apply_ownership
        return CalendarToolchainInstallResult(
            success=True,
            already_installed=False,
            record=record,
            issues=(),
        )

    result = install_release_candidate_calendar_toolchain(
        plan,
        display_timezone="Africa/Gaborone",
        installer=installer,
    )

    assert result.success is False
    assert result.record is None
    assert result.issues[0].path == record.khal_executable


@pytest.mark.parametrize(
    "checksum",
    (
        "A" * 64,
        "a" * 63,
        "g" * 64,
    ),
)
def test_inputs_reject_invalid_lock_checksum(
    tmp_path: Path,
    checksum: str,
) -> None:
    """The lock checksum must use canonical lower-case SHA-256 text."""
    inputs = _inputs(tmp_path)

    with pytest.raises(ValueError, match="lower-case hexadecimal"):
        ReleaseCandidateCalendarInputs(
            toolchain_version=inputs.toolchain_version,
            platform=inputs.platform,
            requirements_lock=inputs.requirements_lock,
            expected_lock_sha256=checksum,
            uv_executable=inputs.uv_executable,
            python_executable=inputs.python_executable,
            package_index_url=inputs.package_index_url,
        )
