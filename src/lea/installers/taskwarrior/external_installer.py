"""Administrator-supplied Taskwarrior executable installation workflow."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from lea.installers.taskwarrior.activation import (
    write_taskwarrior_installation_record,
)
from lea.installers.taskwarrior.contracts import (
    TaskwarriorInstallerConfig,
    TaskwarriorInstallerIssue,
    TaskwarriorInstallFailureCode,
    TaskwarriorInstallMode,
)
from lea.installers.taskwarrior.ownership import (
    OwnershipApplier,
    ignore_ownership,
)
from lea.installers.taskwarrior.preflight import calculate_sha256
from lea.installers.taskwarrior.records import (
    TaskwarriorInstallationRecord,
    installation_record_matches,
    read_taskwarrior_installation_record,
)
from lea.installers.taskwarrior.runtime_layout import (
    provision_taskwarrior_runtime_layout,
)
from lea.installers.taskwarrior.smoke_test import (
    TaskwarriorSmokeTestResult,
    validate_taskwarrior_executable,
)
from lea.installers.taskwarrior.validation import (
    validate_taskwarrior_installer_config,
)

_ExecutableValidator = Callable[..., TaskwarriorSmokeTestResult]


@dataclass(frozen=True, slots=True)
class TaskwarriorExternalInstallResult:
    """Result of installing one external Taskwarrior executable."""

    success: bool
    already_installed: bool
    record: TaskwarriorInstallationRecord | None
    issues: tuple[TaskwarriorInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate result consistency."""
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


def install_external_taskwarrior(
    config: TaskwarriorInstallerConfig,
    *,
    fsync: bool = False,
    apply_ownership: OwnershipApplier = ignore_ownership,
    validate_executable: _ExecutableValidator = validate_taskwarrior_executable,
) -> TaskwarriorExternalInstallResult:
    """Validate and register one exact administrator-supplied executable."""
    if config.mode is not TaskwarriorInstallMode.EXTERNAL_EXECUTABLE:
        return _failure(
            code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
            message=("The external installer requires external-executable mode."),
            field="mode",
        )

    validation = validate_taskwarrior_installer_config(config)

    if not validation.valid or validation.config is None:
        return TaskwarriorExternalInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=validation.issues,
        )

    normalised = validation.config
    executable = normalised.external_executable

    if executable is None:
        return _failure(
            code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
            message="The external Taskwarrior executable path is missing.",
            field="external_executable",
        )

    try:
        sha256 = calculate_sha256(executable)
    except OSError as error:
        return _failure(
            code=TaskwarriorInstallFailureCode.VERSION_CHECK_FAILED,
            message=(
                "The external Taskwarrior executable could not be read: "
                f"{error.strerror or type(error).__name__}."
            ),
            field="external_executable",
            path=executable,
        )

    existing = _existing_result(
        config=normalised,
        executable=executable,
        sha256=sha256,
    )

    if existing is not None:
        return existing

    smoke = validate_executable(
        executable,
        temporary_parent=normalised.state_root.parent,
    )

    if not smoke.passed or smoke.version is None:
        return TaskwarriorExternalInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=smoke.issues,
        )

    layout = provision_taskwarrior_runtime_layout(
        normalised,
        fsync=fsync,
        apply_ownership=apply_ownership,
    )

    if not layout.success or layout.layout is None:
        return TaskwarriorExternalInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=layout.issues,
        )

    record = TaskwarriorInstallationRecord(
        schema_version=1,
        component="taskwarrior",
        version=smoke.version,
        mode=normalised.mode.value,
        platform=normalised.platform,
        executable=executable,
        sha256=sha256,
        taskrc=layout.layout.taskrc,
        home=layout.layout.home,
        data=layout.layout.data,
        smoke_test="passed",
        installed_at=datetime.now(UTC),
    )

    record_issues = write_taskwarrior_installation_record(
        record,
        destination=normalised.installation_record,
        owner="root",
        group=normalised.service_group,
        fsync=fsync,
        apply_ownership=apply_ownership,
    )

    if record_issues:
        return TaskwarriorExternalInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=record_issues,
        )

    return TaskwarriorExternalInstallResult(
        success=True,
        already_installed=False,
        record=record,
        issues=(),
    )


def _existing_result(
    *,
    config: TaskwarriorInstallerConfig,
    executable: Path,
    sha256: str,
) -> TaskwarriorExternalInstallResult | None:
    """Return an idempotent result when a matching record exists."""
    if not config.installation_record.exists():
        return None

    record, issues = read_taskwarrior_installation_record(config.installation_record)

    if issues or record is None:
        return TaskwarriorExternalInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=issues,
        )

    if not installation_record_matches(
        record,
        version=config.version,
        platform=config.platform,
        executable=executable,
        sha256=sha256,
    ):
        return _failure(
            code=TaskwarriorInstallFailureCode.RECORD_FAILED,
            message=(
                "The existing Taskwarrior installation record does not "
                "match the external executable."
            ),
            field="installation_record",
            path=config.installation_record,
        )

    return TaskwarriorExternalInstallResult(
        success=True,
        already_installed=True,
        record=record,
        issues=(),
    )


def _failure(
    *,
    code: TaskwarriorInstallFailureCode,
    message: str,
    field: str,
    path: Path | None = None,
) -> TaskwarriorExternalInstallResult:
    """Create one failed external-install result."""
    return TaskwarriorExternalInstallResult(
        success=False,
        already_installed=False,
        record=None,
        issues=(
            TaskwarriorInstallerIssue(
                code=code,
                message=message,
                field=field,
                path=path,
            ),
        ),
    )
