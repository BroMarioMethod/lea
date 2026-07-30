"""Managed calendar toolchain installation."""

from lea.installers.calendar.contracts import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallerValidationResult,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
)
from lea.installers.calendar.preflight import (
    calculate_calendar_sha256,
    check_calendar_directory_parent_writable,
    run_calendar_toolchain_installer_preflight,
    verify_calendar_sha256,
)
from lea.installers.calendar.validation import (
    is_supported_khal_version,
    is_supported_vdirsyncer_version,
    is_valid_calendar_sha256,
    is_valid_https_package_index_url,
    normalise_calendar_platform,
    validate_calendar_executable_path,
    validate_calendar_toolchain_installer_config,
)

__all__ = [
    "CalendarToolchainInstallFailureCode",
    "CalendarToolchainInstallMode",
    "CalendarToolchainInstallerConfig",
    "CalendarToolchainInstallerIssue",
    "CalendarToolchainInstallerValidationResult",
    "calculate_calendar_sha256",
    "check_calendar_directory_parent_writable",
    "is_supported_khal_version",
    "is_supported_vdirsyncer_version",
    "is_valid_calendar_sha256",
    "is_valid_https_package_index_url",
    "normalise_calendar_platform",
    "run_calendar_toolchain_installer_preflight",
    "validate_calendar_executable_path",
    "validate_calendar_toolchain_installer_config",
    "verify_calendar_sha256",
]
