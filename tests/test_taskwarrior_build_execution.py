"""Tests for finite Taskwarrior source-build execution."""

import stat
import subprocess
from pathlib import Path
from typing import Any

from lea.installers.taskwarrior import (
    TaskwarriorBuildTools,
    TaskwarriorInstallFailureCode,
    TaskwarriorSourceBuildPlan,
    create_taskwarrior_source_build_plan,
    execute_taskwarrior_source_build,
)


def _executable(
    tmp_path: Path,
    name: str,
) -> Path:
    """Create one executable test-double path."""
    path = tmp_path / name
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _plan(
    tmp_path: Path,
) -> TaskwarriorSourceBuildPlan:
    """Return one deterministic source-build plan."""
    source = tmp_path / "source"
    source.mkdir()

    tools = TaskwarriorBuildTools(
        cmake=_executable(tmp_path, "cmake"),
        cxx=_executable(tmp_path, "c++"),
        make=_executable(tmp_path, "make"),
        cargo=_executable(tmp_path, "cargo"),
        rustc=_executable(tmp_path, "rustc"),
        pkg_config=_executable(tmp_path, "pkg-config"),
    )

    return create_taskwarrior_source_build_plan(
        tools=tools,
        source_root=source,
        cmake_build_directory=tmp_path / "cmake-build",
        installation_prefix=tmp_path / "install",
        build_concurrency=2,
        timeout_seconds=30.0,
    )


def test_executes_configure_build_and_install_in_order(
    tmp_path: Path,
) -> None:
    """A successful run should capture all three phases."""
    plan = _plan(tmp_path)
    calls: list[tuple[str, ...]] = []

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)

        if command == plan.install_command:
            executable = plan.installation_prefix / "bin" / "task"
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.write_text(
                "#!/bin/sh\nexit 0\n",
                encoding="utf-8",
            )
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"{len(calls)} stdout",
            stderr=f"{len(calls)} stderr",
        )

    result = execute_taskwarrior_source_build(
        plan,
        runner=runner,
    )

    assert result.success is True
    assert result.installation_prefix == plan.installation_prefix
    assert calls == [
        plan.configure_command,
        plan.build_command,
        plan.install_command,
    ]
    assert tuple(step.phase for step in result.steps) == (
        "configure",
        "build",
        "install",
    )


def test_non_zero_configure_stops_later_phases(
    tmp_path: Path,
) -> None:
    """A configure failure should stop before build and install."""
    plan = _plan(tmp_path)
    calls: list[tuple[str, ...]] = []

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            2,
            stdout="configure output",
            stderr="configure failed",
        )

    result = execute_taskwarrior_source_build(
        plan,
        runner=runner,
    )

    assert result.success is False
    assert calls == [plan.configure_command]
    assert result.issues[0].code is TaskwarriorInstallFailureCode.BUILD_FAILED
    assert result.steps[0].returncode == 2
    assert result.steps[0].stderr == "configure failed"


def test_timeout_returns_build_timeout(
    tmp_path: Path,
) -> None:
    """A finite command timeout should be reported explicitly."""
    plan = _plan(tmp_path)

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(
            command,
            30.0,
            output=b"partial stdout",
            stderr=b"partial stderr",
        )

    result = execute_taskwarrior_source_build(
        plan,
        runner=runner,
    )

    assert result.success is False
    assert result.issues[0].code is TaskwarriorInstallFailureCode.BUILD_TIMEOUT
    assert result.steps[0].timed_out is True
    assert result.steps[0].returncode is None
    assert result.steps[0].stdout == "partial stdout"
    assert result.steps[0].stderr == "partial stderr"


def test_os_error_is_captured_without_shell_fallback(
    tmp_path: Path,
) -> None:
    """Executable failures should become structured build issues."""
    plan = _plan(tmp_path)

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        raise PermissionError("denied")

    result = execute_taskwarrior_source_build(
        plan,
        runner=runner,
    )

    assert result.success is False
    assert result.issues[0].code is TaskwarriorInstallFailureCode.BUILD_FAILED
    assert result.steps[0].returncode == 127


def test_missing_installed_executable_fails_closed(
    tmp_path: Path,
) -> None:
    """Successful commands must still produce an executable."""
    plan = _plan(tmp_path)

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

    result = execute_taskwarrior_source_build(
        plan,
        runner=runner,
    )

    assert result.success is False
    assert len(result.steps) == 3
    assert result.issues[0].code is TaskwarriorInstallFailureCode.BUILD_FAILED


def test_runner_receives_non_shell_subprocess_arguments(
    tmp_path: Path,
) -> None:
    """Execution should use exact arguments and the source working tree."""
    plan = _plan(tmp_path)
    received: list[dict[str, Any]] = []

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        received.append({"command": command, **kwargs})

        if command == plan.install_command:
            executable = plan.installation_prefix / "bin" / "task"
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.write_text(
                "#!/bin/sh\nexit 0\n",
                encoding="utf-8",
            )
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

        return subprocess.CompletedProcess(
            command,
            0,
            stdout="",
            stderr="",
        )

    result = execute_taskwarrior_source_build(
        plan,
        runner=runner,
    )

    assert result.success is True

    for call in received:
        assert call["cwd"] == plan.source_root
        assert call["capture_output"] is True
        assert call["text"] is True
        assert call["timeout"] == plan.timeout_seconds
        assert call["check"] is False
        assert "shell" not in call
