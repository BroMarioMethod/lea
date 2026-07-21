"""Finite, non-shell execution of Taskwarrior source-build plans."""

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from lea.installers.taskwarrior.build_plan import (
    TaskwarriorSourceBuildPlan,
)
from lea.installers.taskwarrior.contracts import (
    TaskwarriorInstallerIssue,
    TaskwarriorInstallFailureCode,
)


class _CommandRunner(Protocol):
    """Callable contract for one subprocess invocation."""

    def __call__(
        self,
        command: tuple[str, ...],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        timeout: float,
        check: bool,
    ) -> subprocess.CompletedProcess[str]: ...


@dataclass(frozen=True, slots=True)
class TaskwarriorBuildStepResult:
    """Captured result of one source-build command."""

    phase: str
    command: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool

    def __post_init__(self) -> None:
        """Validate one build-step result."""
        if not self.phase.strip():
            raise ValueError("phase must be non-empty.")

        if not self.command:
            raise ValueError("command must not be empty.")

        if self.duration_seconds < 0:
            raise ValueError("duration_seconds must not be negative.")

        if self.timed_out and self.returncode is not None:
            raise ValueError("A timed-out step must not contain a return code.")

        if not self.timed_out and self.returncode is None:
            raise ValueError("A completed step must contain a return code.")


@dataclass(frozen=True, slots=True)
class TaskwarriorSourceBuildExecutionResult:
    """Result of executing configure, build and install phases."""

    success: bool
    installation_prefix: Path | None
    steps: tuple[TaskwarriorBuildStepResult, ...]
    issues: tuple[TaskwarriorInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate source-build execution consistency."""
        if self.success:
            if self.installation_prefix is None:
                raise ValueError(
                    "A successful build must contain its installation prefix."
                )

            if self.issues:
                raise ValueError("A successful build must not contain issues.")

            if len(self.steps) != 3:
                raise ValueError(
                    "A successful build must contain three completed steps."
                )

            return

        if self.installation_prefix is not None:
            raise ValueError("A failed build must not contain an installation prefix.")

        if not self.steps:
            raise ValueError("A failed build must contain at least one attempted step.")

        if not self.issues:
            raise ValueError("A failed build must contain at least one issue.")


def _run_command(
    command: tuple[str, ...],
    *,
    cwd: Path,
    capture_output: bool,
    text: bool,
    timeout: float,
    check: bool,
) -> subprocess.CompletedProcess[str]:
    """Run one exact command through subprocess without a shell."""
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=capture_output,
        text=text,
        timeout=timeout,
        check=check,
    )


def execute_taskwarrior_source_build(
    plan: TaskwarriorSourceBuildPlan,
    *,
    runner: _CommandRunner = _run_command,
) -> TaskwarriorSourceBuildExecutionResult:
    """Execute one deterministic Taskwarrior source-build plan."""
    if not isinstance(plan, TaskwarriorSourceBuildPlan):
        raise TypeError("plan must be a TaskwarriorSourceBuildPlan value.")

    plan.cmake_build_directory.mkdir(
        mode=0o750,
        parents=True,
        exist_ok=True,
    )
    plan.installation_prefix.mkdir(
        mode=0o750,
        parents=True,
        exist_ok=True,
    )

    steps: list[TaskwarriorBuildStepResult] = []

    for phase, command in (
        ("configure", plan.configure_command),
        ("build", plan.build_command),
        ("install", plan.install_command),
    ):
        step, issue = _run_step(
            phase=phase,
            command=command,
            cwd=plan.source_root,
            timeout_seconds=plan.timeout_seconds,
            runner=runner,
        )
        steps.append(step)

        if issue is not None:
            return TaskwarriorSourceBuildExecutionResult(
                success=False,
                installation_prefix=None,
                steps=tuple(steps),
                issues=(issue,),
            )

    executable = plan.installation_prefix / "bin" / "task"

    if not executable.is_file():
        return TaskwarriorSourceBuildExecutionResult(
            success=False,
            installation_prefix=None,
            steps=tuple(steps),
            issues=(
                TaskwarriorInstallerIssue(
                    code=TaskwarriorInstallFailureCode.BUILD_FAILED,
                    message=(
                        "The Taskwarrior build completed without producing "
                        "the expected executable."
                    ),
                    field="installation_prefix",
                    path=plan.installation_prefix,
                ),
            ),
        )

    if not executable.stat().st_mode & 0o111:
        return TaskwarriorSourceBuildExecutionResult(
            success=False,
            installation_prefix=None,
            steps=tuple(steps),
            issues=(
                TaskwarriorInstallerIssue(
                    code=TaskwarriorInstallFailureCode.BUILD_FAILED,
                    message=("The built Taskwarrior executable is not executable."),
                    field="installation_prefix",
                    path=executable,
                ),
            ),
        )

    return TaskwarriorSourceBuildExecutionResult(
        success=True,
        installation_prefix=plan.installation_prefix,
        steps=tuple(steps),
        issues=(),
    )


def _run_step(
    *,
    phase: str,
    command: tuple[str, ...],
    cwd: Path,
    timeout_seconds: float,
    runner: _CommandRunner,
) -> tuple[
    TaskwarriorBuildStepResult,
    TaskwarriorInstallerIssue | None,
]:
    """Run one finite build command and capture its diagnostics."""
    started = time.monotonic()

    try:
        completed = runner(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        duration = time.monotonic() - started
        stdout = _normalise_stream(error.stdout)
        stderr = _normalise_stream(error.stderr)
        step = TaskwarriorBuildStepResult(
            phase=phase,
            command=command,
            returncode=None,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
            timed_out=True,
        )
        issue = TaskwarriorInstallerIssue(
            code=TaskwarriorInstallFailureCode.BUILD_TIMEOUT,
            message=(
                f"The Taskwarrior {phase} phase exceeded the finite build timeout."
            ),
            field="build_directory",
            path=cwd,
        )
        return step, issue
    except OSError as error:
        duration = time.monotonic() - started
        step = TaskwarriorBuildStepResult(
            phase=phase,
            command=command,
            returncode=127,
            stdout="",
            stderr=str(error),
            duration_seconds=duration,
            timed_out=False,
        )
        issue = TaskwarriorInstallerIssue(
            code=TaskwarriorInstallFailureCode.BUILD_FAILED,
            message=(
                f"The Taskwarrior {phase} command could not be executed: "
                f"{error.strerror or type(error).__name__}."
            ),
            field="build_directory",
            path=cwd,
        )
        return step, issue

    duration = time.monotonic() - started
    step = TaskwarriorBuildStepResult(
        phase=phase,
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=duration,
        timed_out=False,
    )

    if completed.returncode != 0:
        issue = TaskwarriorInstallerIssue(
            code=TaskwarriorInstallFailureCode.BUILD_FAILED,
            message=(
                f"The Taskwarrior {phase} phase failed with exit status "
                f"{completed.returncode}."
            ),
            field="build_directory",
            path=cwd,
        )
        return step, issue

    return step, None


def _normalise_stream(
    value: str | bytes | None,
) -> str:
    """Normalise timeout output to text."""
    if value is None:
        return ""

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    return value
