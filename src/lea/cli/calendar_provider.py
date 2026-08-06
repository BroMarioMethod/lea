"""Shared Local CLI calendar-provider loading boundary."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lea.adapters.khal import (
    KhalCalendarProviderFactoryConfig,
    build_khal_calendar_provider,
)
from lea.calendars import CalendarProvider
from lea.cli.contracts import CliIssue, CliResult, LocalCliExitCode
from lea.runtime import (
    ConfigurationResult,
    RuntimeConfig,
    RuntimeProfile,
    load_runtime_config,
)

ConfigurationLoader = Callable[[str | Path], ConfigurationResult]
CalendarProviderBuilder = Callable[[RuntimeConfig], CalendarProvider | CliResult]

_INSTALLATION_RECORD = Path("/var/lib/lea/install/calendar-toolchain.json")
_TOOLS_ROOT = Path("/opt/lea-tools/calendar")
_CONFIGURATION_DIRECTORY = Path("/etc/lea/calendar")
_STATE_ROOT = Path("/var/lib/lea/calendar")


def _build_system_provider(config: RuntimeConfig) -> CalendarProvider | CliResult:
    if config.profile is not RuntimeProfile.SYSTEM:
        return _failure(
            LocalCliExitCode.CONFIGURATION_ERROR,
            "calendar_runtime_unavailable",
            "Calendar commands require the system runtime profile.",
        )
    result = build_khal_calendar_provider(
        KhalCalendarProviderFactoryConfig(
            installation_record=_INSTALLATION_RECORD,
            tools_root=_TOOLS_ROOT,
            configuration_directory=_CONFIGURATION_DIRECTORY,
            state_root=_STATE_ROOT,
            working_directory=_STATE_ROOT,
            display_timezone=config.display_timezone,
        )
    )
    if result.success and result.provider is not None:
        return result.provider
    issue = result.issues[0]
    return _failure(LocalCliExitCode.PROVIDER_UNAVAILABLE, issue.code, issue.message)


@dataclass(frozen=True, slots=True)
class CalendarProviderDependencies:
    """Injected dependencies for configured calendar-provider loading."""

    load_configuration: ConfigurationLoader = load_runtime_config
    build_provider: CalendarProviderBuilder = _build_system_provider


def load_calendar_provider(
    *,
    config_path: Path,
    expected_profile: RuntimeProfile | None,
    dependencies: CalendarProviderDependencies | None = None,
) -> CalendarProvider | CliResult:
    """Load the configured calendar provider without installing or repairing it."""
    resolved = dependencies or CalendarProviderDependencies()
    configuration = resolved.load_configuration(config_path)
    if not configuration.success:
        return CliResult.failed(
            exit_code=LocalCliExitCode.CONFIGURATION_ERROR,
            issues=tuple(
                CliIssue(code=issue.code, message=issue.message, field=issue.field)
                for issue in configuration.issues
            ),
        )
    config = configuration.config
    if config is None:
        return _failure(
            LocalCliExitCode.INTERNAL_ERROR,
            "internal_error",
            "Successful configuration loading returned no runtime configuration.",
        )
    if expected_profile is not None and config.profile is not expected_profile:
        return _failure(
            LocalCliExitCode.CONFIGURATION_ERROR,
            "configuration_profile_mismatch",
            "The loaded runtime profile does not match the requested profile.",
            field="profile",
        )
    return resolved.build_provider(config)


def _failure(
    exit_code: LocalCliExitCode,
    code: str,
    message: str,
    *,
    field: str | None = None,
) -> CliResult:
    return CliResult.failed(
        exit_code=exit_code,
        issues=(CliIssue(code=code, message=message, field=field),),
    )
