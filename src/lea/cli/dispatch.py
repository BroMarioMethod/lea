"""Root dispatch boundary for the LEA Local CLI."""

import argparse
import sys
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import TextIO, cast

from lea.cli.contracts import CliIssue, CliResult, LocalCliExitCode
from lea.cli.parser import create_local_cli_parser
from lea.cli.rendering import write_cli_result
from lea.cli.status import (
    DEFAULT_RUNTIME_CONFIG,
    StatusDependencies,
    execute_status,
    render_status_result,
)
from lea.runtime import RuntimeProfile


def execute_local_cli(
    arguments: Sequence[str],
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    status_dependencies: StatusDependencies | None = None,
) -> int:
    """Parse and dispatch one Local CLI command."""
    parser = create_local_cli_parser()
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            namespace = parser.parse_args(list(arguments))
    except SystemExit as error:
        return _normalise_argparse_exit(error)

    if namespace.command == "status":
        usage_issue = _validate_status_selection(namespace)
        if usage_issue is not None:
            return write_cli_result(
                usage_issue,
                stdout=stdout,
                stderr=stderr,
                json_output=bool(namespace.json),
                human_renderer=_render_first_issue,
            )

        result = execute_status(
            config_path=_status_config_path(namespace),
            expected_profile=_expected_profile(namespace),
            dependencies=status_dependencies,
        )
        return write_cli_result(
            result,
            stdout=stdout,
            stderr=stderr,
            json_output=bool(namespace.json),
            human_renderer=render_status_result,
        )

    result = _not_implemented_result(namespace)
    return write_cli_result(
        result,
        stdout=stdout,
        stderr=stderr,
        json_output=bool(namespace.json),
        human_renderer=_render_not_implemented,
    )


def _validate_status_selection(
    namespace: argparse.Namespace,
) -> CliResult | None:
    """Validate deterministic status configuration selection."""
    if namespace.config is not None:
        return None

    if namespace.profile in {
        RuntimeProfile.DEVELOPMENT.value,
        RuntimeProfile.TEST.value,
    }:
        return CliResult.failed(
            exit_code=LocalCliExitCode.USAGE_ERROR,
            issues=(
                CliIssue(
                    code="configuration_path_required",
                    message=(
                        "--config is required when --profile is "
                        "'development' or 'test'."
                    ),
                    field="config",
                ),
            ),
        )

    return None


def _status_config_path(namespace: argparse.Namespace) -> Path:
    """Return the explicit or canonical system configuration path."""
    if namespace.config is not None:
        return cast(Path, namespace.config)
    return DEFAULT_RUNTIME_CONFIG


def _expected_profile(
    namespace: argparse.Namespace,
) -> RuntimeProfile | None:
    """Return the optional asserted runtime profile."""
    if namespace.profile is None:
        return None
    return RuntimeProfile(namespace.profile)


def _not_implemented_result(namespace: argparse.Namespace) -> CliResult:
    """Return a structured placeholder for accepted command grammar."""
    command_path = _command_path(namespace)
    return CliResult.failed(
        exit_code=LocalCliExitCode.APPLICATION_ERROR,
        issues=(
            CliIssue(
                code="cli_command_not_implemented",
                message=(
                    f"The '{command_path}' command is recognised but is not "
                    "implemented yet."
                ),
            ),
        ),
        data={"command": command_path},
    )


def _command_path(namespace: argparse.Namespace) -> str:
    """Return the selected command path in display form."""
    parts = ["lea", namespace.command]
    nested_command = getattr(namespace, f"{namespace.command}_command", None)
    if nested_command is not None:
        parts.append(nested_command)
    return " ".join(parts)


def _render_not_implemented(result: CliResult) -> str:
    """Render a placeholder command failure."""
    return result.issues[0].message


def _render_first_issue(result: CliResult) -> str:
    """Render one usage or configuration-selection issue."""
    return result.issues[0].message


def _normalise_argparse_exit(error: SystemExit) -> int:
    """Return one stable parser exit status."""
    if error.code == 0:
        return int(LocalCliExitCode.SUCCESS)
    return int(LocalCliExitCode.USAGE_ERROR)
