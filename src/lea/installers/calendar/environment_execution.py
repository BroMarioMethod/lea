"""Finite execution of deterministic calendar environment plans."""

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from lea.installers.calendar.contracts import (
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallFailureCode,
)
from lea.installers.calendar.environment_plan import (
    CalendarToolchainEnvironmentPlan,
)


class _CommandRunner(Protocol):
    """Callable contract for one exact subprocess invocation."""

    def __call__(
        self,
        command: tuple[str, ...],
        *,
        cwd: Path,
        stdin: int,
        capture_output: bool,
        text: bool,
        timeout: float,
        check: bool,
        shell: bool,
    ) -> subprocess.CompletedProcess[str]: ...


@dataclass(frozen=True, slots=True)
class CalendarToolchainEnvironmentStepResult:
    """Captured result of one calendar environment command."""

    phase: str
    command: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool

    def __post_init__(self) -> None:
        """Validate one execution-step result."""
        if not isinstance(self.phase, str) or not self.phase.strip():
            raise ValueError("phase must be non-empty.")

        if not isinstance(self.command, tuple) or not self.command:
            raise ValueError("command must be a non-empty tuple.")

        if any(
            not isinstance(argument, str) or not argument for argument in self.command
        ):
            raise ValueError("command arguments must be non-empty strings.")

        if self.duration_seconds < 0:
            raise ValueError("duration_seconds must not be negative.")

        if self.timed_out and self.returncode is not None:
            raise ValueError("A timed-out step must not contain a return code.")

        if not self.timed_out and self.returncode is None:
            raise ValueError("A completed step must contain a return code.")


@dataclass(frozen=True, slots=True)
class CalendarToolchainEnvironmentExecutionResult:
    """Result of creating and populating one staged calendar environment."""

    success: bool
    environment_root: Path | None
    steps: tuple[CalendarToolchainEnvironmentStepResult, ...]
    issues: tuple[CalendarToolchainInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate execution-result consistency."""
        if not isinstance(self.success, bool):
            raise TypeError("success must be a boolean.")

        if self.success:
            if self.environment_root is None:
                raise ValueError(
                    "A successful execution must contain its environment root."
                )

            if self.issues:
                raise ValueError("A successful execution must not contain issues.")

            if len(self.steps) != 2:
                raise ValueError(
                    "A successful execution must contain two completed steps."
                )

            return

        if self.environment_root is not None:
            raise ValueError("A failed execution must not contain an environment root.")

        if not self.steps:
            raise ValueError(
                "A failed execution must contain at least one attempted step."
            )

        if not self.issues:
            raise ValueError("A failed execution must contain at least one issue.")


def _run_command(
    command: tuple[str, ...],
    *,
    cwd: Path,
    stdin: int,
    capture_output: bool,
    text: bool,
    timeout: float,
    check: bool,
    shell: bool,
) -> subprocess.CompletedProcess[str]:
    """Run one exact command without shell interpretation."""
    return subprocess.run(
        command,
        cwd=cwd,
        stdin=stdin,
        capture_output=capture_output,
        text=text,
        timeout=timeout,
        check=check,
        shell=shell,
    )


def execute_calendar_toolchain_environment_plan(
    plan: CalendarToolchainEnvironmentPlan,
    *,
    runner: _CommandRunner = _run_command,
) -> CalendarToolchainEnvironmentExecutionResult:
    """Execute environment creation and locked package installation."""
    if not isinstance(plan, CalendarToolchainEnvironmentPlan):
        raise TypeError("plan must be a CalendarToolchainEnvironmentPlan value.")

    steps: list[CalendarToolchainEnvironmentStepResult] = []

    for phase, command, failure_code in (
        (
            "create-environment",
            plan.create_environment_command,
            CalendarToolchainInstallFailureCode.ENVIRONMENT_CREATION_FAILED,
        ),
        (
            "install-packages",
            plan.install_packages_command,
            CalendarToolchainInstallFailureCode.PACKAGE_INSTALL_FAILED,
        ),
    ):
        step, issue = _run_step(
            phase=phase,
            command=command,
            failure_code=failure_code,
            plan=plan,
            runner=runner,
        )
        steps.append(step)

        if issue is not None:
            return CalendarToolchainEnvironmentExecutionResult(
                success=False,
                environment_root=None,
                steps=tuple(steps),
                issues=(issue,),
            )

    executable_issues = _validate_expected_executables(plan)

    if executable_issues:
        return CalendarToolchainEnvironmentExecutionResult(
            success=False,
            environment_root=None,
            steps=tuple(steps),
            issues=executable_issues,
        )

    return CalendarToolchainEnvironmentExecutionResult(
        success=True,
        environment_root=plan.environment_root,
        steps=tuple(steps),
        issues=(),
    )


def _run_step(
    *,
    phase: str,
    command: tuple[str, ...],
    failure_code: CalendarToolchainInstallFailureCode,
    plan: CalendarToolchainEnvironmentPlan,
    runner: _CommandRunner,
) -> tuple[
    CalendarToolchainEnvironmentStepResult,
    CalendarToolchainInstallerIssue | None,
]:
    """Run one finite environment command and capture diagnostics."""
    started = time.monotonic()

    try:
        completed = runner(
            command,
            cwd=plan.working_directory,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=plan.timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as error:
        step = CalendarToolchainEnvironmentStepResult(
            phase=phase,
            command=command,
            returncode=None,
            stdout=_normalise_stream(error.stdout),
            stderr=_normalise_stream(error.stderr),
            duration_seconds=time.monotonic() - started,
            timed_out=True,
        )
        issue = CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.INSTALL_TIMEOUT,
            message=(
                f"The calendar {phase} phase exceeded the finite installation timeout."
            ),
            field="environment_root",
            path=plan.environment_root,
        )
        return step, issue
    except OSError as error:
        step = CalendarToolchainEnvironmentStepResult(
            phase=phase,
            command=command,
            returncode=127,
            stdout="",
            stderr=str(error),
            duration_seconds=time.monotonic() - started,
            timed_out=False,
        )
        issue = CalendarToolchainInstallerIssue(
            code=failure_code,
            message=(
                f"The calendar {phase} command could not be executed: "
                f"{error.strerror or type(error).__name__}."
            ),
            field="environment_root",
            path=plan.environment_root,
        )
        return step, issue

    step = CalendarToolchainEnvironmentStepResult(
        phase=phase,
        command=command,
        returncode=completed.returncode,
        stdout=_normalise_stream(completed.stdout),
        stderr=_normalise_stream(completed.stderr),
        duration_seconds=time.monotonic() - started,
        timed_out=False,
    )

    if completed.returncode != 0:
        issue = CalendarToolchainInstallerIssue(
            code=failure_code,
            message=(
                f"The calendar {phase} phase failed with exit status "
                f"{completed.returncode}."
            ),
            field="environment_root",
            path=plan.environment_root,
        )
        return step, issue

    return step, None


def _validate_expected_executables(
    plan: CalendarToolchainEnvironmentPlan,
) -> tuple[CalendarToolchainInstallerIssue, ...]:
    """Verify that successful commands produced the expected entry points."""
    issues: list[CalendarToolchainInstallerIssue] = []

    for field_name, executable in (
        ("environment_python", plan.environment_python),
        ("khal_executable", plan.environment_root / "bin" / "khal"),
        (
            "vdirsyncer_executable",
            plan.environment_root / "bin" / "vdirsyncer",
        ),
    ):
        issue = _inspect_expected_executable(
            executable,
            field_name=field_name,
        )

        if issue is not None:
            issues.append(issue)

    return tuple(issues)


def _inspect_expected_executable(
    executable: Path,
    *,
    field_name: str,
) -> CalendarToolchainInstallerIssue | None:
    """Inspect one expected staged command without invoking it."""
    try:
        if not executable.exists():
            return CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.PACKAGE_INSTALL_FAILED,
                message=(f"The calendar environment did not produce {field_name}."),
                field=field_name,
                path=executable,
            )

        if not executable.is_file():
            return CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.PACKAGE_INSTALL_FAILED,
                message=(f"The expected {field_name} path is not a regular file."),
                field=field_name,
                path=executable,
            )

        if not executable.stat().st_mode & 0o111:
            return CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.PACKAGE_INSTALL_FAILED,
                message=f"The expected {field_name} path is not executable.",
                field=field_name,
                path=executable,
            )
    except OSError:
        return CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.PACKAGE_INSTALL_FAILED,
            message=f"The expected {field_name} path could not be inspected.",
            field=field_name,
            path=executable,
        )

    return None


def _normalise_stream(
    value: str | bytes | None,
) -> str:
    """Return deterministic text for captured subprocess output."""
    if value is None:
        return ""

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    return value
