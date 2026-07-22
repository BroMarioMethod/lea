"""Public Local CLI contracts and execution interfaces."""

from lea.cli.contracts import (
    CliIssue,
    CliResult,
    JsonScalar,
    JsonValue,
    LocalCliExitCode,
    RuntimeCliExitCode,
    normalise_runtime_cli_exit_code,
)
from lea.cli.dispatch import execute_local_cli
from lea.cli.parser import create_local_cli_parser
from lea.cli.rendering import HumanResultRenderer, write_cli_result
from lea.cli.serialisation import (
    cli_issue_to_dict,
    cli_result_to_dict,
    render_cli_result_json,
)
from lea.cli.status import (
    DEFAULT_RUNTIME_CONFIG,
    StatusDependencies,
    execute_status,
    render_status_result,
)
from lea.cli.task_commands import (
    TaskCommandDependencies,
    execute_task_complete,
    execute_task_create,
    execute_task_list,
    execute_task_modify,
    render_task_complete_result,
    render_task_create_result,
    render_task_list_result,
    render_task_modify_result,
)

__all__ = [
    "DEFAULT_RUNTIME_CONFIG",
    "CliIssue",
    "CliResult",
    "HumanResultRenderer",
    "JsonScalar",
    "JsonValue",
    "LocalCliExitCode",
    "RuntimeCliExitCode",
    "StatusDependencies",
    "TaskCommandDependencies",
    "cli_issue_to_dict",
    "cli_result_to_dict",
    "create_local_cli_parser",
    "execute_local_cli",
    "execute_status",
    "execute_task_complete",
    "execute_task_create",
    "execute_task_list",
    "execute_task_modify",
    "normalise_runtime_cli_exit_code",
    "render_cli_result_json",
    "render_status_result",
    "render_task_complete_result",
    "render_task_create_result",
    "render_task_list_result",
    "render_task_modify_result",
    "write_cli_result",
]
