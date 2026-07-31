"""Disposable local-only smoke tests for calendar toolchain executables."""

import json
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping
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
_SMOKE_PAIR = "smoke"
_SMOKE_COLLECTION = "default"
_SMOKE_UID = "lea-calendar-smoke@example.invalid"
_SMOKE_SUMMARY = "LEA calendar smoke test"


class _CommandRunner(Protocol):
    """Callable contract for one exact smoke-test subprocess."""

    def __call__(
        self,
        command: tuple[str, ...],
        *,
        cwd: Path,
        env: Mapping[str, str],
        stdin: int,
        capture_output: bool,
        text: bool,
        timeout: float,
        check: bool,
        shell: bool,
    ) -> subprocess.CompletedProcess[str]: ...


@dataclass(frozen=True, slots=True)
class CalendarToolchainSmokeStepResult:
    """Captured result of one local calendar smoke command."""

    phase: str
    command: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool

    def __post_init__(self) -> None:
        """Validate one immutable smoke step."""
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
class CalendarToolchainSmokeTestResult:
    """Result of one disposable local-only calendar toolchain smoke test."""

    passed: bool
    steps: tuple[CalendarToolchainSmokeStepResult, ...]
    issues: tuple[CalendarToolchainInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate smoke-test result consistency."""
        if not isinstance(self.passed, bool):
            raise TypeError("passed must be a boolean.")

        if self.passed:
            if len(self.steps) != 5:
                raise ValueError(
                    "A passed smoke test must contain five completed steps."
                )

            if self.issues:
                raise ValueError("A passed smoke test must not contain issues.")

            return

        if not self.issues:
            raise ValueError("A failed smoke test must contain at least one issue.")


@dataclass(frozen=True, slots=True)
class _SmokeLayout:
    """Private disposable filesystem layout for one smoke test."""

    root: Path
    home: Path
    xdg_config: Path
    xdg_data: Path
    xdg_cache: Path
    source_root: Path
    target_root: Path
    status_root: Path
    khal_config: Path
    vdirsyncer_config: Path

    def __post_init__(self) -> None:
        """Validate that every smoke path remains below the private root."""
        _validate_absolute_path(self.root, field_name="root")

        for field_name, path in (
            ("home", self.home),
            ("xdg_config", self.xdg_config),
            ("xdg_data", self.xdg_data),
            ("xdg_cache", self.xdg_cache),
            ("source_root", self.source_root),
            ("target_root", self.target_root),
            ("status_root", self.status_root),
            ("khal_config", self.khal_config),
            ("vdirsyncer_config", self.vdirsyncer_config),
        ):
            _validate_absolute_path(path, field_name=field_name)

            if not path.is_relative_to(self.root):
                raise ValueError(
                    f"{field_name} must remain below the private smoke root."
                )


@dataclass(frozen=True, slots=True)
class _SmokeCommand:
    """One exact command in the local smoke sequence."""

    phase: str
    command: tuple[str, ...]
    field: str
    path: Path


def _run_command(
    command: tuple[str, ...],
    *,
    cwd: Path,
    env: Mapping[str, str],
    stdin: int,
    capture_output: bool,
    text: bool,
    timeout: float,
    check: bool,
    shell: bool,
) -> subprocess.CompletedProcess[str]:
    """Run one exact smoke command without shell interpretation."""
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        stdin=stdin,
        capture_output=capture_output,
        text=text,
        timeout=timeout,
        check=check,
        shell=shell,
    )


def run_staged_calendar_toolchain_smoke_test(
    config: CalendarToolchainInstallerConfig,
    staged: CalendarToolchainStagingLayout,
    *,
    runner: _CommandRunner = _run_command,
) -> CalendarToolchainSmokeTestResult:
    """Run local-only smoke checks inside one managed staging layout."""
    if not isinstance(config, CalendarToolchainInstallerConfig):
        raise TypeError("config must be a CalendarToolchainInstallerConfig value.")

    if not isinstance(staged, CalendarToolchainStagingLayout):
        raise TypeError("staged must be a CalendarToolchainStagingLayout value.")

    if staged.staging_parent != config.tools_root:
        raise ValueError(
            "The staged layout does not belong to the configured tools root."
        )

    return run_calendar_toolchain_smoke_test(
        khal_executable=staged.khal_executable,
        vdirsyncer_executable=staged.vdirsyncer_executable,
        working_directory=staged.staging_root,
        timeout_seconds=config.timeout_seconds,
        runner=runner,
    )


def run_calendar_toolchain_smoke_test(
    *,
    khal_executable: Path,
    vdirsyncer_executable: Path,
    working_directory: Path,
    timeout_seconds: float,
    runner: _CommandRunner = _run_command,
) -> CalendarToolchainSmokeTestResult:
    """Run one disposable filesystem-only khal and vdirsyncer smoke test."""
    for field_name, path in (
        ("khal_executable", khal_executable),
        ("vdirsyncer_executable", vdirsyncer_executable),
        ("working_directory", working_directory),
    ):
        _validate_absolute_path(path, field_name=field_name)

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero.")

    smoke_root: Path | None = None
    result: CalendarToolchainSmokeTestResult

    try:
        smoke_root = Path(
            tempfile.mkdtemp(
                prefix=".calendar-smoke-",
                dir=working_directory,
            )
        )
        smoke_root.chmod(0o700)
        layout = _prepare_smoke_layout(smoke_root)
        result = _execute_smoke_sequence(
            khal_executable=khal_executable,
            vdirsyncer_executable=vdirsyncer_executable,
            layout=layout,
            timeout_seconds=timeout_seconds,
            runner=runner,
        )
    except OSError as error:
        result = CalendarToolchainSmokeTestResult(
            passed=False,
            steps=(),
            issues=(
                CalendarToolchainInstallerIssue(
                    code=(CalendarToolchainInstallFailureCode.SMOKE_TEST_FAILED),
                    message=(
                        "The disposable calendar smoke layout could not be "
                        f"prepared: {error.strerror or type(error).__name__}."
                    ),
                    field="smoke_root",
                    path=smoke_root or working_directory,
                ),
            ),
        )

    if smoke_root is None:
        return result

    try:
        shutil.rmtree(smoke_root)
    except OSError as error:
        cleanup_issue = CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.SMOKE_TEST_FAILED,
            message=(
                "The disposable calendar smoke layout could not be removed: "
                f"{error.strerror or type(error).__name__}."
            ),
            field="smoke_root",
            path=smoke_root,
        )
        return CalendarToolchainSmokeTestResult(
            passed=False,
            steps=result.steps,
            issues=(*result.issues, cleanup_issue),
        )

    return result


def _prepare_smoke_layout(
    smoke_root: Path,
) -> _SmokeLayout:
    """Create isolated local vdirs, configuration and one synthetic event."""
    layout = _SmokeLayout(
        root=smoke_root,
        home=smoke_root / "home",
        xdg_config=smoke_root / "xdg" / "config",
        xdg_data=smoke_root / "xdg" / "data",
        xdg_cache=smoke_root / "xdg" / "cache",
        source_root=smoke_root / "source",
        target_root=smoke_root / "target",
        status_root=smoke_root / "status",
        khal_config=smoke_root / "khal.conf",
        vdirsyncer_config=smoke_root / "vdirsyncer.conf",
    )

    for directory in (
        layout.home,
        layout.xdg_config,
        layout.xdg_data,
        layout.xdg_cache,
        layout.source_root / _SMOKE_COLLECTION,
        layout.target_root / _SMOKE_COLLECTION,
        layout.status_root,
    ):
        directory.mkdir(parents=True, exist_ok=False)
        directory.chmod(0o700)

    source_event = layout.source_root / _SMOKE_COLLECTION / "lea-smoke.ics"
    source_event.write_text(
        (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//LEA//Calendar smoke test//EN\r\n"
            "CALSCALE:GREGORIAN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{_SMOKE_UID}\r\n"
            "DTSTAMP:20981231T120000Z\r\n"
            "DTSTART:20990101T090000Z\r\n"
            "DTEND:20990101T100000Z\r\n"
            f"SUMMARY:{_SMOKE_SUMMARY}\r\n"
            "DESCRIPTION:Disposable local installer validation\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        ),
        encoding="utf-8",
        newline="",
    )
    source_event.chmod(0o600)

    layout.vdirsyncer_config.write_text(
        (
            "[general]\n"
            f'status_path = "{layout.status_root}"\n'
            "\n"
            f"[pair {_SMOKE_PAIR}]\n"
            'a = "smoke_source"\n'
            'b = "smoke_target"\n'
            'collections = ["from a", "from b"]\n'
            'conflict_resolution = "a wins"\n'
            "\n"
            "[storage smoke_source]\n"
            'type = "filesystem"\n'
            f'path = "{layout.source_root}"\n'
            'fileext = ".ics"\n'
            "\n"
            "[storage smoke_target]\n"
            'type = "filesystem"\n'
            f'path = "{layout.target_root}"\n'
            'fileext = ".ics"\n'
        ),
        encoding="utf-8",
        newline="\n",
    )
    layout.vdirsyncer_config.chmod(0o600)

    layout.khal_config.write_text(
        (
            "[calendars]\n"
            f"[[{_SMOKE_PAIR}]]\n"
            f"path = {layout.target_root / _SMOKE_COLLECTION}\n"
            "type = calendar\n"
            "\n"
            "[locale]\n"
            "local_timezone = UTC\n"
            "default_timezone = UTC\n"
            "timeformat = %H:%M\n"
            "dateformat = %Y-%m-%d\n"
            "longdateformat = %Y-%m-%d\n"
            "datetimeformat = %Y-%m-%d %H:%M\n"
            "longdatetimeformat = %Y-%m-%d %H:%M\n"
            "firstweekday = 0\n"
            "\n"
            "[default]\n"
            f"default_calendar = {_SMOKE_PAIR}\n"
        ),
        encoding="utf-8",
        newline="\n",
    )
    layout.khal_config.chmod(0o600)

    return layout


def _execute_smoke_sequence(
    *,
    khal_executable: Path,
    vdirsyncer_executable: Path,
    layout: _SmokeLayout,
    timeout_seconds: float,
    runner: _CommandRunner,
) -> CalendarToolchainSmokeTestResult:
    """Execute and verify the five-command local smoke sequence."""
    environment = _smoke_environment(
        executable_directory=khal_executable.parent,
        layout=layout,
    )
    steps: list[CalendarToolchainSmokeStepResult] = []

    commands = (
        _SmokeCommand(
            phase="vdirsyncer-showconfig",
            command=(
                str(vdirsyncer_executable),
                "-c",
                str(layout.vdirsyncer_config),
                "showconfig",
            ),
            field="vdirsyncer_config",
            path=layout.vdirsyncer_config,
        ),
        _SmokeCommand(
            phase="vdirsyncer-discover",
            command=(
                str(vdirsyncer_executable),
                "-c",
                str(layout.vdirsyncer_config),
                "discover",
                _SMOKE_PAIR,
            ),
            field="vdirsyncer_executable",
            path=vdirsyncer_executable,
        ),
        _SmokeCommand(
            phase="vdirsyncer-sync",
            command=(
                str(vdirsyncer_executable),
                "-c",
                str(layout.vdirsyncer_config),
                "sync",
                f"{_SMOKE_PAIR}/{_SMOKE_COLLECTION}",
            ),
            field="vdirsyncer_executable",
            path=vdirsyncer_executable,
        ),
    )

    for smoke_command in commands:
        step, issue = _run_smoke_step(
            smoke_command=smoke_command,
            working_directory=layout.root,
            environment=environment,
            timeout_seconds=timeout_seconds,
            runner=runner,
        )
        steps.append(step)

        if issue is not None:
            return _failed(steps, issue)

        verification_issue = _verify_vdirsyncer_phase(
            phase=smoke_command.phase,
            step=step,
            layout=layout,
        )

        if verification_issue is not None:
            return _failed(steps, verification_issue)

    khal_commands = (
        _SmokeCommand(
            phase="khal-printcalendars",
            command=(
                str(khal_executable),
                "--no-color",
                "-c",
                str(layout.khal_config),
                "printcalendars",
            ),
            field="khal_config",
            path=layout.khal_config,
        ),
        _SmokeCommand(
            phase="khal-list",
            command=(
                str(khal_executable),
                "--no-color",
                "-c",
                str(layout.khal_config),
                "list",
                "2099-01-01",
                "2099-01-02",
            ),
            field="khal_executable",
            path=khal_executable,
        ),
    )

    for smoke_command in khal_commands:
        step, issue = _run_smoke_step(
            smoke_command=smoke_command,
            working_directory=layout.root,
            environment=environment,
            timeout_seconds=timeout_seconds,
            runner=runner,
        )
        steps.append(step)

        if issue is not None:
            return _failed(steps, issue)

        verification_issue = _verify_khal_phase(
            phase=smoke_command.phase,
            step=step,
            layout=layout,
        )

        if verification_issue is not None:
            return _failed(steps, verification_issue)

    return CalendarToolchainSmokeTestResult(
        passed=True,
        steps=tuple(steps),
        issues=(),
    )


def _run_smoke_step(
    *,
    smoke_command: _SmokeCommand,
    working_directory: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    runner: _CommandRunner,
) -> tuple[
    CalendarToolchainSmokeStepResult,
    CalendarToolchainInstallerIssue | None,
]:
    """Execute one finite local smoke command."""
    started = time.monotonic()

    try:
        completed = runner(
            smoke_command.command,
            cwd=working_directory,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as error:
        step = CalendarToolchainSmokeStepResult(
            phase=smoke_command.phase,
            command=smoke_command.command,
            returncode=None,
            stdout=_normalise_stream(error.stdout),
            stderr=_normalise_stream(error.stderr),
            duration_seconds=time.monotonic() - started,
            timed_out=True,
        )
        return step, CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.INSTALL_TIMEOUT,
            message=(
                f"The {smoke_command.phase} smoke phase exceeded the "
                "finite installer timeout."
            ),
            field=smoke_command.field,
            path=smoke_command.path,
        )
    except OSError as error:
        step = CalendarToolchainSmokeStepResult(
            phase=smoke_command.phase,
            command=smoke_command.command,
            returncode=127,
            stdout="",
            stderr=_bounded_stream(str(error)),
            duration_seconds=time.monotonic() - started,
            timed_out=False,
        )
        return step, CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.SMOKE_TEST_FAILED,
            message=(
                f"The {smoke_command.phase} smoke command could not be "
                f"executed: {error.strerror or type(error).__name__}."
            ),
            field=smoke_command.field,
            path=smoke_command.path,
        )

    step = CalendarToolchainSmokeStepResult(
        phase=smoke_command.phase,
        command=smoke_command.command,
        returncode=completed.returncode,
        stdout=_normalise_stream(completed.stdout),
        stderr=_normalise_stream(completed.stderr),
        duration_seconds=time.monotonic() - started,
        timed_out=False,
    )

    if completed.returncode != 0:
        return step, CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.SMOKE_TEST_FAILED,
            message=(
                f"The {smoke_command.phase} smoke phase failed with exit "
                f"status {completed.returncode}."
            ),
            field=smoke_command.field,
            path=smoke_command.path,
        )

    return step, None


def _verify_vdirsyncer_phase(
    *,
    phase: str,
    step: CalendarToolchainSmokeStepResult,
    layout: _SmokeLayout,
) -> CalendarToolchainInstallerIssue | None:
    """Verify configuration parsing and local filesystem synchronisation."""
    if phase == "vdirsyncer-showconfig":
        try:
            document = json.loads(step.stdout)
        except (json.JSONDecodeError, TypeError):
            return _smoke_issue(
                message=("vdirsyncer showconfig did not return valid JSON."),
                field="vdirsyncer_config",
                path=layout.vdirsyncer_config,
            )

        storages = document.get("storages")

        if not isinstance(storages, list):
            return _smoke_issue(
                message=("vdirsyncer showconfig did not return a storage list."),
                field="vdirsyncer_config",
                path=layout.vdirsyncer_config,
            )

        names = {
            storage.get("instance_name")
            for storage in storages
            if isinstance(storage, dict)
        }

        if names != {"smoke_source", "smoke_target"}:
            return _smoke_issue(
                message=(
                    "vdirsyncer did not load both disposable filesystem storages."
                ),
                field="vdirsyncer_config",
                path=layout.vdirsyncer_config,
            )

    if phase != "vdirsyncer-sync":
        return None

    target_directory = layout.target_root / _SMOKE_COLLECTION
    target_events = tuple(sorted(target_directory.glob("*.ics")))

    if len(target_events) != 1:
        return _smoke_issue(
            message=(
                "vdirsyncer did not produce exactly one synchronised calendar item."
            ),
            field="target_collection",
            path=target_directory,
        )

    try:
        target_text = target_events[0].read_text(encoding="utf-8")
    except OSError:
        return _smoke_issue(
            message=("The synchronised calendar item could not be inspected."),
            field="target_event",
            path=target_events[0],
        )

    lines = set(target_text.splitlines())

    if f"UID:{_SMOKE_UID}" not in lines or f"SUMMARY:{_SMOKE_SUMMARY}" not in lines:
        return _smoke_issue(
            message=(
                "The synchronised calendar item did not preserve its "
                "expected UID and summary."
            ),
            field="target_event",
            path=target_events[0],
        )

    return None


def _verify_khal_phase(
    *,
    phase: str,
    step: CalendarToolchainSmokeStepResult,
    layout: _SmokeLayout,
) -> CalendarToolchainInstallerIssue | None:
    """Verify that khal loads the calendar and reads the synthetic event."""
    if phase == "khal-printcalendars":
        calendars = {line.strip() for line in step.stdout.splitlines() if line.strip()}

        if _SMOKE_PAIR not in calendars:
            return _smoke_issue(
                message=("khal did not load the disposable smoke calendar."),
                field="khal_config",
                path=layout.khal_config,
            )

        return None

    if _SMOKE_SUMMARY not in step.stdout:
        return _smoke_issue(
            message=("khal did not read the synchronised synthetic event."),
            field="target_collection",
            path=layout.target_root / _SMOKE_COLLECTION,
        )

    return None


def _smoke_environment(
    *,
    executable_directory: Path,
    layout: _SmokeLayout,
) -> dict[str, str]:
    """Return a minimal isolated environment for local smoke commands."""
    return {
        "HOME": str(layout.home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "NO_COLOR": "1",
        "PATH": f"{executable_directory}:/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
        "TZ": "UTC",
        "XDG_CACHE_HOME": str(layout.xdg_cache),
        "XDG_CONFIG_HOME": str(layout.xdg_config),
        "XDG_DATA_HOME": str(layout.xdg_data),
    }


def _failed(
    steps: list[CalendarToolchainSmokeStepResult],
    issue: CalendarToolchainInstallerIssue,
) -> CalendarToolchainSmokeTestResult:
    """Return one failed smoke-test result."""
    return CalendarToolchainSmokeTestResult(
        passed=False,
        steps=tuple(steps),
        issues=(issue,),
    )


def _smoke_issue(
    *,
    message: str,
    field: str,
    path: Path,
) -> CalendarToolchainInstallerIssue:
    """Construct one deterministic smoke-test issue."""
    return CalendarToolchainInstallerIssue(
        code=CalendarToolchainInstallFailureCode.SMOKE_TEST_FAILED,
        message=message,
        field=field,
        path=path,
    )


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
