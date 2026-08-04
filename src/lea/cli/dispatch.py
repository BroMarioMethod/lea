"""Root dispatch boundary for the LEA Local CLI."""

import argparse
import sys
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TextIO, cast
from uuid import UUID

from lea.actions import ActionProposal, ActionStatus
from lea.calendars import (
    CalendarCancelRequest,
    CalendarCreateRequest,
    CalendarEventQuery,
    CalendarEventTiming,
    CalendarModifyRequest,
    build_calendar_cancel_event_proposal,
    build_calendar_create_event_proposal,
    build_calendar_modify_event_proposal,
    build_calendar_sync_proposal,
)
from lea.cli.calendar_commands import (
    CalendarCommandDependencies,
    execute_calendar_events,
    execute_calendar_list,
    execute_calendar_show,
    render_calendar_events_result,
    render_calendar_list_result,
    render_calendar_show_result,
)
from lea.cli.calendar_proposal_commands import (
    CalendarProposalCommandDependencies,
    execute_calendar_proposal,
    render_calendar_proposal_result,
)
from lea.cli.contracts import (
    CliIssue,
    CliResult,
    JsonValue,
    LocalCliExitCode,
)
from lea.cli.parser import create_local_cli_parser
from lea.cli.proposal_commands import (
    ProposalCommandDependencies,
    execute_proposal_approve,
    execute_proposal_cancel,
    execute_proposal_execute,
    execute_proposal_list,
    execute_proposal_reject,
    execute_proposal_show,
    render_proposal_approve_result,
    render_proposal_cancel_result,
    render_proposal_execute_result,
    render_proposal_list_result,
    render_proposal_reject_result,
    render_proposal_show_result,
)
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
    execute_task_delete,
    execute_task_list,
    execute_task_modify,
    render_task_complete_result,
    render_task_create_result,
    render_task_delete_result,
    render_task_list_result,
    render_task_modify_result,
)
from lea.runtime import RuntimeProfile
from lea.tasks import (
    TaskCreateRequest,
    TaskListQuery,
    TaskModifyRequest,
    TaskStatus,
    normalise_task_tag,
)


def execute_local_cli(
    arguments: Sequence[str],
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    status_dependencies: StatusDependencies | None = None,
    task_dependencies: TaskCommandDependencies | None = None,
    proposal_dependencies: ProposalCommandDependencies | None = None,
    calendar_dependencies: CalendarCommandDependencies | None = None,
    calendar_proposal_dependencies: CalendarProposalCommandDependencies | None = None,
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

    if namespace.command == "calendar":
        if namespace.calendar_command == "list":
            result = execute_calendar_list(
                config_path=_config_path(namespace),
                expected_profile=_expected_profile(namespace),
                dependencies=calendar_dependencies,
            )
            renderer = render_calendar_list_result
        elif namespace.calendar_command == "show":
            result = execute_calendar_show(
                config_path=_config_path(namespace),
                expected_profile=_expected_profile(namespace),
                calendar_id=namespace.calendar_id,
                event_uid=namespace.event_uid,
                dependencies=calendar_dependencies,
            )
            renderer = render_calendar_show_result
        elif namespace.calendar_command == "events":
            try:
                calendar_query = CalendarEventQuery(
                    start_date=date.fromisoformat(namespace.start_date),
                    end_date=date.fromisoformat(namespace.end_date),
                    calendar_ids=tuple(namespace.calendar_id),
                    include_cancelled=namespace.include_cancelled,
                )
            except ValueError as error:
                result = CliResult.failed(
                    exit_code=LocalCliExitCode.VALIDATION_ERROR,
                    issues=(
                        CliIssue(code="calendar_query_invalid", message=str(error)),
                    ),
                    data={"events": []},
                )
            else:
                result = execute_calendar_events(
                    config_path=_config_path(namespace),
                    expected_profile=_expected_profile(namespace),
                    query=calendar_query,
                    dependencies=calendar_dependencies,
                )
            renderer = render_calendar_events_result
        else:
            proposal_builder_result = _calendar_proposal_builder(namespace)
            if isinstance(proposal_builder_result, CliResult):
                result = proposal_builder_result
            else:
                result = execute_calendar_proposal(
                    config_path=_config_path(namespace),
                    expected_profile=_expected_profile(namespace),
                    build_proposal=proposal_builder_result,
                    dependencies=calendar_proposal_dependencies,
                )
            renderer = render_calendar_proposal_result
        return write_cli_result(
            result,
            stdout=stdout,
            stderr=stderr,
            json_output=bool(namespace.json),
            human_renderer=renderer,
        )
    if namespace.command == "proposal" and namespace.proposal_command == "list":
        result = execute_proposal_list(
            config_path=_config_path(namespace),
            expected_profile=_expected_profile(namespace),
            status=(
                ActionStatus(namespace.status) if namespace.status is not None else None
            ),
            action_type=namespace.action_type,
            limit=namespace.limit,
            dependencies=proposal_dependencies,
        )
        return write_cli_result(
            result,
            stdout=stdout,
            stderr=stderr,
            json_output=bool(namespace.json),
            human_renderer=render_proposal_list_result,
        )

    if namespace.command == "proposal" and namespace.proposal_command == "approve":
        result = execute_proposal_approve(
            config_path=_config_path(namespace),
            expected_profile=_expected_profile(namespace),
            proposal_id=namespace.proposal_id,
            actor=namespace.actor,
            reason=namespace.reason,
            dependencies=proposal_dependencies,
        )
        return write_cli_result(
            result,
            stdout=stdout,
            stderr=stderr,
            json_output=bool(namespace.json),
            human_renderer=render_proposal_approve_result,
        )

    if namespace.command == "proposal" and namespace.proposal_command == "execute":
        result = execute_proposal_execute(
            config_path=_config_path(namespace),
            expected_profile=_expected_profile(namespace),
            proposal_id=namespace.proposal_id,
            dependencies=proposal_dependencies,
        )
        return write_cli_result(
            result,
            stdout=stdout,
            stderr=stderr,
            json_output=bool(namespace.json),
            human_renderer=render_proposal_execute_result,
        )

    if namespace.command == "proposal" and namespace.proposal_command == "cancel":
        result = execute_proposal_cancel(
            config_path=_config_path(namespace),
            expected_profile=_expected_profile(namespace),
            proposal_id=namespace.proposal_id,
            actor=namespace.actor,
            reason=namespace.reason,
            dependencies=proposal_dependencies,
        )
        return write_cli_result(
            result,
            stdout=stdout,
            stderr=stderr,
            json_output=bool(namespace.json),
            human_renderer=render_proposal_cancel_result,
        )

    if namespace.command == "proposal" and namespace.proposal_command == "reject":
        result = execute_proposal_reject(
            config_path=_config_path(namespace),
            expected_profile=_expected_profile(namespace),
            proposal_id=namespace.proposal_id,
            actor=namespace.actor,
            reason=namespace.reason,
            dependencies=proposal_dependencies,
        )
        return write_cli_result(
            result,
            stdout=stdout,
            stderr=stderr,
            json_output=bool(namespace.json),
            human_renderer=render_proposal_reject_result,
        )

    if namespace.command == "proposal" and namespace.proposal_command == "show":
        result = execute_proposal_show(
            config_path=_config_path(namespace),
            expected_profile=_expected_profile(namespace),
            proposal_id=namespace.proposal_id,
            dependencies=proposal_dependencies,
        )
        return write_cli_result(
            result,
            stdout=stdout,
            stderr=stderr,
            json_output=bool(namespace.json),
            human_renderer=render_proposal_show_result,
        )

    if namespace.command == "task" and namespace.task_command == "list":
        list_request_result = _task_list_query(namespace)

        if isinstance(list_request_result, CliResult):
            return write_cli_result(
                list_request_result,
                stdout=stdout,
                stderr=stderr,
                json_output=bool(namespace.json),
                human_renderer=_render_first_issue,
            )

        query, normalisations = list_request_result
        result = execute_task_list(
            config_path=_config_path(namespace),
            expected_profile=_expected_profile(namespace),
            query=query,
            dependencies=task_dependencies,
        )
        result = _with_normalisations(result, normalisations)
        return write_cli_result(
            result,
            stdout=stdout,
            stderr=stderr,
            json_output=bool(namespace.json),
            human_renderer=render_task_list_result,
        )

    if namespace.command == "task" and namespace.task_command == "create":
        create_request_result = _task_create_request(namespace)

        if isinstance(create_request_result, CliResult):
            return write_cli_result(
                create_request_result,
                stdout=stdout,
                stderr=stderr,
                json_output=bool(namespace.json),
                human_renderer=_render_first_issue,
            )

        create_request, normalisations = create_request_result
        result = execute_task_create(
            config_path=_config_path(namespace),
            expected_profile=_expected_profile(namespace),
            request=create_request,
            dependencies=task_dependencies,
        )
        result = _with_normalisations(result, normalisations)
        return write_cli_result(
            result,
            stdout=stdout,
            stderr=stderr,
            json_output=bool(namespace.json),
            human_renderer=render_task_create_result,
        )

    if namespace.command == "task" and namespace.task_command == "delete":
        validation_error = _validate_task_uuid(namespace.uuid)

        if validation_error is not None:
            return write_cli_result(
                validation_error,
                stdout=stdout,
                stderr=stderr,
                json_output=bool(namespace.json),
                human_renderer=_render_first_issue,
            )

        result = execute_task_delete(
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
            human_renderer=render_task_delete_result,
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
        modify_request_result = _task_modify_request(namespace)

        if isinstance(modify_request_result, CliResult):
            return write_cli_result(
                modify_request_result,
                stdout=stdout,
                stderr=stderr,
                json_output=bool(namespace.json),
                human_renderer=_render_first_issue,
            )

        modify_request, normalisations = modify_request_result
        result = execute_task_modify(
            config_path=_config_path(namespace),
            expected_profile=_expected_profile(namespace),
            request=modify_request,
            dependencies=task_dependencies,
        )
        result = _with_normalisations(result, normalisations)
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


def _calendar_proposal_builder(
    namespace: argparse.Namespace,
) -> Callable[[str, datetime], ActionProposal] | CliResult:
    """Validate calendar mutation input and return its proposal builder."""
    try:
        if namespace.calendar_command == "create":
            create_request = CalendarCreateRequest(
                calendar_id=namespace.calendar_id,
                summary=namespace.summary,
                timing=_calendar_timing(
                    namespace.start,
                    namespace.end,
                    namespace.timezone,
                ),
                description=namespace.description,
                location=namespace.location,
            )
            return lambda proposal_id, created_at: build_calendar_create_event_proposal(
                create_request,
                proposal_id=proposal_id,
                source="cli:local",
                created_at=created_at,
            )
        if namespace.calendar_command == "modify":
            modify_request = CalendarModifyRequest(
                calendar_id=namespace.calendar_id,
                event_uid=namespace.event_uid,
                summary=namespace.summary,
            )
            return lambda proposal_id, created_at: build_calendar_modify_event_proposal(
                modify_request,
                proposal_id=proposal_id,
                source="cli:local",
                created_at=created_at,
            )
        if namespace.calendar_command == "cancel":
            cancel_request = CalendarCancelRequest(
                namespace.calendar_id, namespace.event_uid
            )
            return lambda proposal_id, created_at: build_calendar_cancel_event_proposal(
                cancel_request,
                proposal_id=proposal_id,
                source="cli:local",
                created_at=created_at,
            )
        return lambda proposal_id, created_at: build_calendar_sync_proposal(
            proposal_id=proposal_id,
            source="cli:local",
            created_at=created_at,
        )
    except (TypeError, ValueError) as error:
        return CliResult.failed(
            exit_code=LocalCliExitCode.VALIDATION_ERROR,
            issues=(CliIssue(code="calendar_proposal_invalid", message=str(error)),),
            data={"proposal": None},
        )


def _calendar_timing(
    start_text: str,
    end_text: str,
    timezone: str | None,
) -> CalendarEventTiming:
    """Parse matching ISO dates or aware datetimes into canonical timing."""
    try:
        start_date = date.fromisoformat(start_text)
        end_date = date.fromisoformat(end_text)
    except ValueError:
        try:
            start_datetime = datetime.fromisoformat(start_text)
            end_datetime = datetime.fromisoformat(end_text)
        except ValueError as error:
            raise ValueError("start and end must be ISO dates or datetimes.") from error
        if timezone is None:
            raise ValueError("--timezone is required for timed events.") from None
        if (
            start_datetime.tzinfo is None
            or start_datetime.utcoffset() is None
            or end_datetime.tzinfo is None
            or end_datetime.utcoffset() is None
        ):
            raise ValueError("Timed event inputs must include UTC offsets.") from None
        return CalendarEventTiming(
            start_datetime.astimezone(UTC),
            end_datetime.astimezone(UTC),
            timezone,
        )
    if timezone is not None:
        raise ValueError("--timezone must not be supplied for all-day events.")
    return CalendarEventTiming(start_date, end_date)


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


def _task_list_query(
    namespace: argparse.Namespace,
) -> tuple[TaskListQuery, list[dict[str, str]]] | CliResult:
    """Build one validated task-list query and report normalisation."""
    try:
        normalisations = _tag_normalisations(
            [namespace.tag] if namespace.tag is not None else []
        )
        return (
            TaskListQuery(
                uuid=namespace.uuid,
                status=TaskStatus(namespace.status),
                project=namespace.project,
                tag=namespace.tag,
            ),
            normalisations,
        )
    except ValueError as error:
        return _task_validation_failure(
            code="task_list_query_invalid",
            message=str(error),
        )


def _task_create_request(
    namespace: argparse.Namespace,
) -> tuple[TaskCreateRequest, list[dict[str, str]]] | CliResult:
    """Build one validated task creation and report normalisation."""
    try:
        return (
            TaskCreateRequest(
                description=namespace.description,
                project=namespace.project,
                priority=namespace.priority,
                tags=tuple(namespace.tag),
            ),
            _tag_normalisations(namespace.tag),
        )
    except ValueError as error:
        return _task_validation_failure(
            code="task_creation_invalid",
            message=str(error),
        )


def _task_modify_request(
    namespace: argparse.Namespace,
) -> tuple[TaskModifyRequest, list[dict[str, str]]] | CliResult:
    """Build one validated provider-neutral task modification."""
    try:
        return (
            TaskModifyRequest(
                task_uuid=namespace.uuid,
                description=namespace.description,
                project=namespace.project,
                priority=namespace.priority,
                add_tags=tuple(namespace.add_tag),
                remove_tags=tuple(namespace.remove_tag),
            ),
            _tag_normalisations([*namespace.add_tag, *namespace.remove_tag]),
        )
    except ValueError as error:
        return _task_validation_failure(
            code="task_modification_invalid",
            message=str(error),
        )


def _tag_normalisations(values: list[str]) -> list[dict[str, str]]:
    """Describe every task tag changed by canonical normalisation."""
    normalisations: list[dict[str, str]] = []

    for value in values:
        canonical = normalise_task_tag(value)

        if canonical != value:
            normalisations.append(
                {
                    "field": "tag",
                    "input": value,
                    "value": canonical,
                }
            )

    return normalisations


def _with_normalisations(
    result: CliResult,
    normalisations: list[dict[str, str]],
) -> CliResult:
    """Attach input normalisations to CLI result data."""
    if not normalisations or not isinstance(result.data, dict):
        return result

    data = dict(result.data)
    data["normalisations"] = cast(JsonValue, normalisations)
    return CliResult(
        success=result.success,
        exit_code=result.exit_code,
        data=data,
        issues=result.issues,
    )


def _task_validation_failure(
    *,
    code: str,
    message: str,
) -> CliResult:
    """Return one deterministic task-input validation failure."""
    return CliResult.failed(
        exit_code=LocalCliExitCode.VALIDATION_ERROR,
        issues=(
            CliIssue(
                code=code,
                message=message,
                field="tag",
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
