"""Tests for finite calendar environment-plan execution."""

import hashlib
import stat
import subprocess
from pathlib import Path
from typing import Any

from lea.installers.calendar import (
    CalendarToolchainEnvironmentPlan,
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
    create_calendar_toolchain_environment_plan,
    create_calendar_toolchain_staging,
    execute_calendar_toolchain_environment_plan,
)


def _make_executable(path: Path) -> None:
    """Create one executable test script."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _plan(
    tmp_path: Path,
) -> tuple[CalendarToolchainInstallerConfig, CalendarToolchainEnvironmentPlan]:
    """Return one staged verified-network environment plan."""
    uv_executable = tmp_path / "uv"
    python_executable = tmp_path / "python3"
    requirements_lock = tmp_path / "calendar-requirements.txt"
    payload = b"khal==0.11.4\nvdirsyncer==0.19.3\n"

    _make_executable(uv_executable)
    _make_executable(python_executable)
    requirements_lock.write_bytes(payload)

    config = CalendarToolchainInstallerConfig(
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
        package_index_url="https://packages.example.invalid/simple",
        timeout_seconds=30.0,
    )

    staging = create_calendar_toolchain_staging(config)
    assert staging.staged is not None

    return (
        config,
        create_calendar_toolchain_environment_plan(
            config,
            staging.staged,
        ),
    )


def _create_expected_environment(
    plan: CalendarToolchainEnvironmentPlan,
) -> None:
    """Create all expected staged executable paths."""
    _make_executable(plan.environment_python)
    _make_executable(plan.environment_root / "bin" / "khal")
    _make_executable(plan.environment_root / "bin" / "vdirsyncer")


def test_executes_environment_and_install_commands_in_order(
    tmp_path: Path,
) -> None:
    """Successful execution should run both exact commands in order."""
    config, plan = _plan(tmp_path)
    calls: list[dict[str, Any]] = []

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, **kwargs})

        if command == plan.create_environment_command:
            _make_executable(plan.environment_python)

        if command == plan.install_packages_command:
            _make_executable(plan.environment_root / "bin" / "khal")
            _make_executable(plan.environment_root / "bin" / "vdirsyncer")

        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"{len(calls)} stdout",
            stderr=f"{len(calls)} stderr",
        )

    result = execute_calendar_toolchain_environment_plan(
        plan,
        runner=runner,
    )

    assert result.success is True
    assert result.environment_root == plan.environment_root
    assert tuple(step.phase for step in result.steps) == (
        "create-environment",
        "install-packages",
    )
    assert [call["command"] for call in calls] == [
        plan.create_environment_command,
        plan.install_packages_command,
    ]

    for call in calls:
        assert call["cwd"] == plan.working_directory
        assert call["stdin"] == subprocess.DEVNULL
        assert call["capture_output"] is True
        assert call["text"] is True
        assert call["timeout"] == plan.timeout_seconds
        assert call["check"] is False
        assert call["shell"] is False

    assert not (config.tools_root / config.toolchain_version).exists()


def test_environment_creation_failure_stops_package_install(
    tmp_path: Path,
) -> None:
    """A failed venv command should stop before package installation."""
    _config, plan = _plan(tmp_path)
    calls: list[tuple[str, ...]] = []

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            2,
            stdout="create output",
            stderr="create failed",
        )

    result = execute_calendar_toolchain_environment_plan(
        plan,
        runner=runner,
    )

    assert result.success is False
    assert calls == [plan.create_environment_command]
    assert (
        result.issues[0].code
        is CalendarToolchainInstallFailureCode.ENVIRONMENT_CREATION_FAILED
    )
    assert result.steps[0].returncode == 2
    assert result.steps[0].stderr == "create failed"


def test_package_install_failure_is_distinct(
    tmp_path: Path,
) -> None:
    """A failed package phase should retain its separate failure code."""
    _config, plan = _plan(tmp_path)
    calls: list[tuple[str, ...]] = []

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)

        if command == plan.create_environment_command:
            _make_executable(plan.environment_python)
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="created",
                stderr="",
            )

        return subprocess.CompletedProcess(
            command,
            3,
            stdout="install output",
            stderr="install failed",
        )

    result = execute_calendar_toolchain_environment_plan(
        plan,
        runner=runner,
    )

    assert result.success is False
    assert calls == [
        plan.create_environment_command,
        plan.install_packages_command,
    ]
    assert (
        result.issues[0].code
        is CalendarToolchainInstallFailureCode.PACKAGE_INSTALL_FAILED
    )
    assert result.steps[-1].returncode == 3


def test_timeout_preserves_partial_output(
    tmp_path: Path,
) -> None:
    """A finite timeout should stop execution and retain diagnostics."""
    _config, plan = _plan(tmp_path)

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(
            command,
            plan.timeout_seconds,
            output=b"partial stdout",
            stderr=b"partial stderr",
        )

    result = execute_calendar_toolchain_environment_plan(
        plan,
        runner=runner,
    )

    assert result.success is False
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.INSTALL_TIMEOUT
    assert result.steps[0].timed_out is True
    assert result.steps[0].returncode is None
    assert result.steps[0].stdout == "partial stdout"
    assert result.steps[0].stderr == "partial stderr"


def test_os_error_uses_phase_specific_failure_code(
    tmp_path: Path,
) -> None:
    """Executable launch failures should become structured issues."""
    _config, plan = _plan(tmp_path)

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        raise PermissionError("denied")

    result = execute_calendar_toolchain_environment_plan(
        plan,
        runner=runner,
    )

    assert result.success is False
    assert (
        result.issues[0].code
        is CalendarToolchainInstallFailureCode.ENVIRONMENT_CREATION_FAILED
    )
    assert result.steps[0].returncode == 127


def test_successful_commands_without_expected_tools_fail_closed(
    tmp_path: Path,
) -> None:
    """Exit status zero must still produce all required entry points."""
    _config, plan = _plan(tmp_path)

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="ok",
            stderr="",
        )

    result = execute_calendar_toolchain_environment_plan(
        plan,
        runner=runner,
    )

    assert result.success is False
    assert len(result.steps) == 2
    assert len(result.issues) == 3
    assert all(
        issue.code is CalendarToolchainInstallFailureCode.PACKAGE_INSTALL_FAILED
        for issue in result.issues
    )
    assert {issue.field for issue in result.issues} == {
        "environment_python",
        "khal_executable",
        "vdirsyncer_executable",
    }


def test_non_executable_installed_tool_fails_closed(
    tmp_path: Path,
) -> None:
    """Installed entry points must retain execute permission."""
    _config, plan = _plan(tmp_path)

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        if command == plan.install_packages_command:
            _create_expected_environment(plan)
            vdirsyncer = plan.environment_root / "bin" / "vdirsyncer"
            vdirsyncer.chmod(vdirsyncer.stat().st_mode & ~0o111)

        return subprocess.CompletedProcess(
            command,
            0,
            stdout="ok",
            stderr="",
        )

    result = execute_calendar_toolchain_environment_plan(
        plan,
        runner=runner,
    )

    assert result.success is False
    assert any(
        issue.code is CalendarToolchainInstallFailureCode.PACKAGE_INSTALL_FAILED
        and issue.field == "vdirsyncer_executable"
        for issue in result.issues
    )
