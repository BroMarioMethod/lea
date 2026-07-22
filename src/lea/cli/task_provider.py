"""Shared Local CLI task-provider loading boundary."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lea.adapters.taskwarrior import TaskwarriorCliProvider, TaskwarriorConfig
from lea.cli.contracts import CliIssue, CliResult, LocalCliExitCode
from lea.installers.taskwarrior import (
    TaskwarriorInstallationRecord,
    read_taskwarrior_installation_record,
)
from lea.runtime import ConfigurationResult, RuntimeProfile, load_runtime_config
from lea.tasks import TaskProvider

ConfigurationLoader = Callable[[str | Path], ConfigurationResult]
InstallationRecordReader = Callable[
    [Path],
    tuple[TaskwarriorInstallationRecord | None, tuple[object, ...]],
]
TaskProviderFactory = Callable[[TaskwarriorConfig], TaskProvider]


@dataclass(frozen=True, slots=True)
class TaskProviderDependencies:
    """Injected dependencies for configured task-provider loading."""

    load_configuration: ConfigurationLoader = load_runtime_config
    read_installation_record: InstallationRecordReader = (
        read_taskwarrior_installation_record
    )
    create_provider: TaskProviderFactory = TaskwarriorCliProvider


def load_task_provider(
    *,
    config_path: Path,
    expected_profile: RuntimeProfile | None,
    dependencies: TaskProviderDependencies | None = None,
) -> TaskProvider | CliResult:
    """Load and inspect the configured provider without storage discovery."""
    resolved = dependencies or TaskProviderDependencies()
    configuration = resolved.load_configuration(config_path)

    if not configuration.success:
        return CliResult.failed(
            exit_code=LocalCliExitCode.CONFIGURATION_ERROR,
            issues=tuple(
                CliIssue(
                    code=issue.code,
                    message=issue.message,
                    field=issue.field,
                )
                for issue in configuration.issues
            ),
        )

    config = configuration.config

    if config is None:
        return _internal_failure(
            "Successful configuration loading returned no runtime configuration."
        )

    if expected_profile is not None and config.profile is not expected_profile:
        return CliResult.failed(
            exit_code=LocalCliExitCode.CONFIGURATION_ERROR,
            issues=(
                CliIssue(
                    code="configuration_profile_mismatch",
                    message=(
                        "The loaded runtime profile does not match "
                        "the requested profile."
                    ),
                    field="profile",
                ),
            ),
        )

    record, record_issues = resolved.read_installation_record(
        config.component_records.taskwarrior
    )

    if record is None:
        return CliResult.failed(
            exit_code=LocalCliExitCode.PROVIDER_UNAVAILABLE,
            issues=_installation_record_issues(record_issues),
        )

    provider = resolved.create_provider(_provider_config(record))
    inspection = provider.inspect()

    if not inspection.available:
        return CliResult.failed(
            exit_code=LocalCliExitCode.PROVIDER_UNAVAILABLE,
            issues=tuple(
                CliIssue(
                    code=issue.code,
                    message=issue.message,
                    field=issue.field,
                )
                for issue in inspection.issues
            ),
        )

    return provider


def _installation_record_issues(
    issues: tuple[object, ...],
) -> tuple[CliIssue, ...]:
    """Map installer-record issues to Local CLI issues."""
    mapped = tuple(
        CliIssue(
            code=str(
                getattr(
                    issue,
                    "code",
                    "taskwarrior_install_record_failed",
                )
            ),
            message=str(
                getattr(
                    issue,
                    "message",
                    "The Taskwarrior installation record could not be loaded.",
                )
            ),
            field=getattr(issue, "field", None),
        )
        for issue in issues
    )

    if mapped:
        return mapped

    return (
        CliIssue(
            code="taskwarrior_install_record_failed",
            message="The Taskwarrior installation record could not be loaded.",
        ),
    )


def _provider_config(
    record: TaskwarriorInstallationRecord,
) -> TaskwarriorConfig:
    """Construct one provider configuration from a validated record."""
    return TaskwarriorConfig(
        executable=record.executable,
        taskrc=record.taskrc,
        data_dir=record.data,
        home_dir=record.home,
    )


def _internal_failure(message: str) -> CliResult:
    """Construct one deterministic internal failure."""
    return CliResult.failed(
        exit_code=LocalCliExitCode.INTERNAL_ERROR,
        issues=(
            CliIssue(
                code="internal_error",
                message=message,
            ),
        ),
    )
