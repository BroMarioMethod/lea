"""Finite Python-version inspection for calendar toolchains."""

import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lea.installers.calendar.contracts import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallFailureCode,
)
from lea.installers.calendar.staging import (
    CalendarToolchainStagingLayout,
)

_MAX_CAPTURED_STREAM_CHARACTERS = 20_000
_PYTHON_VERSION_PATTERN = re.compile(r"^(?P<version>[0-9]+\.[0-9]+\.[0-9]+)$")
_VERSION_SCRIPT = (
    "import sys; print('.'.join(str(part) for part in sys.version_info[:3]))"
)

type CalendarPythonVersionRunner = Callable[
    ...,
    subprocess.CompletedProcess[str],
]


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
    """Run one exact Python-version command."""
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


@dataclass(frozen=True, slots=True)
class CalendarToolchainPythonVersionResult:
    """Result of inspecting one exact Python executable."""

    passed: bool
    version: str | None
    command: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool
    issues: tuple[CalendarToolchainInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate immutable result consistency."""
        if not isinstance(self.passed, bool):
            raise TypeError("passed must be a boolean.")

        if not isinstance(self.command, tuple) or not self.command:
            raise ValueError("command must be a non-empty tuple.")

        if any(
            not isinstance(argument, str) or not argument for argument in self.command
        ):
            raise ValueError("command arguments must be non-empty strings.")

        if self.duration_seconds < 0:
            raise ValueError("duration_seconds must not be negative.")

        if self.timed_out and self.returncode is not None:
            raise ValueError(
                "A timed-out version check must not contain a return code."
            )

        if not self.timed_out and self.returncode is None:
            raise ValueError("A completed version check must contain a return code.")

        if self.passed:
            if self.version is None:
                raise ValueError(
                    "A passed Python-version result must contain a version."
                )

            if self.returncode != 0 or self.timed_out:
                raise ValueError(
                    "A passed Python-version result must complete normally."
                )

            if self.issues:
                raise ValueError(
                    "A passed Python-version result must not contain issues."
                )

            return

        if self.version is not None:
            raise ValueError(
                "A failed Python-version result must not expose a version."
            )

        if not self.issues:
            raise ValueError("A failed Python-version result must contain issues.")


def inspect_staged_calendar_python_version(
    config: CalendarToolchainInstallerConfig,
    staged: CalendarToolchainStagingLayout,
    *,
    runner: CalendarPythonVersionRunner = _run_command,
) -> CalendarToolchainPythonVersionResult:
    """Inspect the exact Python executable inside managed staging."""
    if not isinstance(config, CalendarToolchainInstallerConfig):
        raise TypeError("config must be a CalendarToolchainInstallerConfig value.")

    if not isinstance(staged, CalendarToolchainStagingLayout):
        raise TypeError("staged must be a CalendarToolchainStagingLayout value.")

    if staged.staging_parent != config.tools_root:
        raise ValueError(
            "The staged layout does not belong to the configured tools root."
        )

    return inspect_calendar_python_version(
        python_executable=staged.environment_root / "bin" / "python",
        working_directory=staged.toolchain_root,
        timeout_seconds=config.timeout_seconds,
        runner=runner,
    )


def inspect_calendar_python_version(
    *,
    python_executable: Path,
    working_directory: Path,
    timeout_seconds: float,
    runner: CalendarPythonVersionRunner = _run_command,
) -> CalendarToolchainPythonVersionResult:
    """Inspect one exact Python executable without shell interpretation."""
    _validate_absolute_path(
        python_executable,
        field_name="python_executable",
    )
    _validate_absolute_path(
        working_directory,
        field_name="working_directory",
    )

    if isinstance(timeout_seconds, bool) or not isinstance(
        timeout_seconds,
        (int, float),
    ):
        raise TypeError("timeout_seconds must be a number.")

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero.")

    command = (
        str(python_executable),
        "-c",
        _VERSION_SCRIPT,
    )
    started = time.monotonic()

    try:
        completed = runner(
            command,
            cwd=working_directory,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=float(timeout_seconds),
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as error:
        return CalendarToolchainPythonVersionResult(
            passed=False,
            version=None,
            command=command,
            returncode=None,
            stdout=_normalise_stream(error.stdout),
            stderr=_normalise_stream(error.stderr),
            duration_seconds=time.monotonic() - started,
            timed_out=True,
            issues=(
                CalendarToolchainInstallerIssue(
                    code=(CalendarToolchainInstallFailureCode.INSTALL_TIMEOUT),
                    message=(
                        "The calendar Python-version check exceeded the "
                        "finite installer timeout."
                    ),
                    field="python_executable",
                    path=python_executable,
                ),
            ),
        )
    except OSError as error:
        return CalendarToolchainPythonVersionResult(
            passed=False,
            version=None,
            command=command,
            returncode=127,
            stdout="",
            stderr=_bounded_stream(str(error)),
            duration_seconds=time.monotonic() - started,
            timed_out=False,
            issues=(
                CalendarToolchainInstallerIssue(
                    code=(CalendarToolchainInstallFailureCode.VERSION_CHECK_FAILED),
                    message=(
                        "The calendar Python executable could not be "
                        f"inspected: {_error_detail(error)}."
                    ),
                    field="python_executable",
                    path=python_executable,
                ),
            ),
        )

    stdout = _normalise_stream(completed.stdout)
    stderr = _normalise_stream(completed.stderr)
    duration = time.monotonic() - started

    if completed.returncode != 0:
        return CalendarToolchainPythonVersionResult(
            passed=False,
            version=None,
            command=command,
            returncode=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
            timed_out=False,
            issues=(
                CalendarToolchainInstallerIssue(
                    code=(CalendarToolchainInstallFailureCode.VERSION_CHECK_FAILED),
                    message=(
                        "The calendar Python-version check failed with "
                        f"exit status {completed.returncode}."
                    ),
                    field="python_executable",
                    path=python_executable,
                ),
            ),
        )

    match = _PYTHON_VERSION_PATTERN.fullmatch(stdout.strip())

    if match is None:
        return CalendarToolchainPythonVersionResult(
            passed=False,
            version=None,
            command=command,
            returncode=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
            timed_out=False,
            issues=(
                CalendarToolchainInstallerIssue(
                    code=(CalendarToolchainInstallFailureCode.VERSION_CHECK_FAILED),
                    message=(
                        "The calendar Python executable returned an "
                        "unrecognised version."
                    ),
                    field="python_executable",
                    path=python_executable,
                ),
            ),
        )

    return CalendarToolchainPythonVersionResult(
        passed=True,
        version=match.group("version"),
        command=command,
        returncode=completed.returncode,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=duration,
        timed_out=False,
        issues=(),
    )


def _normalise_stream(value: str | bytes | None) -> str:
    """Return bounded deterministic subprocess diagnostics."""
    if value is None:
        return ""

    if isinstance(value, bytes):
        return _bounded_stream(value.decode("utf-8", errors="replace"))

    return _bounded_stream(str(value))


def _bounded_stream(value: str) -> str:
    """Bound retained subprocess diagnostics."""
    if len(value) <= _MAX_CAPTURED_STREAM_CHARACTERS:
        return value

    return value[: _MAX_CAPTURED_STREAM_CHARACTERS - 3] + "..."


def _error_detail(error: BaseException) -> str:
    """Return deterministic operating-system error text."""
    strerror = getattr(error, "strerror", None)

    if isinstance(strerror, str) and strerror:
        return strerror

    rendered = str(error).strip()
    return rendered or type(error).__name__


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
