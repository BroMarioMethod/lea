"""khal CLI provider inspection."""

import re

from lea.adapters.khal.contracts import (
    KhalConfig,
    KhalRunResult,
)
from lea.adapters.khal.runner import KhalRunner
from lea.calendars import (
    CalendarProviderInspectionResult,
    CalendarProviderIssue,
)

_PROVIDER = "khal"
_KHAL_VERSION_PATTERN = re.compile(
    r"^khal,\s+version\s+(?P<version>\S+)\s*$",
    re.IGNORECASE,
)
_MAX_DIAGNOSTIC_CHARACTERS = 2_000


def inspect_khal(
    config: KhalConfig,
    *,
    runner: KhalRunner | None = None,
) -> CalendarProviderInspectionResult:
    """Inspect one configured khal CLI provider."""
    if not isinstance(config, KhalConfig):
        raise TypeError("config must be a KhalConfig value.")

    resolved_runner = runner or KhalRunner(config)

    if resolved_runner.config != config:
        raise ValueError("runner configuration must match config.")

    runtime_issue = _inspect_runtime_paths(config)

    if runtime_issue is not None:
        return _unavailable(runtime_issue)

    result = resolved_runner.run(
        ("--version",),
        operation="inspect",
        configured=False,
    )

    if not result.success:
        return CalendarProviderInspectionResult(
            available=False,
            provider=_PROVIDER,
            version=None,
            issues=_enrich_process_issues(result),
        )

    command = result.command

    if command is None:
        return _unavailable(
            CalendarProviderIssue(
                code="khal_process_failed",
                message=("khal inspection succeeded without a command result."),
                provider=_PROVIDER,
                operation="inspect",
            )
        )

    version = _parse_version(
        stdout=command.stdout,
        stderr=command.stderr,
    )

    if version is None:
        return _unavailable(
            CalendarProviderIssue(
                code="khal_version_output_invalid",
                message=(
                    "The configured khal version output did not match the "
                    "supported command format."
                ),
                provider=_PROVIDER,
                operation="inspect",
                field="expected_version",
            )
        )

    if version != config.expected_version:
        return _unavailable(
            CalendarProviderIssue(
                code="khal_unsupported_version",
                message=(
                    f"The configured khal version was {version}; expected "
                    f"{config.expected_version}."
                ),
                provider=_PROVIDER,
                operation="inspect",
                field="expected_version",
            )
        )

    return CalendarProviderInspectionResult(
        available=True,
        provider=_PROVIDER,
        version=version,
        issues=(),
    )


def _inspect_runtime_paths(
    config: KhalConfig,
) -> CalendarProviderIssue | None:
    """Require the configured provider runtime without invoking khal."""
    configuration = config.configuration

    try:
        if configuration.is_symlink():
            return CalendarProviderIssue(
                code="khal_configuration_invalid",
                message=(
                    "The configured khal configuration must not be a symbolic link."
                ),
                provider=_PROVIDER,
                operation="inspect",
                field="configuration",
            )

        if not configuration.exists():
            return CalendarProviderIssue(
                code="khal_configuration_missing",
                message=("The configured khal configuration file does not exist."),
                provider=_PROVIDER,
                operation="inspect",
                field="configuration",
            )

        if not configuration.is_file():
            return CalendarProviderIssue(
                code="khal_configuration_invalid",
                message=(
                    "The configured khal configuration path is not a regular file."
                ),
                provider=_PROVIDER,
                operation="inspect",
                field="configuration",
            )
    except OSError:
        return CalendarProviderIssue(
            code="khal_configuration_invalid",
            message=("The configured khal configuration could not be inspected."),
            provider=_PROVIDER,
            operation="inspect",
            field="configuration",
        )

    for field, path in (
        ("state_directory", config.state_directory),
        ("working_directory", config.working_directory),
    ):
        try:
            if path.is_symlink():
                return CalendarProviderIssue(
                    code=f"khal_{field}_invalid",
                    message=(
                        f"The configured khal {field.replace('_', ' ')} "
                        "must not be a symbolic link."
                    ),
                    provider=_PROVIDER,
                    operation="inspect",
                    field=field,
                )

            if not path.exists():
                return CalendarProviderIssue(
                    code=f"khal_{field}_missing",
                    message=(
                        f"The configured khal {field.replace('_', ' ')} does not exist."
                    ),
                    provider=_PROVIDER,
                    operation="inspect",
                    field=field,
                )

            if not path.is_dir():
                return CalendarProviderIssue(
                    code=f"khal_{field}_invalid",
                    message=(
                        f"The configured khal {field.replace('_', ' ')} "
                        "is not a directory."
                    ),
                    provider=_PROVIDER,
                    operation="inspect",
                    field=field,
                )
        except OSError:
            return CalendarProviderIssue(
                code=f"khal_{field}_invalid",
                message=(
                    f"The configured khal {field.replace('_', ' ')} "
                    "could not be inspected."
                ),
                provider=_PROVIDER,
                operation="inspect",
                field=field,
            )

    return None


def _parse_version(
    *,
    stdout: str,
    stderr: str,
) -> str | None:
    """Parse one exact khal version line from either output stream."""
    for stream in (stdout, stderr):
        for line in stream.splitlines():
            match = _KHAL_VERSION_PATTERN.fullmatch(line.strip())

            if match is not None:
                return match.group("version")

    return None


def _enrich_process_issues(
    result: KhalRunResult,
) -> tuple[CalendarProviderIssue, ...]:
    """Attach bounded diagnostics when the process actually ran."""
    command = result.command

    if command is None:
        return result.issues

    diagnostics = _bounded_diagnostics(
        stdout=command.stdout,
        stderr=command.stderr,
    )

    return tuple(
        CalendarProviderIssue(
            code=issue.code,
            message=(
                issue.message
                if not diagnostics
                else f"{issue.message} Diagnostics: {diagnostics}"
            ),
            provider=issue.provider,
            operation=issue.operation,
            calendar_id=issue.calendar_id,
            event_uid=issue.event_uid,
            field=issue.field,
            return_code=issue.return_code,
        )
        for issue in result.issues
    )


def _bounded_diagnostics(
    *,
    stdout: str,
    stderr: str,
) -> str:
    """Return compact bounded subprocess diagnostics."""
    parts = []

    for name, value in (("stderr", stderr), ("stdout", stdout)):
        compact = " ".join(value.split())

        if compact:
            parts.append(f"{name}={compact}")

    rendered = "; ".join(parts)

    if len(rendered) <= _MAX_DIAGNOSTIC_CHARACTERS:
        return rendered

    return rendered[: _MAX_DIAGNOSTIC_CHARACTERS - 3] + "..."


def _unavailable(
    issue: CalendarProviderIssue,
) -> CalendarProviderInspectionResult:
    """Construct one deterministic unavailable-provider result."""
    return CalendarProviderInspectionResult(
        available=False,
        provider=_PROVIDER,
        version=None,
        issues=(issue,),
    )
