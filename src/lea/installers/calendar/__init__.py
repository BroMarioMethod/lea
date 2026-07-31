"""Managed calendar toolchain installation."""

from lea.installers.calendar.configuration import (
    CalendarToolchainConfigurationPlan,
    CalendarToolchainConfigurationResult,
    create_calendar_toolchain_configuration_plan,
    persist_calendar_toolchain_configuration,
    render_calendar_khal_configuration,
    render_calendar_vdirsyncer_configuration,
)
from lea.installers.calendar.contracts import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallerValidationResult,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
)
from lea.installers.calendar.environment_execution import (
    CalendarToolchainEnvironmentExecutionResult,
    CalendarToolchainEnvironmentStepResult,
    execute_calendar_toolchain_environment_plan,
)
from lea.installers.calendar.environment_plan import (
    CalendarToolchainEnvironmentPlan,
    create_calendar_toolchain_environment_plan,
)
from lea.installers.calendar.preflight import (
    calculate_calendar_sha256,
    check_calendar_directory_parent_writable,
    run_calendar_toolchain_installer_preflight,
    verify_calendar_sha256,
)
from lea.installers.calendar.runtime_layout import (
    CalendarToolchainRuntimeLayout,
    CalendarToolchainRuntimeLayoutResult,
    create_calendar_toolchain_runtime_layout,
    provision_calendar_toolchain_runtime_layout,
)
from lea.installers.calendar.smoke_test import (
    CalendarToolchainSmokeStepResult,
    CalendarToolchainSmokeTestResult,
    run_calendar_toolchain_smoke_test,
    run_staged_calendar_toolchain_smoke_test,
)
from lea.installers.calendar.staging import (
    CalendarToolchainStagingLayout,
    CalendarToolchainStagingResult,
    create_calendar_toolchain_staging,
    remove_calendar_toolchain_staging,
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
from lea.installers.calendar.version_check import (
    CalendarToolchainVersionCheckResult,
    CalendarToolchainVersionStepResult,
    validate_calendar_tool_versions,
    validate_staged_calendar_tool_versions,
)

__all__ = [
    "CalendarToolchainConfigurationPlan",
    "CalendarToolchainConfigurationResult",
    "CalendarToolchainEnvironmentExecutionResult",
    "CalendarToolchainEnvironmentPlan",
    "CalendarToolchainEnvironmentStepResult",
    "CalendarToolchainInstallFailureCode",
    "CalendarToolchainInstallMode",
    "CalendarToolchainInstallerConfig",
    "CalendarToolchainInstallerIssue",
    "CalendarToolchainInstallerValidationResult",
    "CalendarToolchainRuntimeLayout",
    "CalendarToolchainRuntimeLayoutResult",
    "CalendarToolchainSmokeStepResult",
    "CalendarToolchainSmokeTestResult",
    "CalendarToolchainStagingLayout",
    "CalendarToolchainStagingResult",
    "CalendarToolchainVersionCheckResult",
    "CalendarToolchainVersionStepResult",
    "calculate_calendar_sha256",
    "check_calendar_directory_parent_writable",
    "create_calendar_toolchain_configuration_plan",
    "create_calendar_toolchain_environment_plan",
    "create_calendar_toolchain_runtime_layout",
    "create_calendar_toolchain_staging",
    "execute_calendar_toolchain_environment_plan",
    "is_supported_khal_version",
    "is_supported_vdirsyncer_version",
    "is_valid_calendar_sha256",
    "is_valid_https_package_index_url",
    "normalise_calendar_platform",
    "persist_calendar_toolchain_configuration",
    "provision_calendar_toolchain_runtime_layout",
    "remove_calendar_toolchain_staging",
    "render_calendar_khal_configuration",
    "render_calendar_vdirsyncer_configuration",
    "run_calendar_toolchain_installer_preflight",
    "run_calendar_toolchain_smoke_test",
    "run_staged_calendar_toolchain_smoke_test",
    "validate_calendar_executable_path",
    "validate_calendar_tool_versions",
    "validate_calendar_toolchain_installer_config",
    "validate_staged_calendar_tool_versions",
    "verify_calendar_sha256",
]
