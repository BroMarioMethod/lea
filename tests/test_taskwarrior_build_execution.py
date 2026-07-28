"""Tests for finite Taskwarrior source-build execution."""

import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

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


class RecordingBuildProgress:
    """Record Taskwarrior build progress events."""

    def __init__(self) -> None:
        self.details: list[str] = []
        self.heartbeats: list[tuple[str, float]] = []
        self.outputs: list[str] = []

    def heartbeat(
        self,
        message: str,
        *,
        elapsed_seconds: float,
    ) -> None:
        self.heartbeats.append((message, elapsed_seconds))

    def detail(
        self,
        message: str,
    ) -> None:
        self.details.append(message)

    def output(
        self,
        text: str,
    ) -> None:
        self.outputs.append(text)


def test_production_runner_streams_output_without_replaying_it(
    tmp_path: Path,
) -> None:
    """Production execution should stream each output fragment once."""
    plan = _plan(tmp_path)
    progress = RecordingBuildProgress()

    script = tmp_path / "stream-build.py"
    script.write_text(
        (
            "from pathlib import Path\n"
            "import os\n"
            "import sys\n"
            "command = sys.argv[1]\n"
            "prefix = Path(sys.argv[2])\n"
            "print(f'{command} stdout', flush=True)\n"
            "print(f'{command} stderr', file=sys.stderr, flush=True)\n"
            "if command == 'install':\n"
            "    executable = prefix / 'bin' / 'task'\n"
            "    executable.parent.mkdir(parents=True, exist_ok=True)\n"
            "    executable.write_text('#!/bin/sh\\\\nexit 0\\\\n')\n"
            "    executable.chmod(0o750)\n"
        ),
        encoding="utf-8",
    )

    import sys
    from dataclasses import replace

    streaming_plan = replace(
        plan,
        configure_command=(
            sys.executable,
            str(script),
            "configure",
            str(plan.installation_prefix),
        ),
        build_command=(
            sys.executable,
            str(script),
            "build",
            str(plan.installation_prefix),
        ),
        install_command=(
            sys.executable,
            str(script),
            "install",
            str(plan.installation_prefix),
        ),
    )

    result = execute_taskwarrior_source_build(
        streaming_plan,
        progress=progress,
    )

    assert result.success is True
    rendered = "".join(progress.outputs)
    assert rendered.count("configure stdout") == 1
    assert rendered.count("configure stderr") == 1
    assert rendered.count("build stdout") == 1
    assert rendered.count("install stderr") == 1
    assert result.steps[0].stdout == "configure stdout\n"
    assert result.steps[0].stderr == "configure stderr\n"


def test_production_runner_times_out_and_retains_partial_output(
    tmp_path: Path,
) -> None:
    """A timed-out production process should be stopped and diagnosed."""
    plan = _plan(tmp_path)
    progress = RecordingBuildProgress()

    script = tmp_path / "slow-build.py"
    script.write_text(
        (
            "import os\n"
            "import sys\n"
            "import time\n"
            "print(f'pid={os.getpid()}', flush=True)\n"
            "print('partial stdout', flush=True)\n"
            "print('partial stderr', file=sys.stderr, flush=True)\n"
            "time.sleep(30)\n"
        ),
        encoding="utf-8",
    )

    import sys
    from dataclasses import replace

    timed_plan = replace(
        plan,
        configure_command=(sys.executable, str(script)),
        timeout_seconds=0.25,
    )

    started = time.monotonic()
    result = execute_taskwarrior_source_build(
        timed_plan,
        progress=progress,
    )
    duration = time.monotonic() - started

    assert result.success is False
    assert duration < 8
    assert result.issues[0].code is TaskwarriorInstallFailureCode.BUILD_TIMEOUT
    assert result.steps[0].timed_out is True
    assert "partial stdout" in result.steps[0].stdout
    assert "partial stderr" in result.steps[0].stderr
    assert "partial stdout" in "".join(progress.outputs)

    pid_line = next(
        line for line in result.steps[0].stdout.splitlines() if line.startswith("pid=")
    )
    pid = int(pid_line.removeprefix("pid="))

    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_streaming_runner_emits_periodic_heartbeats(
    tmp_path: Path,
) -> None:
    """A long-running production command should emit periodic heartbeats."""
    from lea.installers.taskwarrior import build_execution

    progress = RecordingBuildProgress()
    script = tmp_path / "heartbeat.py"
    script.write_text(
        ("import time\ntime.sleep(0.35)\n"),
        encoding="utf-8",
    )

    completed = build_execution._run_streaming_command(
        (sys.executable, str(script)),
        cwd=tmp_path,
        timeout=5.0,
        progress=progress,
        phase="build",
        started=time.monotonic(),
        heartbeat_interval_seconds=0.1,
    )

    assert completed.returncode == 0
    assert len(progress.heartbeats) >= 2
    assert all(
        "Taskwarrior build phase is still running." in message
        for message, _elapsed in progress.heartbeats
    )
    assert all(elapsed_seconds > 0 for _message, elapsed_seconds in progress.heartbeats)


def test_streaming_runner_bounds_retained_output_but_streams_all(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retained diagnostics should be bounded without truncating live output."""
    from lea.installers.taskwarrior import build_execution

    monkeypatch.setattr(
        build_execution,
        "_MAX_CAPTURED_STREAM_CHARACTERS",
        20,
    )

    progress = RecordingBuildProgress()
    script = tmp_path / "large-output.py"
    script.write_text(
        (
            "import sys\n"
            "print('x' * 50, flush=True)\n"
            "print('y' * 50, file=sys.stderr, flush=True)\n"
        ),
        encoding="utf-8",
    )

    completed = build_execution._run_streaming_command(
        (sys.executable, str(script)),
        cwd=tmp_path,
        timeout=5.0,
        progress=progress,
        phase="build",
        started=time.monotonic(),
        heartbeat_interval_seconds=1.0,
    )

    streamed = "".join(progress.outputs)

    assert completed.returncode == 0
    assert len(completed.stdout) == 20
    assert len(completed.stderr) == 20
    assert "x" * 50 in streamed
    assert "y" * 50 in streamed
