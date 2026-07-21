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
    "calculate_sha256",
    "check_directory_parent_writable",
    "is_supported_taskwarrior_version",
    "is_valid_sha256",
    "normalise_taskwarrior_platform",
    "run_taskwarrior_installer_preflight",
    "validate_external_executable_path",
    "validate_taskwarrior_installer_config",
    "verify_expected_sha256",
]
