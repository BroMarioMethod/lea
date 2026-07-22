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

__all__ = [
    "CliIssue",
    "CliResult",
    "HumanResultRenderer",
    "JsonScalar",
    "JsonValue",
    "LocalCliExitCode",
    "RuntimeCliExitCode",
    "cli_issue_to_dict",
    "cli_result_to_dict",
    "create_local_cli_parser",
    "execute_local_cli",
    "normalise_runtime_cli_exit_code",
    "render_cli_result_json",
    "write_cli_result",
]
