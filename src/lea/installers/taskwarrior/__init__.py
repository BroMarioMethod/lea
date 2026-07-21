"""Public Taskwarrior installer interfaces."""

from lea.installers.taskwarrior.activation import (
    TaskwarriorActivationResult,
    activate_staged_taskwarrior,
    render_taskwarrior_installation_record,
    write_taskwarrior_installation_record,
)
from lea.installers.taskwarrior.build_execution import (
    TaskwarriorBuildStepResult,
    TaskwarriorSourceBuildExecutionResult,
    execute_taskwarrior_source_build,
)
from lea.installers.taskwarrior.build_plan import (
    TaskwarriorBuildDependencyResult,
    TaskwarriorBuildTools,
    TaskwarriorSourceBuildPlan,
    create_taskwarrior_source_build_plan,
    default_taskwarrior_build_tools,
    validate_taskwarrior_build_dependencies,
)
from lea.installers.taskwarrior.contracts import (
    TaskwarriorInstallerConfig,
    TaskwarriorInstallerIssue,
    TaskwarriorInstallerValidationResult,
    TaskwarriorInstallFailureCode,
    TaskwarriorInstallMode,
)
from lea.installers.taskwarrior.external_installer import (
    TaskwarriorExternalInstallResult,
    install_external_taskwarrior,
)
from lea.installers.taskwarrior.installer import (
    TaskwarriorBundledInstallResult,
    install_bundled_taskwarrior,
)
from lea.installers.taskwarrior.preflight import (
    calculate_sha256,
    check_directory_parent_writable,
    run_taskwarrior_installer_preflight,
    verify_expected_sha256,
)
from lea.installers.taskwarrior.records import (
    TaskwarriorInstallationRecord,
    installation_record_matches,
    read_taskwarrior_installation_record,
)
from lea.installers.taskwarrior.runtime_layout import (
    TaskwarriorRuntimeLayout,
    TaskwarriorRuntimeLayoutResult,
    provision_taskwarrior_runtime_layout,
    render_taskwarrior_taskrc,
)
from lea.installers.taskwarrior.smoke_test import (
    TaskwarriorSmokeTestResult,
    validate_staged_taskwarrior_binary,
    validate_taskwarrior_executable,
)
from lea.installers.taskwarrior.source_archive import (
    TaskwarriorExtractedSource,
    TaskwarriorSourceExtractionResult,
    extract_taskwarrior_source_archive,
    remove_taskwarrior_extracted_source,
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
    "TaskwarriorActivationResult",
    "TaskwarriorBuildDependencyResult",
    "TaskwarriorBuildStepResult",
    "TaskwarriorBuildTools",
    "TaskwarriorBundledInstallResult",
    "TaskwarriorExternalInstallResult",
    "TaskwarriorExtractedSource",
    "TaskwarriorInstallFailureCode",
    "TaskwarriorInstallMode",
    "TaskwarriorInstallationRecord",
    "TaskwarriorInstallerConfig",
    "TaskwarriorInstallerIssue",
    "TaskwarriorInstallerValidationResult",
    "TaskwarriorRuntimeLayout",
    "TaskwarriorRuntimeLayoutResult",
    "TaskwarriorSmokeTestResult",
    "TaskwarriorSourceBuildExecutionResult",
    "TaskwarriorSourceBuildPlan",
    "TaskwarriorSourceExtractionResult",
    "TaskwarriorStagedBinary",
    "TaskwarriorStagingResult",
    "activate_staged_taskwarrior",
    "calculate_sha256",
    "check_directory_parent_writable",
    "create_taskwarrior_source_build_plan",
    "default_taskwarrior_build_tools",
    "execute_taskwarrior_source_build",
    "extract_taskwarrior_source_archive",
    "install_bundled_taskwarrior",
    "install_external_taskwarrior",
    "installation_record_matches",
    "is_supported_taskwarrior_version",
    "is_valid_sha256",
    "normalise_taskwarrior_platform",
    "provision_taskwarrior_runtime_layout",
    "read_taskwarrior_installation_record",
    "remove_taskwarrior_extracted_source",
    "remove_taskwarrior_staging",
    "render_taskwarrior_installation_record",
    "render_taskwarrior_taskrc",
    "run_taskwarrior_installer_preflight",
    "stage_taskwarrior_binary",
    "validate_external_executable_path",
    "validate_staged_taskwarrior_binary",
    "validate_taskwarrior_build_dependencies",
    "validate_taskwarrior_executable",
    "validate_taskwarrior_installer_config",
    "verify_expected_sha256",
    "write_taskwarrior_installation_record",
]
