"""Public Taskwarrior installer interfaces."""

from lea.installers.taskwarrior.contracts import (
    TaskwarriorInstallerConfig,
    TaskwarriorInstallerIssue,
    TaskwarriorInstallerValidationResult,
    TaskwarriorInstallFailureCode,
    TaskwarriorInstallMode,
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
    "is_supported_taskwarrior_version",
    "is_valid_sha256",
    "normalise_taskwarrior_platform",
    "validate_external_executable_path",
    "validate_taskwarrior_installer_config",
]
