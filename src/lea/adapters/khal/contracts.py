"""Immutable khal CLI adapter contracts."""

from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lea.calendars import (
    CalendarEvent,
    CalendarProviderIssue,
)


@dataclass(frozen=True, slots=True)
class KhalConfig:
    """Explicit trusted configuration for one khal CLI provider."""

    executable: Path
    configuration: Path
    vdirs_directory: Path
    state_directory: Path
    working_directory: Path
    expected_version: str
    display_timezone: str = "UTC"
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        """Validate explicit khal adapter configuration."""
        for field_name, path in (
            ("executable", self.executable),
            ("configuration", self.configuration),
            ("vdirs_directory", self.vdirs_directory),
            ("state_directory", self.state_directory),
            ("working_directory", self.working_directory),
        ):
            _validate_absolute_path(path, field_name=field_name)

        if not isinstance(self.expected_version, str):
            raise TypeError("expected_version must be a string.")

        if not self.expected_version.strip():
            raise ValueError("expected_version must be non-empty.")

        if not isinstance(self.display_timezone, str):
            raise TypeError("display_timezone must be a string.")

        if not self.display_timezone.strip():
            raise ValueError("display_timezone must be non-empty.")

        try:
            display_zone = ZoneInfo(self.display_timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError(
                "display_timezone must be a valid IANA timezone."
            ) from error

        if display_zone.key != self.display_timezone:
            raise ValueError("display_timezone must use its canonical IANA identifier.")

        if not isinstance(self.timeout_seconds, (int, float)) or isinstance(
            self.timeout_seconds, bool
        ):
            raise TypeError("timeout_seconds must be a number.")

        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")


@dataclass(frozen=True, slots=True)
class KhalCommandResult:
    """Immutable captured result of one khal command."""

    arguments: tuple[str, ...]
    return_code: int
    stdout: str
    stderr: str
    duration_seconds: float

    def __post_init__(self) -> None:
        """Validate captured command-result fields."""
        if not self.arguments:
            raise ValueError("arguments must contain at least the executable.")

        if any(
            not isinstance(argument, str) or not argument for argument in self.arguments
        ):
            raise ValueError("arguments must contain only non-empty strings.")

        if not isinstance(self.return_code, int) or isinstance(
            self.return_code,
            bool,
        ):
            raise TypeError("return_code must be an integer.")

        if not isinstance(self.stdout, str):
            raise TypeError("stdout must be a string.")

        if not isinstance(self.stderr, str):
            raise TypeError("stderr must be a string.")

        if not isinstance(self.duration_seconds, (int, float)) or isinstance(
            self.duration_seconds, bool
        ):
            raise TypeError("duration_seconds must be a number.")

        if self.duration_seconds < 0:
            raise ValueError("duration_seconds must not be negative.")


@dataclass(frozen=True, slots=True)
class KhalRunResult:
    """Immutable result of invoking khal."""

    success: bool
    command: KhalCommandResult | None
    issues: tuple[CalendarProviderIssue, ...]

    def __post_init__(self) -> None:
        """Validate invocation-result consistency."""
        if not isinstance(self.success, bool):
            raise TypeError("success must be a boolean.")

        if self.success:
            if self.command is None:
                raise ValueError("A successful khal run must contain a command result.")

            if self.issues:
                raise ValueError("A successful khal run must not contain issues.")

            return

        if not self.issues:
            raise ValueError("A failed khal run must contain at least one issue.")

        if self.command is not None and self.command.return_code == 0:
            raise ValueError(
                "A failed khal run command result must have a non-zero return code."
            )


@dataclass(frozen=True, slots=True)
class KhalCalendarItemParseResult:
    """Immutable result of parsing one local vdir item."""

    success: bool
    event: CalendarEvent | None
    issues: tuple[CalendarProviderIssue, ...]

    def __post_init__(self) -> None:
        """Validate item-parse result consistency."""
        if not isinstance(self.success, bool):
            raise TypeError("success must be a boolean.")

        if self.success:
            if self.event is None:
                raise ValueError("A successful khal item parse must contain an event.")

            if self.issues:
                raise ValueError(
                    "A successful khal item parse must not contain issues."
                )

            return

        if self.event is not None:
            raise ValueError("A failed khal item parse must not contain an event.")

        if not self.issues:
            raise ValueError(
                "A failed khal item parse must contain at least one issue."
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
