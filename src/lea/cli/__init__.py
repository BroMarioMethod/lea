"""Public Local CLI contracts and rendering interfaces."""

from lea.cli.contracts import (
    CliIssue,
    CliResult,
    JsonScalar,
    JsonValue,
    LocalCliExitCode,
    RuntimeCliExitCode,
    normalise_runtime_cli_exit_code,
)
from lea.cli.rendering import (
    HumanResultRenderer,
    write_cli_result,
)
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
    "normalise_runtime_cli_exit_code",
    "render_cli_result_json",
    "write_cli_result",
]
