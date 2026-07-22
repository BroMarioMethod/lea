"""Mode-based Taskwarrior installer dispatch."""

from dataclasses import dataclass

from lea.installers.taskwarrior.contracts import (
    TaskwarriorInstallerConfig,
    TaskwarriorInstallerIssue,
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
from lea.installers.taskwarrior.records import (
    TaskwarriorInstallationRecord,
)
from lea.installers.taskwarrior.source_installer import (
    TaskwarriorSourceInstallResult,
    install_source_taskwarrior,
)


@dataclass(frozen=True, slots=True)
class TaskwarriorInstallResult:
    """Provider-neutral result of one Taskwarrior installation."""

    success: bool
    already_installed: bool
    record: TaskwarriorInstallationRecord | None
    issues: tuple[TaskwarriorInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate generic installation-result consistency."""
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


def install_taskwarrior(
    config: TaskwarriorInstallerConfig,
    *,
    fsync: bool = False,
) -> TaskwarriorInstallResult:
    """Install Taskwarrior using the mode declared by the configuration."""
    if not isinstance(config, TaskwarriorInstallerConfig):
        raise TypeError("config must be a TaskwarriorInstallerConfig value.")

    if config.mode is TaskwarriorInstallMode.BUNDLED_BINARY:
        bundled_result = install_bundled_taskwarrior(
            config,
            fsync=fsync,
        )
        return _from_bundled(bundled_result)

    if config.mode is TaskwarriorInstallMode.SOURCE_BUILD:
        source_result = install_source_taskwarrior(
            config,
            fsync=fsync,
        )
        return _from_source(source_result)

    if config.mode is TaskwarriorInstallMode.EXTERNAL_EXECUTABLE:
        external_result = install_external_taskwarrior(
            config,
            fsync=fsync,
        )
        return _from_external(external_result)

    return TaskwarriorInstallResult(
        success=False,
        already_installed=False,
        record=None,
        issues=(
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
                message="The Taskwarrior installation mode is unsupported.",
                field="mode",
            ),
        ),
    )


def _from_bundled(
    result: TaskwarriorBundledInstallResult,
) -> TaskwarriorInstallResult:
    """Convert one bundled result to the generic result contract."""
    return TaskwarriorInstallResult(
        success=result.success,
        already_installed=result.already_installed,
        record=result.record,
        issues=result.issues,
    )


def _from_source(
    result: TaskwarriorSourceInstallResult,
) -> TaskwarriorInstallResult:
    """Convert one source result to the generic result contract."""
    return TaskwarriorInstallResult(
        success=result.success,
        already_installed=result.already_installed,
        record=result.record,
        issues=result.issues,
    )


def _from_external(
    result: TaskwarriorExternalInstallResult,
) -> TaskwarriorInstallResult:
    """Convert one external result to the generic result contract."""
    return TaskwarriorInstallResult(
        success=result.success,
        already_installed=result.already_installed,
        record=result.record,
        issues=result.issues,
    )
