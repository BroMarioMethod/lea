"""Immutable contracts for explicit vdirsyncer execution."""

from dataclasses import dataclass
from pathlib import Path

from lea.calendars import CalendarProviderIssue


@dataclass(frozen=True, slots=True)
class VdirsyncerConfig:
    """Exact trusted runtime inputs for vdirsyncer."""

    executable: Path
    configuration: Path
    working_directory: Path
    expected_version: str
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        for name, path in (
            ("executable", self.executable),
            ("configuration", self.configuration),
            ("working_directory", self.working_directory),
        ):
            if not isinstance(path, Path):
                raise TypeError(f"{name} must be a pathlib.Path value.")
            if not path.is_absolute():
                raise ValueError(f"{name} must be an absolute path.")
        if (
            not isinstance(self.expected_version, str)
            or not self.expected_version.strip()
        ):
            raise ValueError("expected_version must be non-empty.")
        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds, (int, float)
        ):
            raise TypeError("timeout_seconds must be a number.")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")


@dataclass(frozen=True, slots=True)
class VdirsyncerCommandResult:
    """Captured bounded subprocess evidence."""

    arguments: tuple[str, ...]
    return_code: int
    stdout: str
    stderr: str
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class VdirsyncerRunResult:
    """Result of one explicit synchronization command."""

    success: bool
    command: VdirsyncerCommandResult | None
    issues: tuple[CalendarProviderIssue, ...]

    def __post_init__(self) -> None:
        if self.success and (self.command is None or self.issues):
            raise ValueError(
                "A successful vdirsyncer run requires only command evidence."
            )
        if not self.success and not self.issues:
            raise ValueError("A failed vdirsyncer run requires at least one issue.")
