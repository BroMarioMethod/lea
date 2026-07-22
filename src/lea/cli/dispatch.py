"""Root dispatch boundary for the LEA Local CLI."""

import argparse
import sys
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import TextIO, cast
from uuid import UUID

from lea.cli.contracts import (
    CliIssue,
    CliResult,
    LocalCliExitCode,
)
from lea.cli.parser import create_local_cli_parser
from lea.cli.rendering import write_cli_result
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
from lea.runtime import RuntimeProfile
from lea.tasks import (
    TaskCreateRequest,
    TaskListQuery,
    TaskModifyRequest,
    TaskStatus,
)


def execute_local_cli(
    arguments: Sequence[str],
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    status_dependencies: StatusDependencies | None = None,
    task_dependencies: TaskCommandDependencies | None = None,
) -> int:
    """Parse and dispatch one Local CLI command."""
    parser = create_local_cli_parser()

    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            namespace = parser.parse_args(list(arguments))
    except SystemExit as error:
        return _normalise_argparse_exit(error)

    selection_issue = _validate_runtime_selection(namespace)

    if selection_issue is not None:
        return write_cli_result(
            selection_issue,
            stdout=stdout,
            stderr=stderr,
            json_output=bool(namespace.json),
            human_renderer=_render_first_issue,
        )

    if namespace.command == "status":
        result = execute_status(
            config_path=_config_path(namespace),
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

    if namespace.command == "task" and namespace.task_command == "list":
        result = execute_task_list(
            config_path=_config_path(namespace),
            expected_profile=_expected_profile(namespace),
            query=TaskListQuery(
                uuid=namespace.uuid,
                status=TaskStatus(namespace.status),
                project=namespace.project,
                tag=namespace.tag,
            ),
            dependencies=task_dependencies,
        )
        return write_cli_result(
            result,
            stdout=stdout,
            stderr=stderr,
            json_output=bool(namespace.json),
            human_renderer=render_task_list_result,
        )

    if namespace.command == "task" and namespace.task_command == "create":
        result = execute_task_create(
            config_path=_config_path(namespace),
            expected_profile=_expected_profile(namespace),
            request=TaskCreateRequest(
                description=namespace.description,
                project=namespace.project,
                priority=namespace.priority,
                tags=tuple(namespace.tag),
            ),
            dependencies=task_dependencies,
        )
        return write_cli_result(
            result,
            stdout=stdout,
            stderr=stderr,
            json_output=bool(namespace.json),
            human_renderer=render_task_create_result,
        )

    if namespace.command == "task" and namespace.task_command == "complete":
        validation_error = _validate_task_uuid(namespace.uuid)

        if validation_error is not None:
            return write_cli_result(
                validation_error,
                stdout=stdout,
                stderr=stderr,
                json_output=bool(namespace.json),
                human_renderer=_render_first_issue,
            )

        result = execute_task_complete(
            config_path=_config_path(namespace),
            expected_profile=_expected_profile(namespace),
            task_uuid=namespace.uuid,
            dependencies=task_dependencies,
        )
        return write_cli_result(
            result,
            stdout=stdout,
            stderr=stderr,
            json_output=bool(namespace.json),
            human_renderer=render_task_complete_result,
        )

    if namespace.command == "task" and namespace.task_command == "modify":
        request_result = _task_modify_request(namespace)

        if isinstance(request_result, CliResult):
            return write_cli_result(
                request_result,
                stdout=stdout,
                stderr=stderr,
                json_output=bool(namespace.json),
                human_renderer=_render_first_issue,
            )

        result = execute_task_modify(
            config_path=_config_path(namespace),
            expected_profile=_expected_profile(namespace),
            request=request_result,
            dependencies=task_dependencies,
        )
        return write_cli_result(
            result,
            stdout=stdout,
            stderr=stderr,
            json_output=bool(namespace.json),
            human_renderer=render_task_modify_result,
        )

    result = _not_implemented_result(namespace)
    return write_cli_result(
        result,
        stdout=stdout,
        stderr=stderr,
        json_output=bool(namespace.json),
        human_renderer=_render_not_implemented,
    )


def _validate_runtime_selection(
    namespace: argparse.Namespace,
) -> CliResult | None:
    """Validate deterministic runtime configuration selection."""
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


def _config_path(namespace: argparse.Namespace) -> Path:
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


def _validate_task_uuid(task_uuid: str) -> CliResult | None:
    """Validate one canonical lower-case task UUID."""
    try:
        canonical = str(UUID(task_uuid))
    except ValueError:
        canonical = ""

    if canonical == task_uuid:
        return None

    return CliResult.failed(
        exit_code=LocalCliExitCode.VALIDATION_ERROR,
        issues=(
            CliIssue(
                code="task_uuid_invalid",
                message="The task UUID is not canonical.",
                field="uuid",
            ),
        ),
        data={"task": None},
    )


def _task_modify_request(
    namespace: argparse.Namespace,
) -> TaskModifyRequest | CliResult:
    """Build one validated provider-neutral task modification."""
    try:
        return TaskModifyRequest(
            task_uuid=namespace.uuid,
            description=namespace.description,
            project=namespace.project,
            priority=namespace.priority,
            add_tags=tuple(namespace.add_tag),
            remove_tags=tuple(namespace.remove_tag),
        )
    except ValueError as error:
        return CliResult.failed(
            exit_code=LocalCliExitCode.VALIDATION_ERROR,
            issues=(
                CliIssue(
                    code="task_modification_invalid",
                    message=str(error),
                ),
            ),
            data={"task": None},
        )


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
    nested_command = getattr(
        namespace,
        f"{namespace.command}_command",
        None,
    )

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
