"""Deterministic bundled-binary Taskwarrior installation workflow."""

from collections.abc import Callable
from dataclasses import dataclass

from lea.installers.taskwarrior.activation import (
    TaskwarriorActivationResult,
    activate_staged_taskwarrior,
)
from lea.installers.taskwarrior.contracts import (
    TaskwarriorInstallerConfig,
    TaskwarriorInstallerIssue,
    TaskwarriorInstallFailureCode,
    TaskwarriorInstallMode,
)
from lea.installers.taskwarrior.preflight import (
    run_taskwarrior_installer_preflight,
)
from lea.installers.taskwarrior.records import (
    TaskwarriorInstallationRecord,
)
from lea.installers.taskwarrior.runtime_layout import (
    TaskwarriorRuntimeLayoutResult,
    provision_taskwarrior_runtime_layout,
)
from lea.installers.taskwarrior.smoke_test import (
    TaskwarriorSmokeTestResult,
    validate_staged_taskwarrior_binary,
)
from lea.installers.taskwarrior.staging import (
    TaskwarriorStagedBinary,
    TaskwarriorStagingResult,
    remove_taskwarrior_staging,
    stage_taskwarrior_binary,
)
from lea.installers.taskwarrior.validation import (
    validate_taskwarrior_installer_config,
)

_ConfigValidator = Callable[
    [TaskwarriorInstallerConfig],
    object,
]
_PreflightRunner = Callable[
    [TaskwarriorInstallerConfig],
    tuple[TaskwarriorInstallerIssue, ...],
]
_Stager = Callable[..., TaskwarriorStagingResult]
_SmokeTester = Callable[..., TaskwarriorSmokeTestResult]
_LayoutProvisioner = Callable[..., TaskwarriorRuntimeLayoutResult]
_Activator = Callable[..., TaskwarriorActivationResult]
_StagingRemover = Callable[
    [TaskwarriorStagedBinary],
    tuple[TaskwarriorInstallerIssue, ...],
]


@dataclass(frozen=True, slots=True)
class TaskwarriorBundledInstallResult:
    """Result of one bundled-binary installation workflow."""

    success: bool
    already_installed: bool
    record: TaskwarriorInstallationRecord | None
    issues: tuple[TaskwarriorInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate installation-result consistency."""
        if self.success:
            if self.record is None:
                raise ValueError("A successful installation must contain a record.")

            if self.issues:
                raise ValueError("A successful installation must not contain issues.")

            return

        if self.already_installed:
            raise ValueError("A failed installation must not be already installed.")

        if self.record is not None:
            raise ValueError("A failed installation must not contain a record.")

        if not self.issues:
            raise ValueError("A failed installation must contain at least one issue.")


def install_bundled_taskwarrior(
    config: TaskwarriorInstallerConfig,
    *,
    fsync: bool = False,
    validate_config: _ConfigValidator = (validate_taskwarrior_installer_config),
    run_preflight: _PreflightRunner = (run_taskwarrior_installer_preflight),
    stage_binary: _Stager = stage_taskwarrior_binary,
    run_smoke_test: _SmokeTester = (validate_staged_taskwarrior_binary),
    provision_layout: _LayoutProvisioner = (provision_taskwarrior_runtime_layout),
    activate: _Activator = activate_staged_taskwarrior,
    remove_staging: _StagingRemover = remove_taskwarrior_staging,
) -> TaskwarriorBundledInstallResult:
    """Install one bundled Taskwarrior binary through validated phases."""
    if config.mode is not TaskwarriorInstallMode.BUNDLED_BINARY:
        return _failure(
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
                message=("The bundled installer requires bundled-binary mode."),
                field="mode",
            )
        )

    validation = validate_config(config)

    valid = getattr(validation, "valid", None)
    normalised_config = getattr(validation, "config", None)
    validation_issues = getattr(validation, "issues", None)

    if valid is not True or normalised_config is None:
        if isinstance(validation_issues, tuple) and validation_issues:
            return TaskwarriorBundledInstallResult(
                success=False,
                already_installed=False,
                record=None,
                issues=validation_issues,
            )

        return _failure(
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
                message="The installer configuration failed validation.",
            )
        )

    if normalised_config.artefact_path is None:
        return _failure(
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
                message="The bundled Taskwarrior artefact path is missing.",
                field="artefact_path",
            )
        )

    if normalised_config.expected_sha256 is None:
        return _failure(
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
                message="The bundled Taskwarrior checksum is missing.",
                field="expected_sha256",
            )
        )

    preflight_issues = run_preflight(normalised_config)

    if preflight_issues:
        return TaskwarriorBundledInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=preflight_issues,
        )

    staging_result = stage_binary(
        normalised_config.artefact_path,
        expected_sha256=normalised_config.expected_sha256,
        staging_parent=normalised_config.tools_root,
    )

    if staging_result.staged is None:
        return TaskwarriorBundledInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=staging_result.issues,
        )

    staged = staging_result.staged

    smoke_result = run_smoke_test(staged)

    if not smoke_result.passed:
        cleanup_issues = remove_staging(staged)
        return TaskwarriorBundledInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=(*smoke_result.issues, *cleanup_issues),
        )

    layout_result = provision_layout(
        normalised_config,
        fsync=fsync,
    )

    if not layout_result.success:
        cleanup_issues = remove_staging(staged)
        return TaskwarriorBundledInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=(*layout_result.issues, *cleanup_issues),
        )

    activation_result = activate(
        staged,
        normalised_config,
        fsync=fsync,
    )

    if not activation_result.success:
        cleanup_issues = remove_staging(staged)
        return TaskwarriorBundledInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=(*activation_result.issues, *cleanup_issues),
        )

    if activation_result.record is None:
        cleanup_issues = remove_staging(staged)
        return TaskwarriorBundledInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=(
                TaskwarriorInstallerIssue(
                    code=(TaskwarriorInstallFailureCode.ACTIVATION_FAILED),
                    message=(
                        "Taskwarrior activation succeeded without an "
                        "installation record."
                    ),
                ),
                *cleanup_issues,
            ),
        )

    if activation_result.already_installed:
        cleanup_issues = remove_staging(staged)

        if cleanup_issues:
            return TaskwarriorBundledInstallResult(
                success=False,
                already_installed=False,
                record=None,
                issues=cleanup_issues,
            )

    return TaskwarriorBundledInstallResult(
        success=True,
        already_installed=activation_result.already_installed,
        record=activation_result.record,
        issues=(),
    )


def _failure(
    issue: TaskwarriorInstallerIssue,
) -> TaskwarriorBundledInstallResult:
    """Create one failed bundled-install result."""
    return TaskwarriorBundledInstallResult(
        success=False,
        already_installed=False,
        record=None,
        issues=(issue,),
    )
