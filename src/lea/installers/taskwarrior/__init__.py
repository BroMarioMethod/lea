"""Public Taskwarrior installer interfaces."""

from lea.installers.taskwarrior.contracts import (
    TaskwarriorInstallerConfig,
    TaskwarriorInstallerIssue,
    TaskwarriorInstallerValidationResult,
    TaskwarriorInstallFailureCode,
    TaskwarriorInstallMode,
)
from lea.installers.taskwarrior.preflight import (
    calculate_sha256,
    check_directory_parent_writable,
    run_taskwarrior_installer_preflight,
    verify_expected_sha256,
)
from lea.installers.taskwarrior.staging import (
    TaskwarriorStagedBinary,
    TaskwarriorStagingResult,
    remove_taskwarrior_staging,
    stage_taskwarrior_binary,
)
from lea.installers.taskwarrior.validation import (
    is_supported_taskwarrior_version,
    is_valid_sha256,
    normalise_taskwarrior_platform,
    validate_external_executable_path,
    validate_taskwarrior_installer_config,
)

__all__ = [
    "TaskwarriorInstallFailureCode",
    "TaskwarriorInstallMode",
    "TaskwarriorInstallerConfig",
    "TaskwarriorInstallerIssue",
    "TaskwarriorInstallerValidationResult",
    "TaskwarriorStagedBinary",
    "TaskwarriorStagingResult",
    "calculate_sha256",
    "check_directory_parent_writable",
    "is_supported_taskwarrior_version",
    "is_valid_sha256",
    "normalise_taskwarrior_platform",
    "remove_taskwarrior_staging",
    "run_taskwarrior_installer_preflight",
    "stage_taskwarrior_binary",
    "validate_external_executable_path",
    "validate_taskwarrior_installer_config",
    "verify_expected_sha256",
]
