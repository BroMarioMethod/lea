"""Atomic activation and installation-record persistence for Taskwarrior."""

import json
import os
import shutil
import tempfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from lea.installers.taskwarrior.contracts import (
    TaskwarriorInstallerConfig,
    TaskwarriorInstallerIssue,
    TaskwarriorInstallFailureCode,
)
from lea.installers.taskwarrior.preflight import calculate_sha256
from lea.installers.taskwarrior.records import (
    TaskwarriorInstallationRecord,
    installation_record_matches,
    read_taskwarrior_installation_record,
)
from lea.installers.taskwarrior.staging import TaskwarriorStagedBinary

_Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class TaskwarriorActivationResult:
    """Result of activating one staged Taskwarrior installation."""

    success: bool
    already_installed: bool
    record: TaskwarriorInstallationRecord | None
    issues: tuple[TaskwarriorInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate activation-result consistency."""
        if self.success:
            if self.record is None:
                raise ValueError("A successful activation must contain a record.")

            if self.issues:
                raise ValueError("A successful activation must not contain issues.")

            return

        if self.already_installed:
            raise ValueError("A failed activation must not be already installed.")

        if self.record is not None:
            raise ValueError("A failed activation must not contain a record.")

        if not self.issues:
            raise ValueError("A failed activation must contain at least one issue.")


def render_taskwarrior_installation_record(
    record: TaskwarriorInstallationRecord,
) -> str:
    """Render one installation record as deterministic JSON."""
    payload = {
        "schema_version": record.schema_version,
        "component": record.component,
        "version": record.version,
        "mode": record.mode,
        "platform": record.platform,
        "executable": str(record.executable),
        "sha256": record.sha256,
        "taskrc": str(record.taskrc),
        "home": str(record.home),
        "data": str(record.data),
        "smoke_test": record.smoke_test,
        "installed_at": record.installed_at.isoformat().replace(
            "+00:00",
            "Z",
        ),
    }

    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def activate_staged_taskwarrior(
    staged: TaskwarriorStagedBinary,
    config: TaskwarriorInstallerConfig,
    *,
    clock: _Clock = lambda: datetime.now(UTC),
    fsync: bool = False,
) -> TaskwarriorActivationResult:
    """Atomically activate one validated staged Taskwarrior binary."""
    final_root = config.tools_root / config.version
    final_executable = final_root / "bin" / "task"

    existing_result = _inspect_existing_installation(
        final_executable=final_executable,
        expected_sha256=staged.sha256,
        config=config,
    )

    if existing_result is not None:
        return existing_result

    try:
        config.tools_root.mkdir(
            mode=0o750,
            parents=True,
            exist_ok=True,
        )
        config.installation_record.parent.mkdir(
            mode=0o750,
            parents=True,
            exist_ok=True,
        )
    except OSError as error:
        return _failure(
            code=TaskwarriorInstallFailureCode.ACTIVATION_FAILED,
            message=(
                "The Taskwarrior installation directories could not be "
                f"prepared: {error.strerror or type(error).__name__}."
            ),
            path=config.tools_root,
        )

    try:
        os.replace(staged.staging_root, final_root)

        if fsync:
            _fsync_directory(config.tools_root)
    except OSError as error:
        return _failure(
            code=TaskwarriorInstallFailureCode.ACTIVATION_FAILED,
            message=(
                "The staged Taskwarrior installation could not be "
                f"activated: {error.strerror or type(error).__name__}."
            ),
            path=final_root,
        )

    record = _make_record(
        config=config,
        executable=final_executable,
        sha256=staged.sha256,
        installed_at=clock(),
    )

    write_issues = write_taskwarrior_installation_record(
        record,
        destination=config.installation_record,
        fsync=fsync,
    )

    if write_issues:
        rollback_issue = _rollback_activated_installation(final_root)

        if rollback_issue is not None:
            return TaskwarriorActivationResult(
                success=False,
                already_installed=False,
                record=None,
                issues=(*write_issues, rollback_issue),
            )

        return TaskwarriorActivationResult(
            success=False,
            already_installed=False,
            record=None,
            issues=write_issues,
        )

    return TaskwarriorActivationResult(
        success=True,
        already_installed=False,
        record=record,
        issues=(),
    )


def write_taskwarrior_installation_record(
    record: TaskwarriorInstallationRecord,
    *,
    destination: Path,
    fsync: bool = False,
) -> tuple[TaskwarriorInstallerIssue, ...]:
    """Atomically replace one Taskwarrior installation record."""
    if not destination.is_absolute():
        raise ValueError("destination must be absolute.")

    document = render_taskwarrior_installation_record(record)
    temporary_path: Path | None = None

    try:
        destination.parent.mkdir(
            mode=0o750,
            parents=True,
            exist_ok=True,
        )
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            text=True,
        )
        temporary_path = Path(temporary_name)

        with os.fdopen(
            file_descriptor,
            mode="w",
            encoding="utf-8",
            newline="\n",
        ) as stream:
            stream.write(document)
            stream.flush()

            if fsync:
                os.fsync(stream.fileno())

        os.replace(temporary_path, destination)
        temporary_path = None

        if fsync:
            _fsync_directory(destination.parent)
    except OSError as error:
        return (
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.RECORD_FAILED,
                message=(
                    "The Taskwarrior installation record could not be "
                    f"written: {error.strerror or type(error).__name__}."
                ),
                field="installation_record",
                path=destination,
            ),
        )
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)

    return ()


def _inspect_existing_installation(
    *,
    final_executable: Path,
    expected_sha256: str,
    config: TaskwarriorInstallerConfig,
) -> TaskwarriorActivationResult | None:
    """Return an idempotent result or mismatch failure when present."""
    final_root = final_executable.parent.parent

    if not final_root.exists():
        return None

    if not final_root.is_dir() or not final_executable.is_file():
        return _failure(
            code=TaskwarriorInstallFailureCode.ACTIVATION_FAILED,
            message=(
                "The target Taskwarrior version path already exists but "
                "is not a valid installation."
            ),
            path=final_root,
        )

    try:
        existing_sha256 = calculate_sha256(final_executable)
    except OSError as error:
        return _failure(
            code=TaskwarriorInstallFailureCode.ACTIVATION_FAILED,
            message=(
                "The existing Taskwarrior installation could not be "
                f"verified: {error.strerror or type(error).__name__}."
            ),
            path=final_executable,
        )

    if existing_sha256 != expected_sha256:
        return _failure(
            code=TaskwarriorInstallFailureCode.ACTIVATION_FAILED,
            message=(
                "The target Taskwarrior version already exists with a "
                "different SHA-256 checksum."
            ),
            path=final_executable,
        )

    record, record_issues = read_taskwarrior_installation_record(
        config.installation_record
    )

    if record_issues or record is None:
        return TaskwarriorActivationResult(
            success=False,
            already_installed=False,
            record=None,
            issues=record_issues,
        )

    if not installation_record_matches(
        record,
        version=config.version,
        platform=config.platform,
        executable=final_executable,
        sha256=existing_sha256,
    ):
        return _failure(
            code=TaskwarriorInstallFailureCode.RECORD_FAILED,
            message=(
                "The existing Taskwarrior installation record does not "
                "match the installed executable."
            ),
            path=config.installation_record,
        )

    return TaskwarriorActivationResult(
        success=True,
        already_installed=True,
        record=record,
        issues=(),
    )


def _make_record(
    *,
    config: TaskwarriorInstallerConfig,
    executable: Path,
    sha256: str,
    installed_at: datetime,
) -> TaskwarriorInstallationRecord:
    """Create one installation record from validated inputs."""
    return TaskwarriorInstallationRecord(
        schema_version=1,
        component="taskwarrior",
        version=config.version,
        mode=config.mode.value,
        platform=config.platform,
        executable=executable,
        sha256=sha256,
        taskrc=config.configuration_dir / "taskrc",
        home=config.state_root / "home",
        data=config.state_root / "data",
        smoke_test="passed",
        installed_at=installed_at,
    )


def _rollback_activated_installation(
    final_root: Path,
) -> TaskwarriorInstallerIssue | None:
    """Remove only the newly activated version directory."""
    try:
        shutil.rmtree(final_root)
    except OSError as error:
        return TaskwarriorInstallerIssue(
            code=TaskwarriorInstallFailureCode.ACTIVATION_FAILED,
            message=(
                "The failed Taskwarrior activation could not be rolled "
                f"back: {error.strerror or type(error).__name__}."
            ),
            field="tools_root",
            path=final_root,
        )

    return None


def _fsync_directory(directory: Path) -> None:
    """Request filesystem synchronisation for one directory."""
    descriptor = os.open(directory, os.O_RDONLY)

    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _failure(
    *,
    code: TaskwarriorInstallFailureCode,
    message: str,
    path: Path,
) -> TaskwarriorActivationResult:
    """Construct one deterministic activation failure."""
    return TaskwarriorActivationResult(
        success=False,
        already_installed=False,
        record=None,
        issues=(
            TaskwarriorInstallerIssue(
                code=code,
                message=message,
                path=path,
            ),
        ),
    )
