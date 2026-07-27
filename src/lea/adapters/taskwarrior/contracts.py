"""Immutable Taskwarrior CLI adapter contracts."""

from dataclasses import dataclass
from pathlib import Path

from lea.tasks import TaskProviderIssue


@dataclass(frozen=True, slots=True)
class TaskwarriorConfig:
    """Explicit trusted configuration for Taskwarrior CLI."""

    executable: Path
    taskrc: Path
    data_dir: Path
    home_dir: Path
    timeout_seconds: float = 10.0
    working_dir: Path | None = None

    def __post_init__(self) -> None:
        """Validate explicit Taskwarrior adapter configuration."""
        for field_name, path in (
            ("executable", self.executable),
            ("taskrc", self.taskrc),
            ("data_dir", self.data_dir),
            ("home_dir", self.home_dir),
        ):
            _validate_absolute_path(path, field_name=field_name)

        if self.working_dir is not None:
            _validate_absolute_path(
                self.working_dir,
                field_name="working_dir",
            )

        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")


@dataclass(frozen=True, slots=True)
class TaskwarriorCommandResult:
    """Immutable captured result of one Taskwarrior command."""

    arguments: tuple[str, ...]
    return_code: int
    stdout: str
    stderr: str
    duration_seconds: float

    def __post_init__(self) -> None:
        """Validate captured command-result fields."""
        if not self.arguments:
            raise ValueError("arguments must contain at least the executable.")

        if any(not argument for argument in self.arguments):
            raise ValueError("arguments must not contain empty values.")

        if self.duration_seconds < 0:
            raise ValueError("duration_seconds must not be negative.")


@dataclass(frozen=True, slots=True)
class TaskwarriorRunResult:
    """Immutable result of invoking Taskwarrior."""

    success: bool
    command: TaskwarriorCommandResult | None
    issues: tuple[TaskProviderIssue, ...]

    def __post_init__(self) -> None:
        """Validate invocation-result consistency."""
        if self.success:
            if self.command is None:
                raise ValueError(
                    "A successful Taskwarrior run must contain a command result."
                )

            if self.issues:
                raise ValueError(
                    "A successful Taskwarrior run must not contain issues."
                )

            return

        if not self.issues:
            raise ValueError(
                "A failed Taskwarrior run must contain at least one issue."
            )

        if self.command is not None and self.command.return_code == 0:
            raise ValueError(
                "A failed Taskwarrior run command result must have a "
                "non-zero return code."
            )


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

    if "\x00" in str(path):
        raise ValueError(f"{field_name} must not contain a null byte.")
