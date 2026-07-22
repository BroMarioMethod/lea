"""Safe production runtime layout provisioning for Taskwarrior."""

import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from lea.installers.taskwarrior.contracts import (
    TaskwarriorInstallerConfig,
    TaskwarriorInstallerIssue,
    TaskwarriorInstallFailureCode,
)


@dataclass(frozen=True, slots=True)
class TaskwarriorRuntimeLayout:
    """Provisioned Taskwarrior runtime paths."""

    taskrc: Path
    home: Path
    data: Path

    def __post_init__(self) -> None:
        """Validate absolute runtime paths."""
        for field_name, path in (
            ("taskrc", self.taskrc),
            ("home", self.home),
            ("data", self.data),
        ):
            if not path.is_absolute():
                raise ValueError(f"{field_name} must be absolute.")


@dataclass(frozen=True, slots=True)
class TaskwarriorRuntimeLayoutResult:
    """Result of provisioning the Taskwarrior runtime layout."""

    success: bool
    layout: TaskwarriorRuntimeLayout | None
    issues: tuple[TaskwarriorInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate result consistency."""
        if self.success:
            if self.layout is None:
                raise ValueError(
                    "A successful runtime-layout result must contain a layout."
                )
            if self.issues:
                raise ValueError(
                    "A successful runtime-layout result must not contain issues."
                )
            return

        if self.layout is not None:
            raise ValueError(
                "A failed runtime-layout result must not contain a layout."
            )

        if not self.issues:
            raise ValueError("A failed runtime-layout result must contain issues.")


def render_taskwarrior_taskrc() -> str:
    """Render the deterministic LEA-managed Taskwarrior configuration."""
    return "confirmation=no\nhooks=0\nverbose=nothing\n"


def provision_taskwarrior_runtime_layout(
    config: TaskwarriorInstallerConfig,
    *,
    fsync: bool = False,
) -> TaskwarriorRuntimeLayoutResult:
    """Create or validate LEA-managed Taskwarrior runtime paths."""
    taskrc = config.configuration_dir / "taskrc"
    home = config.state_root / "home"
    data = config.state_root / "data"

    try:
        config.configuration_dir.mkdir(
            mode=0o750,
            parents=True,
            exist_ok=True,
        )
        config.state_root.mkdir(
            mode=0o750,
            parents=True,
            exist_ok=True,
        )
        home.mkdir(mode=0o700, exist_ok=True)
        data.mkdir(mode=0o700, exist_ok=True)
    except OSError as error:
        return _failure(
            message=(
                "The Taskwarrior runtime directories could not be "
                f"provisioned: {error.strerror or type(error).__name__}."
            ),
            path=config.state_root,
        )

    for field_name, directory in (
        ("configuration_dir", config.configuration_dir),
        ("state_root", config.state_root),
        ("home", home),
        ("data", data),
    ):
        if not directory.is_dir():
            return _failure(
                message=f"{field_name} is not a directory.",
                path=directory,
            )

        if directory.is_symlink():
            return _failure(
                message=f"{field_name} must not be a symbolic link.",
                path=directory,
            )

    document = render_taskwarrior_taskrc()

    if taskrc.exists():
        if not taskrc.is_file() or taskrc.is_symlink():
            return _failure(
                message=(
                    "The Taskwarrior taskrc path exists but is not a "
                    "regular managed file."
                ),
                path=taskrc,
            )

        try:
            current = taskrc.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            return _failure(
                message=(
                    "The existing Taskwarrior taskrc could not be read: "
                    f"{type(error).__name__}."
                ),
                path=taskrc,
            )

        if current != document:
            return _failure(
                message=(
                    "The existing Taskwarrior taskrc differs from the "
                    "LEA-managed configuration and was not overwritten."
                ),
                path=taskrc,
            )
    else:
        issues = _write_taskrc(
            taskrc,
            document=document,
            fsync=fsync,
        )
        if issues:
            return TaskwarriorRuntimeLayoutResult(
                success=False,
                layout=None,
                issues=issues,
            )

    try:
        config.configuration_dir.chmod(0o750)
        config.state_root.chmod(0o750)
        home.chmod(0o700)
        data.chmod(0o700)
        taskrc.chmod(0o600)
    except OSError as error:
        return _failure(
            message=(
                "The Taskwarrior runtime permissions could not be "
                f"applied: {error.strerror or type(error).__name__}."
            ),
            path=config.state_root,
        )

    return TaskwarriorRuntimeLayoutResult(
        success=True,
        layout=TaskwarriorRuntimeLayout(
            taskrc=taskrc,
            home=home,
            data=data,
        ),
        issues=(),
    )


def _write_taskrc(
    destination: Path,
    *,
    document: str,
    fsync: bool,
) -> tuple[TaskwarriorInstallerIssue, ...]:
    """Atomically create one managed taskrc without overwriting."""
    temporary_path: Path | None = None

    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=".taskrc.",
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

        os.link(temporary_path, destination)

        if fsync:
            _fsync_directory(destination.parent)
    except FileExistsError:
        return (
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.ACTIVATION_FAILED,
                message=(
                    "The Taskwarrior taskrc appeared during provisioning "
                    "and was not overwritten."
                ),
                field="configuration_dir",
                path=destination,
            ),
        )
    except OSError as error:
        return (
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.ACTIVATION_FAILED,
                message=(
                    "The Taskwarrior taskrc could not be written: "
                    f"{error.strerror or type(error).__name__}."
                ),
                field="configuration_dir",
                path=destination,
            ),
        )
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)

    return ()


def _fsync_directory(directory: Path) -> None:
    """Request filesystem synchronisation for one directory."""
    descriptor = os.open(directory, os.O_RDONLY)

    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _failure(
    *,
    message: str,
    path: Path,
) -> TaskwarriorRuntimeLayoutResult:
    """Create one structured runtime-layout failure."""
    return TaskwarriorRuntimeLayoutResult(
        success=False,
        layout=None,
        issues=(
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.ACTIVATION_FAILED,
                message=message,
                path=path,
            ),
        ),
    )
