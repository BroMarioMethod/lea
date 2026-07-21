"""Taskwarrior CLI provider inspection."""

import re

from lea.adapters.taskwarrior.contracts import TaskwarriorConfig
from lea.adapters.taskwarrior.runner import TaskwarriorRunner
from lea.tasks import (
    TaskProviderInspectionResult,
    TaskProviderIssue,
)

_PROVIDER = "taskwarrior"
_SUPPORTED_VERSION_PATTERN = re.compile(r"^3\.4\.\d+$")


def inspect_taskwarrior(
    config: TaskwarriorConfig,
) -> TaskProviderInspectionResult:
    """Inspect one configured Taskwarrior CLI provider."""
    if not config.taskrc.exists():
        return _unavailable(
            code="taskwarrior_configuration_invalid",
            message="The configured Taskwarrior taskrc file does not exist.",
        )

    if not config.taskrc.is_file():
        return _unavailable(
            code="taskwarrior_configuration_invalid",
            message="The configured Taskwarrior taskrc path is not a file.",
        )

    if not config.data_dir.exists():
        return _unavailable(
            code="taskwarrior_data_directory_missing",
            message="The configured Taskwarrior data directory does not exist.",
        )

    if not config.data_dir.is_dir():
        return _unavailable(
            code="taskwarrior_data_directory_not_directory",
            message=("The configured Taskwarrior data path is not a directory."),
        )

    if not config.home_dir.exists() or not config.home_dir.is_dir():
        return _unavailable(
            code="taskwarrior_configuration_invalid",
            message=("The configured Taskwarrior home directory is not usable."),
        )

    runner = TaskwarriorRunner(config)
    result = runner.run(
        ("--version",),
        operation="inspect",
    )

    if not result.success:
        return TaskProviderInspectionResult(
            available=False,
            provider=_PROVIDER,
            version=None,
            issues=result.issues,
        )

    command = result.command

    if command is None:
        return _unavailable(
            code="taskwarrior_process_failed",
            message=("Taskwarrior inspection succeeded without a command result."),
        )

    version = command.stdout.strip()

    if _SUPPORTED_VERSION_PATTERN.fullmatch(version) is None:
        return _unavailable(
            code="taskwarrior_unsupported_version",
            message=("The configured Taskwarrior version is not supported."),
        )

    return TaskProviderInspectionResult(
        available=True,
        provider=_PROVIDER,
        version=version,
        issues=(),
    )


def _unavailable(
    *,
    code: str,
    message: str,
) -> TaskProviderInspectionResult:
    """Construct one deterministic unavailable-provider result."""
    return TaskProviderInspectionResult(
        available=False,
        provider=_PROVIDER,
        version=None,
        issues=(
            TaskProviderIssue(
                code=code,
                message=message,
                provider=_PROVIDER,
                operation="inspect",
            ),
        ),
    )
