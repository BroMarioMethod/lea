"""Safe staging for verified Taskwarrior binaries."""

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from lea.installers.taskwarrior.contracts import (
    TaskwarriorInstallerIssue,
    TaskwarriorInstallFailureCode,
)
from lea.installers.taskwarrior.preflight import calculate_sha256


@dataclass(frozen=True, slots=True)
class TaskwarriorStagedBinary:
    """One successfully staged Taskwarrior binary."""

    staging_root: Path
    executable: Path
    sha256: str

    def __post_init__(self) -> None:
        """Validate staged paths and checksum."""
        if not self.staging_root.is_absolute():
            raise ValueError("staging_root must be absolute.")

        if not self.executable.is_absolute():
            raise ValueError("executable must be absolute.")

        if self.executable.parent != self.staging_root / "bin":
            raise ValueError("executable must be inside the staging bin directory.")

        if len(self.sha256) != 64:
            raise ValueError("sha256 must contain 64 hexadecimal characters.")

        if any(character not in "0123456789abcdef" for character in self.sha256):
            raise ValueError("sha256 must be lower-case hexadecimal text.")


@dataclass(frozen=True, slots=True)
class TaskwarriorStagingResult:
    """Result of staging one Taskwarrior binary."""

    staged: TaskwarriorStagedBinary | None
    issues: tuple[TaskwarriorInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate success and failure consistency."""
        if self.staged is not None and self.issues:
            raise ValueError("A successful staging result must not contain issues.")

        if self.staged is None and not self.issues:
            raise ValueError("A failed staging result must contain at least one issue.")


def stage_taskwarrior_binary(
    source: Path,
    *,
    expected_sha256: str,
    staging_parent: Path,
) -> TaskwarriorStagingResult:
    """Copy one verified binary into a private temporary staging directory."""
    if not isinstance(source, Path):
        raise TypeError("source must be a pathlib.Path value.")

    if not isinstance(staging_parent, Path):
        raise TypeError("staging_parent must be a pathlib.Path value.")

    if not isinstance(expected_sha256, str):
        raise TypeError("expected_sha256 must be a string.")

    if not source.is_absolute():
        return _failure(
            code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
            message="The source Taskwarrior binary path must be absolute.",
            field="artefact_path",
        )

    if not staging_parent.is_absolute():
        return _failure(
            code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
            message="The staging parent path must be absolute.",
            field="staging_parent",
        )

    if not source.exists():
        return _failure(
            code=TaskwarriorInstallFailureCode.ARTEFACT_MISSING,
            message="The source Taskwarrior binary does not exist.",
            field="artefact_path",
            path=source,
        )

    if not source.is_file():
        return _failure(
            code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
            message="The source Taskwarrior binary is not a regular file.",
            field="artefact_path",
            path=source,
        )

    actual_source_sha256 = calculate_sha256(source)

    if actual_source_sha256 != expected_sha256:
        return _failure(
            code=TaskwarriorInstallFailureCode.CHECKSUM_MISMATCH,
            message=(
                "The source Taskwarrior binary checksum did not match "
                "the expected SHA-256 value."
            ),
            field="expected_sha256",
            path=source,
        )

    try:
        staging_parent.mkdir(
            mode=0o750,
            parents=True,
            exist_ok=True,
        )

        staging_root = Path(
            tempfile.mkdtemp(
                prefix=".taskwarrior-",
                dir=staging_parent,
            )
        )
        staging_root.chmod(0o750)

        bin_directory = staging_root / "bin"
        bin_directory.mkdir(mode=0o750)

        executable = bin_directory / "task"
        shutil.copyfile(source, executable)
        executable.chmod(0o750)

        staged_sha256 = calculate_sha256(executable)

        if staged_sha256 != expected_sha256:
            shutil.rmtree(staging_root, ignore_errors=True)
            return _failure(
                code=TaskwarriorInstallFailureCode.CHECKSUM_MISMATCH,
                message=(
                    "The staged Taskwarrior binary checksum did not match "
                    "the expected SHA-256 value."
                ),
                field="expected_sha256",
                path=executable,
            )

        return TaskwarriorStagingResult(
            staged=TaskwarriorStagedBinary(
                staging_root=staging_root,
                executable=executable,
                sha256=staged_sha256,
            ),
            issues=(),
        )
    except OSError as error:
        if "staging_root" in locals():
            shutil.rmtree(staging_root, ignore_errors=True)

        return _failure(
            code=TaskwarriorInstallFailureCode.COPY_FAILED,
            message=(
                "The Taskwarrior binary could not be copied into staging: "
                f"{error.strerror or type(error).__name__}."
            ),
            field="staging_parent",
            path=staging_parent,
        )


def remove_taskwarrior_staging(
    staged: TaskwarriorStagedBinary,
) -> tuple[TaskwarriorInstallerIssue, ...]:
    """Remove one staging directory without following external paths."""
    if not isinstance(staged, TaskwarriorStagedBinary):
        raise TypeError("staged must be a TaskwarriorStagedBinary value.")

    if staged.staging_root.is_symlink():
        return (
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
                message="The staging root must not be a symbolic link.",
                field="staging_root",
                path=staged.staging_root,
            ),
        )

    try:
        shutil.rmtree(staged.staging_root)
    except FileNotFoundError:
        return ()
    except OSError as error:
        return (
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.COPY_FAILED,
                message=(
                    "The Taskwarrior staging directory could not be removed: "
                    f"{error.strerror or type(error).__name__}."
                ),
                field="staging_root",
                path=staged.staging_root,
            ),
        )

    return ()


def _failure(
    *,
    code: TaskwarriorInstallFailureCode,
    message: str,
    field: str,
    path: Path | None = None,
) -> TaskwarriorStagingResult:
    """Create one failed staging result."""
    return TaskwarriorStagingResult(
        staged=None,
        issues=(
            TaskwarriorInstallerIssue(
                code=code,
                message=message,
                field=field,
                path=path,
            ),
        ),
    )
