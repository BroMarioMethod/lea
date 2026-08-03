"""Construct a verified synchronization boundary from installation evidence."""

from dataclasses import dataclass

from lea.adapters.khal import (
    KhalCalendarProviderFactoryConfig,
    build_khal_calendar_provider,
)
from lea.adapters.vdirsyncer.contracts import VdirsyncerConfig
from lea.adapters.vdirsyncer.synchronizer import VdirsyncerCalendarSynchronizer
from lea.calendars import CalendarProviderIssue
from lea.installers.calendar.records import read_calendar_toolchain_installation_record


@dataclass(frozen=True, slots=True)
class VdirsyncerCalendarSynchronizerBuildResult:
    success: bool
    synchronizer: VdirsyncerCalendarSynchronizer | None
    issues: tuple[CalendarProviderIssue, ...]

    def __post_init__(self) -> None:
        if self.success and (self.synchronizer is None or self.issues):
            raise ValueError("Successful construction requires only a synchronizer.")
        if not self.success and (self.synchronizer is not None or not self.issues):
            raise ValueError("Failed construction requires only issues.")


def build_vdirsyncer_calendar_synchronizer(
    config: KhalCalendarProviderFactoryConfig,
) -> VdirsyncerCalendarSynchronizerBuildResult:
    """Build without installing, repairing, discovering, or synchronizing."""
    if not isinstance(config, KhalCalendarProviderFactoryConfig):
        raise TypeError("config must be a KhalCalendarProviderFactoryConfig value.")

    provider_result = build_khal_calendar_provider(config)
    if not provider_result.success:
        return _failure(provider_result.issues)
    record, issues = read_calendar_toolchain_installation_record(
        config.installation_record
    )
    if record is None or issues:
        return _failure(
            (
                _issue(
                    "vdirsyncer_installation_record_invalid",
                    "The calendar installation record was unavailable.",
                    "installation_record",
                ),
            )
        )

    configuration = config.configuration_directory / "vdirsyncer.conf"
    try:
        configuration_valid = (
            not configuration.is_symlink()
            and configuration.is_file()
            and configuration.stat().st_size <= 65_536
        )
    except OSError:
        configuration_valid = False
    if not configuration_valid:
        return _failure(
            (
                _issue(
                    "vdirsyncer_configuration_invalid",
                    "The managed vdirsyncer configuration was unavailable.",
                    "configuration",
                ),
            )
        )

    synchronizer = VdirsyncerCalendarSynchronizer(
        VdirsyncerConfig(
            executable=record.vdirsyncer_executable,
            configuration=configuration,
            working_directory=config.working_directory,
            expected_version=record.vdirsyncer_version,
            timeout_seconds=max(config.timeout_seconds, 60.0),
        )
    )
    inspection = synchronizer.inspect()
    if not inspection.available:
        return _failure(inspection.issues)
    return VdirsyncerCalendarSynchronizerBuildResult(True, synchronizer, ())


def _issue(code: str, message: str, field: str) -> CalendarProviderIssue:
    return CalendarProviderIssue(
        code=code,
        message=message,
        provider="vdirsyncer",
        operation="build_synchronizer",
        field=field,
    )


def _failure(
    issues: tuple[CalendarProviderIssue, ...],
) -> VdirsyncerCalendarSynchronizerBuildResult:
    return VdirsyncerCalendarSynchronizerBuildResult(False, None, issues)
