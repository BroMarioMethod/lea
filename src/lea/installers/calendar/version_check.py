"""Finite version checks for exact calendar toolchain executables."""

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from lea.installers.calendar.contracts import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallFailureCode,
)
from lea.installers.calendar.staging import (
    CalendarToolchainStagingLayout,
)

_MAX_CAPTURED_STREAM_CHARACTERS = 20_000
_KHAL_VERSION_PATTERN = re.compile(
    r"^khal,\s+version\s+(?P<version>\S+)\s*$",
    re.IGNORECASE,
)
_VDIRSYNCER_VERSION_PATTERN = re.compile(
    r"^vdirsyncer,\s+version\s+(?P<version>\S+)\s*$",
    re.IGNORECASE,
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
class CalendarToolchainVersionStepResult:
    """Captured result of one calendar tool version command."""

    tool: str
    command: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool
    discovered_version: str | None

    def __post_init__(self) -> None:
        """Validate one immutable version-check step."""
        if not isinstance(self.tool, str) or not self.tool.strip():
            raise ValueError("tool must be non-empty.")

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

        if self.discovered_version is not None and (
            not isinstance(self.discovered_version, str)
            or not self.discovered_version.strip()
        ):
            raise ValueError("discovered_version must be non-empty when provided.")


@dataclass(frozen=True, slots=True)
class CalendarToolchainVersionCheckResult:
    """Result of checking exact khal and vdirsyncer versions."""

    passed: bool
    khal_version: str | None
    vdirsyncer_version: str | None
    steps: tuple[CalendarToolchainVersionStepResult, ...]
    issues: tuple[CalendarToolchainInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate version-check result consistency."""
        if not isinstance(self.passed, bool):
            raise TypeError("passed must be a boolean.")

        if self.passed:
            if self.khal_version is None or not self.khal_version.strip():
                raise ValueError(
                    "A passed version check must contain the khal version."
                )

            if self.vdirsyncer_version is None or not self.vdirsyncer_version.strip():
                raise ValueError(
                    "A passed version check must contain the vdirsyncer version."
                )

            if len(self.steps) != 2:
                raise ValueError(
                    "A passed version check must contain two completed steps."
                )

            if self.issues:
                raise ValueError("A passed version check must not contain issues.")

            return

        if not self.steps:
            raise ValueError(
                "A failed version check must contain at least one attempted step."
            )

        if not self.issues:
            raise ValueError("A failed version check must contain at least one issue.")


@dataclass(frozen=True, slots=True)
class _VersionCheckTarget:
    """One exact calendar tool version-check target."""

    tool: str
    executable: Path
    expected_version: str
    pattern: re.Pattern[str]
    executable_field: str
    version_field: str

    def __post_init__(self) -> None:
        """Validate one internal target."""
        if not self.tool.strip():
            raise ValueError("tool must be non-empty.")

        _validate_absolute_path(
            self.executable,
            field_name="executable",
        )

        if not self.expected_version.strip():
            raise ValueError("expected_version must be non-empty.")

        if not self.executable_field.strip():
            raise ValueError("executable_field must be non-empty.")

        if not self.version_field.strip():
            raise ValueError("version_field must be non-empty.")


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
    """Run one exact version command without shell interpretation."""
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


def validate_staged_calendar_tool_versions(
    config: CalendarToolchainInstallerConfig,
    staged: CalendarToolchainStagingLayout,
    *,
    runner: _CommandRunner = _run_command,
) -> CalendarToolchainVersionCheckResult:
    """Validate exact versions inside one private managed staging root."""
    if not isinstance(config, CalendarToolchainInstallerConfig):
        raise TypeError("config must be a CalendarToolchainInstallerConfig value.")

    if not isinstance(staged, CalendarToolchainStagingLayout):
        raise TypeError("staged must be a CalendarToolchainStagingLayout value.")

    if staged.staging_parent != config.tools_root:
        raise ValueError(
            "The staged layout does not belong to the configured tools root."
        )

    return validate_calendar_tool_versions(
        khal_executable=staged.khal_executable,
        expected_khal_version=config.khal_version,
        vdirsyncer_executable=staged.vdirsyncer_executable,
        expected_vdirsyncer_version=config.vdirsyncer_version,
        working_directory=staged.staging_root,
        timeout_seconds=config.timeout_seconds,
        runner=runner,
    )


def validate_calendar_tool_versions(
    *,
    khal_executable: Path,
    expected_khal_version: str,
    vdirsyncer_executable: Path,
    expected_vdirsyncer_version: str,
    working_directory: Path,
    timeout_seconds: float,
    runner: _CommandRunner = _run_command,
) -> CalendarToolchainVersionCheckResult:
    """Validate exact khal and vdirsyncer versions without using PATH."""
    for field_name, path in (
        ("khal_executable", khal_executable),
        ("vdirsyncer_executable", vdirsyncer_executable),
        ("working_directory", working_directory),
    ):
        _validate_absolute_path(path, field_name=field_name)

    for field_name, version in (
        ("expected_khal_version", expected_khal_version),
        ("expected_vdirsyncer_version", expected_vdirsyncer_version),
    ):
        if not isinstance(version, str) or not version.strip():
            raise ValueError(f"{field_name} must be non-empty.")

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero.")

    targets = (
        _VersionCheckTarget(
            tool="khal",
            executable=khal_executable,
            expected_version=expected_khal_version.strip(),
            pattern=_KHAL_VERSION_PATTERN,
            executable_field="khal_executable",
            version_field="khal_version",
        ),
        _VersionCheckTarget(
            tool="vdirsyncer",
            executable=vdirsyncer_executable,
            expected_version=expected_vdirsyncer_version.strip(),
            pattern=_VDIRSYNCER_VERSION_PATTERN,
            executable_field="vdirsyncer_executable",
            version_field="vdirsyncer_version",
        ),
    )

    steps: list[CalendarToolchainVersionStepResult] = []
    discovered: dict[str, str] = {}

    for target in targets:
        step, issue = _run_version_step(
            target=target,
            working_directory=working_directory,
            timeout_seconds=timeout_seconds,
            runner=runner,
        )
        steps.append(step)

        if step.discovered_version is not None:
            discovered[target.tool] = step.discovered_version

        if issue is not None:
            return CalendarToolchainVersionCheckResult(
                passed=False,
                khal_version=discovered.get("khal"),
                vdirsyncer_version=discovered.get("vdirsyncer"),
                steps=tuple(steps),
                issues=(issue,),
            )

    return CalendarToolchainVersionCheckResult(
        passed=True,
        khal_version=discovered["khal"],
        vdirsyncer_version=discovered["vdirsyncer"],
        steps=tuple(steps),
        issues=(),
    )


def _run_version_step(
    *,
    target: _VersionCheckTarget,
    working_directory: Path,
    timeout_seconds: float,
    runner: _CommandRunner,
) -> tuple[
    CalendarToolchainVersionStepResult,
    CalendarToolchainInstallerIssue | None,
]:
    """Run and validate one exact tool version command."""
    command = (str(target.executable), "--version")
    started = time.monotonic()

    try:
        completed = runner(
            command,
            cwd=working_directory,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as error:
        step = CalendarToolchainVersionStepResult(
            tool=target.tool,
            command=command,
            returncode=None,
            stdout=_normalise_stream(error.stdout),
            stderr=_normalise_stream(error.stderr),
            duration_seconds=time.monotonic() - started,
            timed_out=True,
            discovered_version=None,
        )
        issue = CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.INSTALL_TIMEOUT,
            message=(
                f"The {target.tool} version check exceeded the finite "
                "installer timeout."
            ),
            field=target.executable_field,
            path=target.executable,
        )
        return step, issue
    except OSError as error:
        step = CalendarToolchainVersionStepResult(
            tool=target.tool,
            command=command,
            returncode=127,
            stdout="",
            stderr=_bounded_stream(str(error)),
            duration_seconds=time.monotonic() - started,
            timed_out=False,
            discovered_version=None,
        )
        issue = CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.VERSION_CHECK_FAILED,
            message=(
                f"The {target.tool} version command could not be executed: "
                f"{error.strerror or type(error).__name__}."
            ),
            field=target.executable_field,
            path=target.executable,
        )
        return step, issue

    stdout = _normalise_stream(completed.stdout)
    stderr = _normalise_stream(completed.stderr)
    discovered_version = _parse_version(
        pattern=target.pattern,
        stdout=stdout,
        stderr=stderr,
    )

    step = CalendarToolchainVersionStepResult(
        tool=target.tool,
        command=command,
        returncode=completed.returncode,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=time.monotonic() - started,
        timed_out=False,
        discovered_version=discovered_version,
    )

    if completed.returncode != 0:
        return step, CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.VERSION_CHECK_FAILED,
            message=(
                f"The {target.tool} version command failed with exit status "
                f"{completed.returncode}."
            ),
            field=target.executable_field,
            path=target.executable,
        )

    if discovered_version is None:
        return step, CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.VERSION_CHECK_FAILED,
            message=(
                f"The {target.tool} version output did not match the "
                "supported command format."
            ),
            field=target.version_field,
            path=target.executable,
        )

    if discovered_version != target.expected_version:
        return step, CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.VERSION_CHECK_FAILED,
            message=(
                f"The {target.tool} version was {discovered_version}; "
                f"expected {target.expected_version}."
            ),
            field=target.version_field,
            path=target.executable,
        )

    return step, None


def _parse_version(
    *,
    pattern: re.Pattern[str],
    stdout: str,
    stderr: str,
) -> str | None:
    """Parse one tool-specific version line from either output stream."""
    for stream in (stdout, stderr):
        for line in stream.splitlines():
            match = pattern.fullmatch(line.strip())

            if match is not None:
                return match.group("version")

    return None


def _normalise_stream(
    value: str | bytes | None,
) -> str:
    """Return bounded deterministic text for captured subprocess output."""
    if value is None:
        return ""

    if isinstance(value, bytes):
        return _bounded_stream(value.decode("utf-8", errors="replace"))

    return _bounded_stream(value)


def _bounded_stream(value: str) -> str:
    """Bound retained command diagnostics."""
    if len(value) <= _MAX_CAPTURED_STREAM_CHARACTERS:
        return value

    return value[: _MAX_CAPTURED_STREAM_CHARACTERS - 3] + "..."


def _validate_absolute_path(
    path: Path,
    *,
    field_name: str,
) -> None:
    """Validate one absolute pathlib path."""
    if not isinstance(path, Path):
        raise TypeError(f"{field_name} must be a pathlib.Path value.")

    if not path.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path.")
