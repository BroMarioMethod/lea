"""Immutable contracts for the LEA Local CLI."""

from dataclasses import dataclass
from enum import IntEnum

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class LocalCliExitCode(IntEnum):
    """Stable process exit codes for new Local CLI commands."""

    SUCCESS = 0
    APPLICATION_ERROR = 1
    USAGE_ERROR = 2
    CONFIGURATION_ERROR = 3
    NOT_FOUND = 4
    CONFIRMATION_REQUIRED = 5
    PERMISSION_DENIED = 6
    CONFLICT = 7
    PROVIDER_UNAVAILABLE = 8
    VALIDATION_ERROR = 9
    INTERNAL_ERROR = 70


class RuntimeCliExitCode(IntEnum):
    """Existing runtime CLI exit codes retained for compatibility."""

    SUCCESS = 0
    RUNTIME_ERROR = 1
    CONFIGURATION_OR_USAGE_ERROR = 2


@dataclass(frozen=True, slots=True)
class CliIssue:
    """One stable, actionable Local CLI issue."""

    code: str
    message: str
    field: str | None = None

    def __post_init__(self) -> None:
        """Reject blank issue identifiers and messages."""
        if not self.code.strip():
            raise ValueError("CLI issue code must not be blank.")

        if not self.message.strip():
            raise ValueError("CLI issue message must not be blank.")

        if self.field is not None and not self.field.strip():
            raise ValueError("CLI issue field must not be blank when supplied.")


@dataclass(frozen=True, slots=True)
class CliResult:
    """One immutable Local CLI command result."""

    success: bool
    exit_code: LocalCliExitCode
    data: JsonValue = None
    issues: tuple[CliIssue, ...] = ()

    def __post_init__(self) -> None:
        """Require success state and process status to agree."""
        if self.success and self.exit_code is not LocalCliExitCode.SUCCESS:
            raise ValueError("Successful CLI results must use the success exit code.")

        if not self.success and self.exit_code is LocalCliExitCode.SUCCESS:
            raise ValueError("Failed CLI results must not use the success exit code.")

    @classmethod
    def succeeded(
        cls,
        *,
        data: JsonValue = None,
        issues: tuple[CliIssue, ...] = (),
    ) -> "CliResult":
        """Create one successful Local CLI result."""
        return cls(
            success=True,
            exit_code=LocalCliExitCode.SUCCESS,
            data=data,
            issues=issues,
        )

    @classmethod
    def failed(
        cls,
        *,
        exit_code: LocalCliExitCode,
        issues: tuple[CliIssue, ...],
        data: JsonValue = None,
    ) -> "CliResult":
        """Create one failed Local CLI result."""
        if exit_code is LocalCliExitCode.SUCCESS:
            raise ValueError("A failed CLI result requires a failure exit code.")

        if not issues:
            raise ValueError("A failed CLI result requires at least one issue.")

        return cls(
            success=False,
            exit_code=exit_code,
            data=data,
            issues=issues,
        )


def normalise_runtime_cli_exit_code(exit_code: int) -> int:
    """Preserve recognised existing runtime CLI exit codes.

    The existing runtime interface uses status 2 for both argparse usage errors
    and runtime-configuration errors. Milestone 2.3 must preserve that public
    behaviour rather than reinterpret it without richer runtime result data.
    """
    try:
        return int(RuntimeCliExitCode(exit_code))
    except ValueError:
        return int(LocalCliExitCode.INTERNAL_ERROR)
