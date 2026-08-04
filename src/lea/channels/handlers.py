"""Reusable channel handlers for established LEA command services."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TypeGuard, cast
from uuid import UUID

from lea.actions import (
    ActionProposal,
    ActionStatus,
    ConfirmationPolicy,
    RiskLevel,
    proposal_to_dict,
)
from lea.calendars.contracts import (
    CalendarCollection,
    CalendarEvent,
    CalendarEventQuery,
    CalendarProviderIssue,
)
from lea.calendars.proposal_builders import build_calendar_sync_proposal
from lea.calendars.provider import CalendarProvider
from lea.channels.application import (
    ChannelCommandDefinition,
    DispatchingChannelApplication,
)
from lea.channels.authorisation import ChannelCapability
from lea.channels.contracts import (
    ChannelControl,
    ChannelControlType,
    ChannelRequest,
    ChannelResponse,
)
from lea.channels.result_mapping import (
    ChannelResponseClock,
    channel_response_from_cli_result,
)
from lea.cli.contracts import (
    CliIssue,
    CliResult,
    JsonValue,
    LocalCliExitCode,
)
from lea.cli.proposal_commands import (
    ProposalCommandDependencies,
    execute_proposal_approve,
    execute_proposal_cancel,
    execute_proposal_execute,
    execute_proposal_list,
    execute_proposal_reject,
    execute_proposal_show,
)
from lea.cli.status import StatusDependencies, execute_status
from lea.cli.task_commands import (
    TaskCommandDependencies,
    execute_task_list,
)
from lea.proposals import ProposalSubmissionResult
from lea.runtime import RuntimeProfile
from lea.tasks import (
    TaskCreateRequest,
    TaskListQuery,
    TaskModifyRequest,
    TaskStatus,
    build_task_complete_proposal,
    build_task_create_proposal,
    build_task_delete_proposal,
    build_task_modify_proposal,
)

CommandExecutor = Callable[..., CliResult]
IdentifierSource = Callable[[], str]
ProposalSubmitter = Callable[[ActionProposal], ProposalSubmissionResult]


_SUPPORTED_EXPLICIT_COMMANDS = (
    "/start",
    "/help",
    "/status",
    "/tasks",
    "/calendars",
    "/calendar_events <start-date> <end-date> [calendar-id ...]",
    "/calendar_show <calendar-id> <event-uid>",
    "/calendar_sync",
    "/task_add <description>",
    "/task_show <task-uuid>",
    "/task_modify <task-uuid> <description>",
    "/task_complete <task-uuid>",
    "/task_delete <task-uuid>",
    "/proposals",
    "/proposal_show <proposal-id>",
    "/proposal_approve <proposal-id>",
    "/proposal_reject <proposal-id> [reason]",
    "/proposal_cancel <proposal-id> [reason]",
    "/proposal_execute <proposal-id>",
)


@dataclass(frozen=True, slots=True)
class ChannelHandlerDependencies:
    """Dependencies shared by established channel command handlers."""

    config_path: Path
    expected_profile: RuntimeProfile | None
    clock: ChannelResponseClock
    proposal_submitter: ProposalSubmitter
    proposal_id_source: IdentifierSource
    control_id_source: IdentifierSource
    status_dependencies: StatusDependencies | None = None
    task_dependencies: TaskCommandDependencies | None = None
    calendar_provider: CalendarProvider | None = None
    proposal_dependencies: ProposalCommandDependencies | None = None
    status_executor: CommandExecutor = execute_status
    task_list_executor: CommandExecutor = execute_task_list
    proposal_list_executor: CommandExecutor = execute_proposal_list
    proposal_show_executor: CommandExecutor = execute_proposal_show
    proposal_approve_executor: CommandExecutor = execute_proposal_approve
    proposal_reject_executor: CommandExecutor = execute_proposal_reject
    proposal_cancel_executor: CommandExecutor = execute_proposal_cancel
    proposal_execute_executor: CommandExecutor = execute_proposal_execute

    def __post_init__(self) -> None:
        """Validate stable filesystem configuration."""
        if not self.config_path.is_absolute():
            raise ValueError("config_path must be absolute.")


def build_default_channel_application(
    dependencies: ChannelHandlerDependencies,
) -> DispatchingChannelApplication:
    """Build handlers shared by Telegram and the future Web/PWA."""
    return DispatchingChannelApplication(
        (
            ChannelCommandDefinition(
                "system.start",
                lambda request: _system_start(request, dependencies),
            ),
            ChannelCommandDefinition(
                "system.help",
                lambda request: _system_help(request, dependencies),
            ),
            ChannelCommandDefinition(
                "runtime.status",
                lambda request: _status(request, dependencies),
            ),
            ChannelCommandDefinition(
                "tasks.list",
                lambda request: _tasks_list(request, dependencies),
            ),
            ChannelCommandDefinition(
                "tasks.show",
                lambda request: _tasks_show(request, dependencies),
            ),
            ChannelCommandDefinition(
                "calendar.list_calendars",
                lambda request: _calendar_list_calendars(
                    request,
                    dependencies,
                ),
            ),
            ChannelCommandDefinition(
                "calendar.list_events",
                lambda request: _calendar_list_events(
                    request,
                    dependencies,
                ),
            ),
            ChannelCommandDefinition(
                "calendar.show_event",
                lambda request: _calendar_show_event(
                    request,
                    dependencies,
                ),
            ),
            ChannelCommandDefinition(
                "calendar.sync",
                lambda request: _calendar_sync(request, dependencies),
            ),
            ChannelCommandDefinition(
                "tasks.create",
                lambda request: _tasks_create(request, dependencies),
            ),
            ChannelCommandDefinition(
                "tasks.modify",
                lambda request: _tasks_modify(request, dependencies),
            ),
            ChannelCommandDefinition(
                "tasks.complete",
                lambda request: _tasks_complete(request, dependencies),
            ),
            ChannelCommandDefinition(
                "tasks.delete",
                lambda request: _tasks_delete(request, dependencies),
            ),
            ChannelCommandDefinition(
                "proposals.list",
                lambda request: _proposals_list(request, dependencies),
            ),
            ChannelCommandDefinition(
                "proposals.show",
                lambda request: _proposal_identifier_command(
                    request,
                    dependencies,
                    executor=dependencies.proposal_show_executor,
                    success_message="Proposal loaded.",
                ),
            ),
            ChannelCommandDefinition(
                "proposals.approve",
                lambda request: _proposal_decision(
                    request,
                    dependencies,
                    executor=dependencies.proposal_approve_executor,
                    success_message="Proposal approved.",
                    approved_controls=True,
                ),
            ),
            ChannelCommandDefinition(
                "proposals.reject",
                lambda request: _proposal_decision(
                    request,
                    dependencies,
                    executor=dependencies.proposal_reject_executor,
                    success_message="Proposal rejected.",
                ),
            ),
            ChannelCommandDefinition(
                "proposals.cancel",
                lambda request: _proposal_decision(
                    request,
                    dependencies,
                    executor=dependencies.proposal_cancel_executor,
                    success_message="Proposal cancelled.",
                ),
            ),
            ChannelCommandDefinition(
                "proposals.execute",
                lambda request: _proposal_execute(request, dependencies),
            ),
        ),
        clock=dependencies.clock,
    )


def _system_start(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse:
    """Return a deterministic welcome and the supported command set."""
    return _system_commands_response(
        request,
        dependencies,
        message="LEA is ready. Use /help to review the supported commands.",
    )


def _system_help(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse:
    """Return only commands implemented by the channel application."""
    return _system_commands_response(
        request,
        dependencies,
        message="Supported commands.",
    )


def _system_commands_response(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
    *,
    message: str,
) -> ChannelResponse:
    """Build one deterministic system-command response."""
    invalid = _require_only_metadata(request)

    if invalid is not None:
        return _validation_response(request, dependencies, invalid)

    return _mapped(
        request,
        CliResult.succeeded(
            data={"commands": list(_SUPPORTED_EXPLICIT_COMMANDS)},
        ),
        dependencies,
        success_message=message,
    )


def _status(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse:
    invalid = _require_only_metadata(request)
    if invalid is not None:
        return _validation_response(request, dependencies, invalid)

    result = dependencies.status_executor(
        config_path=dependencies.config_path,
        expected_profile=dependencies.expected_profile,
        dependencies=dependencies.status_dependencies,
    )
    return _mapped(
        request,
        result,
        dependencies,
        success_message="LEA status loaded.",
    )


def _tasks_list(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse:
    parameters = _business_parameters(request)
    arguments = _arguments(parameters)

    if arguments is None:
        return _validation_response(
            request,
            dependencies,
            _issue("channel_arguments_invalid", "arguments must be a list of text."),
        )

    allowed = {"arguments", "uuid", "status", "project", "tag"}
    unknown = sorted(set(parameters) - allowed)
    if unknown:
        return _unknown_parameter(request, dependencies, unknown[0])

    try:
        status_value = parameters.get("status", TaskStatus.PENDING.value)
        status_text = _optional_text(status_value)
        status = TaskStatus(status_text) if status_text is not None else None
        query = TaskListQuery(
            uuid=_optional_text(parameters.get("uuid")),
            status=status,
            project=_optional_text(parameters.get("project")),
            tag=_optional_text(parameters.get("tag")),
        )
    except (TypeError, ValueError) as error:
        return _validation_response(
            request,
            dependencies,
            _issue("task_list_query_invalid", str(error)),
        )

    if arguments:
        return _validation_response(
            request,
            dependencies,
            _issue(
                "channel_arguments_excessive",
                "tasks.list does not accept positional arguments.",
                "arguments",
            ),
        )

    result = dependencies.task_list_executor(
        config_path=dependencies.config_path,
        expected_profile=dependencies.expected_profile,
        query=query,
        dependencies=dependencies.task_dependencies,
    )
    return _mapped(request, result, dependencies, success_message="Tasks loaded.")


def _tasks_show(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse:
    """Read one exact task across all supported provider statuses."""
    identifier = _identifier_parameter(request, name="task_uuid")

    if isinstance(identifier, CliIssue):
        return _validation_response(request, dependencies, identifier)

    result = dependencies.task_list_executor(
        config_path=dependencies.config_path,
        expected_profile=dependencies.expected_profile,
        query=TaskListQuery(
            uuid=identifier,
            status=None,
        ),
        dependencies=dependencies.task_dependencies,
    )

    if not result.success:
        return _mapped(
            request,
            result,
            dependencies,
            success_message="",
        )

    data = result.data

    if not isinstance(data, Mapping):
        return _task_show_data_failure(request, dependencies)

    tasks = data.get("tasks")

    if not isinstance(tasks, list):
        return _task_show_data_failure(request, dependencies)

    if not tasks:
        return _mapped(
            request,
            CliResult.failed(
                exit_code=LocalCliExitCode.NOT_FOUND,
                issues=(
                    CliIssue(
                        code="task_not_found",
                        message="No task matched the supplied UUID.",
                        field="task_uuid",
                    ),
                ),
                data={"task": None},
            ),
            dependencies,
            success_message="",
        )

    if len(tasks) != 1:
        return _mapped(
            request,
            CliResult.failed(
                exit_code=LocalCliExitCode.APPLICATION_ERROR,
                issues=(
                    CliIssue(
                        code="task_lookup_ambiguous",
                        message=(
                            "The task provider returned more than one task for "
                            "an exact UUID lookup."
                        ),
                        field="task_uuid",
                    ),
                ),
                data={"task": None},
            ),
            dependencies,
            success_message="",
        )

    task = tasks[0]

    if not isinstance(task, Mapping):
        return _task_show_data_failure(request, dependencies)

    return _mapped(
        request,
        CliResult.succeeded(
            data=cast(
                JsonValue,
                {
                    "task": dict(task),
                },
            ),
        ),
        dependencies,
        success_message="Task loaded.",
    )


def _task_show_data_failure(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse:
    """Return one safe failure for an invalid task-list result."""
    return _mapped(
        request,
        CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=(
                CliIssue(
                    code="task_lookup_data_invalid",
                    message=(
                        "The task provider returned invalid data for an exact "
                        "task lookup."
                    ),
                    field="tasks",
                ),
            ),
            data={"task": None},
        ),
        dependencies,
        success_message="",
    )


def _calendar_list_calendars(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse:
    """List permitted calendar collections through the provider boundary."""
    denied = _calendar_read_denied(request, dependencies)

    if denied is not None:
        return denied

    parameters = _business_parameters(request)
    allowed = {"arguments"}
    unknown = sorted(set(parameters) - allowed)

    if unknown:
        return _unknown_parameter(request, dependencies, unknown[0])

    arguments = _arguments(parameters)

    if arguments is None:
        return _invalid_arguments(request, dependencies)

    if arguments:
        return _validation_response(
            request,
            dependencies,
            _issue(
                "channel_arguments_excessive",
                "calendar.list_calendars does not accept positional arguments.",
                "arguments",
            ),
        )

    provider = dependencies.calendar_provider

    if provider is None:
        return _calendar_provider_unavailable(request, dependencies)

    result = provider.list_calendars()

    if not result.success:
        return _calendar_provider_failure(
            request,
            dependencies,
            result.issues,
        )

    return _mapped(
        request,
        CliResult.succeeded(
            data=cast(
                JsonValue,
                {
                    "calendars": [
                        _calendar_collection_data(calendar)
                        for calendar in result.calendars
                    ]
                },
            )
        ),
        dependencies,
        success_message="Calendars loaded.",
    )


def _calendar_list_events(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse:
    """List events in one half-open local-date range."""
    denied = _calendar_read_denied(request, dependencies)

    if denied is not None:
        return denied

    parameters = _business_parameters(request)
    allowed = {
        "arguments",
        "start_date",
        "end_date",
        "calendar_ids",
        "include_cancelled",
    }
    unknown = sorted(set(parameters) - allowed)

    if unknown:
        return _unknown_parameter(request, dependencies, unknown[0])

    arguments = _arguments(parameters)

    if arguments is None:
        return _invalid_arguments(request, dependencies)

    try:
        start_date, end_date, positional_calendar_ids = _calendar_event_range(
            parameters, arguments
        )
        explicit_calendar_ids = _calendar_identifier_tuple(
            parameters.get("calendar_ids"),
            field="calendar_ids",
        )

        if positional_calendar_ids and explicit_calendar_ids:
            raise ValueError(
                "calendar_ids must be supplied either positionally or "
                "as a named parameter, not both."
            )

        query = CalendarEventQuery(
            start_date=start_date,
            end_date=end_date,
            calendar_ids=(
                positional_calendar_ids
                if positional_calendar_ids
                else explicit_calendar_ids
            ),
            include_cancelled=_calendar_optional_boolean(
                parameters.get("include_cancelled"),
                field="include_cancelled",
            ),
        )
    except (TypeError, ValueError) as error:
        return _validation_response(
            request,
            dependencies,
            _issue(
                "calendar_event_query_invalid",
                str(error),
            ),
        )

    provider = dependencies.calendar_provider

    if provider is None:
        return _calendar_provider_unavailable(request, dependencies)

    result = provider.list_events(query)

    if not result.success:
        return _calendar_provider_failure(
            request,
            dependencies,
            result.issues,
            not_found_codes={"khal_calendar_not_found"},
        )

    return _mapped(
        request,
        CliResult.succeeded(
            data=cast(
                JsonValue,
                {"events": [_calendar_event_data(event) for event in result.events]},
            )
        ),
        dependencies,
        success_message="Calendar events loaded.",
    )


def _calendar_show_event(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse:
    """Read one exact event using calendar ID and event UID."""
    denied = _calendar_read_denied(request, dependencies)

    if denied is not None:
        return denied

    parameters = _business_parameters(request)
    allowed = {"arguments", "calendar_id", "event_uid"}
    unknown = sorted(set(parameters) - allowed)

    if unknown:
        return _unknown_parameter(request, dependencies, unknown[0])

    arguments = _arguments(parameters)

    if arguments is None:
        return _invalid_arguments(request, dependencies)

    try:
        calendar_id, event_uid = _calendar_event_identity(
            parameters,
            arguments,
        )
    except (TypeError, ValueError) as error:
        return _validation_response(
            request,
            dependencies,
            _issue(
                "calendar_event_identity_invalid",
                str(error),
            ),
        )

    provider = dependencies.calendar_provider

    if provider is None:
        return _calendar_provider_unavailable(request, dependencies)

    result = provider.show_event(calendar_id, event_uid)

    if not result.success:
        return _calendar_provider_failure(
            request,
            dependencies,
            result.issues,
            not_found_codes={
                "khal_calendar_not_found",
                "khal_calendar_event_not_found",
            },
        )

    if result.event is None:
        return _mapped(
            request,
            CliResult.failed(
                exit_code=LocalCliExitCode.INTERNAL_ERROR,
                issues=(
                    _issue(
                        "calendar_event_result_invalid",
                        "Successful calendar event lookup returned no event.",
                    ),
                ),
                data={"event": None},
            ),
            dependencies,
            success_message="",
        )

    return _mapped(
        request,
        CliResult.succeeded(
            data=cast(
                JsonValue,
                {
                    "event": _calendar_event_data(result.event),
                },
            )
        ),
        dependencies,
        success_message="Calendar event loaded.",
    )


def _calendar_read_denied(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse | None:
    """Require Calendar.Read at the channel-neutral command boundary."""
    capability = ChannelCapability.CALENDAR_READ.value

    if capability in request.identity.capabilities:
        return None

    return _mapped(
        request,
        CliResult.failed(
            exit_code=LocalCliExitCode.PERMISSION_DENIED,
            issues=(
                _issue(
                    "calendar_read_capability_required",
                    "Calendar.Read capability is required.",
                    "capabilities",
                ),
            ),
            data={"required_capability": capability},
        ),
        dependencies,
        success_message="",
    )


def _calendar_sync(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse:
    """Submit synchronization as an explicitly confirmed proposal."""
    capability = ChannelCapability.CALENDAR_SYNC.value
    if capability not in request.identity.capabilities:
        return _mapped(
            request,
            CliResult.failed(
                exit_code=LocalCliExitCode.PERMISSION_DENIED,
                issues=(
                    _issue(
                        "calendar_sync_capability_required",
                        "Calendar.Sync capability is required.",
                        "capabilities",
                    ),
                ),
                data={"required_capability": capability},
            ),
            dependencies,
            success_message="",
        )
    parameters = _business_parameters(request)
    unknown = sorted(set(parameters) - {"arguments"})
    if unknown:
        return _unknown_parameter(request, dependencies, unknown[0])
    arguments = _arguments(parameters)
    if arguments is None:
        return _invalid_arguments(request, dependencies)
    if arguments:
        return _validation_response(
            request,
            dependencies,
            _issue(
                "channel_arguments_excessive",
                "calendar.sync does not accept positional arguments.",
                "arguments",
            ),
        )
    try:
        proposal = _interactive_proposal(
            build_calendar_sync_proposal(
                proposal_id=_next_identifier(
                    dependencies.proposal_id_source,
                    field="proposal_id",
                ),
                source=_proposal_source(request),
                created_at=request.received_at,
            )
        )
    except (TypeError, ValueError) as error:
        return _validation_response(
            request,
            dependencies,
            _issue("calendar_sync_invalid", str(error)),
        )
    return _submit_interactive_proposal(request, dependencies, proposal)


def _calendar_provider_unavailable(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse:
    """Return a stable response when no calendar provider is wired."""
    return _mapped(
        request,
        CliResult.failed(
            exit_code=LocalCliExitCode.PROVIDER_UNAVAILABLE,
            issues=(
                _issue(
                    "calendar_provider_unavailable",
                    "The calendar provider is not available.",
                ),
            ),
        ),
        dependencies,
        success_message="",
    )


def _calendar_provider_failure(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
    issues: tuple[CalendarProviderIssue, ...],
    *,
    not_found_codes: set[str] | None = None,
) -> ChannelResponse:
    """Map the first structured provider issue to a channel response."""
    if not issues:
        cli_issue = _issue(
            "calendar_provider_failed",
            "The calendar provider failed without reporting an issue.",
        )
        exit_code = LocalCliExitCode.APPLICATION_ERROR
    else:
        provider_issue = issues[0]
        cli_issue = _issue(
            provider_issue.code,
            provider_issue.message,
            provider_issue.field,
        )
        exit_code = (
            LocalCliExitCode.NOT_FOUND
            if provider_issue.code in (not_found_codes or set())
            else LocalCliExitCode.APPLICATION_ERROR
        )

    return _mapped(
        request,
        CliResult.failed(
            exit_code=exit_code,
            issues=(cli_issue,),
        ),
        dependencies,
        success_message="",
    )


def _calendar_event_range(
    parameters: Mapping[str, object],
    arguments: tuple[str, ...],
) -> tuple[date, date, tuple[str, ...]]:
    """Parse either named or positional date-range input."""
    has_named_range = "start_date" in parameters or "end_date" in parameters

    if has_named_range and arguments:
        raise ValueError(
            "Calendar event dates must be supplied either positionally "
            "or as named parameters, not both."
        )

    if has_named_range:
        start_value = parameters.get("start_date")
        end_value = parameters.get("end_date")
        positional_calendar_ids: tuple[str, ...] = ()
    else:
        if len(arguments) < 2:
            raise ValueError("calendar.list_events requires start_date and end_date.")

        start_value = arguments[0]
        end_value = arguments[1]
        positional_calendar_ids = tuple(
            _calendar_identifier(value, field="calendar_ids") for value in arguments[2:]
        )

    return (
        _calendar_date(start_value, field="start_date"),
        _calendar_date(end_value, field="end_date"),
        positional_calendar_ids,
    )


def _calendar_event_identity(
    parameters: Mapping[str, object],
    arguments: tuple[str, ...],
) -> tuple[str, str]:
    """Parse exact event identity without normalising either component."""
    has_named_identity = "calendar_id" in parameters or "event_uid" in parameters

    if has_named_identity and arguments:
        raise ValueError(
            "Calendar event identity must be supplied either positionally "
            "or as named parameters, not both."
        )

    if has_named_identity:
        calendar_id = parameters.get("calendar_id")
        event_uid = parameters.get("event_uid")
    else:
        if len(arguments) != 2:
            raise ValueError("calendar.show_event requires calendar_id and event_uid.")

        calendar_id, event_uid = arguments

    return (
        _calendar_identifier(calendar_id, field="calendar_id"),
        _calendar_identifier(event_uid, field="event_uid"),
    )


def _calendar_date(value: object, *, field: str) -> date:
    """Require one canonical YYYY-MM-DD local date."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a canonical ISO date string.")

    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be a valid ISO date.") from error

    if parsed.isoformat() != value:
        raise ValueError(f"{field} must use YYYY-MM-DD format.")

    return parsed


def _calendar_identifier(value: object, *, field: str) -> str:
    """Require one exact opaque calendar-provider identifier."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string.")

    if value != value.strip():
        raise ValueError(f"{field} must not contain leading or trailing whitespace.")

    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field} must not contain control characters.")

    return value


def _calendar_identifier_tuple(
    value: object,
    *,
    field: str,
) -> tuple[str, ...]:
    """Return one optional array of exact provider identifiers."""
    if value is None:
        return ()

    if not _is_sequence(value):
        raise TypeError(f"{field} must be an array of non-empty strings.")

    return tuple(_calendar_identifier(item, field=field) for item in value)


def _calendar_optional_boolean(
    value: object,
    *,
    field: str,
) -> bool:
    """Return one optional boolean defaulting to false."""
    if value is None:
        return False

    if not isinstance(value, bool):
        raise TypeError(f"{field} must be a boolean.")

    return value


def _calendar_collection_data(
    calendar: CalendarCollection,
) -> dict[str, JsonValue]:
    """Serialise one calendar collection for channel output."""
    return {
        "calendar_id": calendar.calendar_id,
        "display_name": calendar.display_name,
        "read_only": calendar.read_only,
    }


def _calendar_event_data(
    event: CalendarEvent,
) -> dict[str, JsonValue]:
    """Serialise one canonical event for channel output."""
    return {
        "calendar_id": event.calendar_id,
        "event_uid": event.event_uid,
        "summary": event.summary,
        "timing": {
            "start": event.timing.start.isoformat(),
            "end": event.timing.end.isoformat(),
            "all_day": event.timing.all_day,
            "timezone": event.timing.timezone,
        },
        "description": event.description,
        "location": event.location,
        "cancelled": event.cancelled,
    }


def _tasks_create(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse:
    parameters = _business_parameters(request)
    allowed = {
        "arguments",
        "description",
        "project",
        "due",
        "priority",
        "tags",
    }
    unknown = sorted(set(parameters) - allowed)
    if unknown:
        return _unknown_parameter(request, dependencies, unknown[0])

    arguments = _arguments(parameters)
    if arguments is None:
        return _invalid_arguments(request, dependencies)

    description = parameters.get("description")
    if description is None and arguments:
        description = " ".join(arguments)

    try:
        task_request = TaskCreateRequest(
            description=_required_text(description, field="description"),
            project=_optional_text(parameters.get("project")),
            due=_optional_utc_datetime(parameters.get("due"), field="due"),
            priority=_optional_text(parameters.get("priority")),
            tags=_text_tuple(parameters.get("tags"), field="tags"),
        )
        proposal = _interactive_proposal(
            build_task_create_proposal(
                task_request,
                proposal_id=_next_identifier(
                    dependencies.proposal_id_source,
                    field="proposal_id",
                ),
                source=_proposal_source(request),
                created_at=request.received_at,
            )
        )
    except (TypeError, ValueError) as error:
        return _validation_response(
            request,
            dependencies,
            _issue("task_creation_invalid", str(error)),
        )

    return _submit_interactive_proposal(request, dependencies, proposal)


def _tasks_modify(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse:
    parameters = _business_parameters(request)
    allowed = {
        "arguments",
        "task_uuid",
        "description",
        "project",
        "due",
        "clear_due",
        "priority",
        "clear_priority",
        "add_tags",
        "remove_tags",
    }
    unknown = sorted(set(parameters) - allowed)
    if unknown:
        return _unknown_parameter(request, dependencies, unknown[0])

    arguments = _arguments(parameters)
    if arguments is None:
        return _invalid_arguments(request, dependencies)

    task_uuid = parameters.get("task_uuid")
    description = parameters.get("description")

    if task_uuid is None and arguments:
        task_uuid = arguments[0]

    if description is None and len(arguments) > 1:
        description = " ".join(arguments[1:])

    try:
        modify_request = TaskModifyRequest(
            task_uuid=_canonical_uuid(task_uuid, field="task_uuid"),
            description=_optional_text(description),
            project=_optional_text(parameters.get("project")),
            due=_optional_utc_datetime(parameters.get("due"), field="due"),
            clear_due=_boolean(
                parameters.get("clear_due", False),
                field="clear_due",
            ),
            priority=_optional_text(parameters.get("priority")),
            clear_priority=_boolean(
                parameters.get("clear_priority", False),
                field="clear_priority",
            ),
            add_tags=_text_tuple(parameters.get("add_tags"), field="add_tags"),
            remove_tags=_text_tuple(
                parameters.get("remove_tags"),
                field="remove_tags",
            ),
        )
        proposal = _interactive_proposal(
            build_task_modify_proposal(
                modify_request,
                proposal_id=_next_identifier(
                    dependencies.proposal_id_source,
                    field="proposal_id",
                ),
                source=_proposal_source(request),
                created_at=request.received_at,
            )
        )
    except (TypeError, ValueError) as error:
        return _validation_response(
            request,
            dependencies,
            _issue("task_modification_invalid", str(error)),
        )

    return _submit_interactive_proposal(request, dependencies, proposal)


def _tasks_complete(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse:
    identifier = _identifier_parameter(request, name="task_uuid")

    if isinstance(identifier, CliIssue):
        return _validation_response(request, dependencies, identifier)

    try:
        proposal = _interactive_proposal(
            build_task_complete_proposal(
                identifier,
                proposal_id=_next_identifier(
                    dependencies.proposal_id_source,
                    field="proposal_id",
                ),
                source=_proposal_source(request),
                created_at=request.received_at,
            )
        )
    except (TypeError, ValueError) as error:
        return _validation_response(
            request,
            dependencies,
            _issue("task_completion_invalid", str(error)),
        )

    return _submit_interactive_proposal(request, dependencies, proposal)


def _tasks_delete(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse:
    identifier = _identifier_parameter(request, name="task_uuid")

    if isinstance(identifier, CliIssue):
        return _validation_response(request, dependencies, identifier)

    try:
        proposal = _interactive_proposal(
            build_task_delete_proposal(
                identifier,
                proposal_id=_next_identifier(
                    dependencies.proposal_id_source,
                    field="proposal_id",
                ),
                source=_proposal_source(request),
                created_at=request.received_at,
            )
        )
    except (TypeError, ValueError) as error:
        return _validation_response(
            request,
            dependencies,
            _issue("task_deletion_invalid", str(error)),
        )

    return _submit_interactive_proposal(request, dependencies, proposal)


def _interactive_proposal(
    proposal: ActionProposal,
) -> ActionProposal:
    """Require explicit confirmation for an interactive mutation or sync."""
    return replace(
        proposal,
        confirmation_policy=ConfirmationPolicy.ALWAYS,
    )


def _submit_interactive_proposal(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
    proposal: ActionProposal,
) -> ChannelResponse:
    result = dependencies.proposal_submitter(proposal)

    if not result.success:
        data: dict[str, object] = {
            "audit_persisted": result.audit_persisted,
            "proposal_persisted": result.proposal_persisted,
            "persisted_audit_event_count": (result.persisted_audit_event_count),
        }

        if result.proposal is not None:
            data["proposal"] = proposal_to_dict(result.proposal)

        return _mapped(
            request,
            CliResult.failed(
                exit_code=LocalCliExitCode.APPLICATION_ERROR,
                issues=tuple(
                    CliIssue(
                        code=issue.code,
                        message=issue.message,
                        field=issue.field,
                    )
                    for issue in result.issues
                ),
                data=cast(JsonValue, data),
            ),
            dependencies,
            success_message="",
        )

    submitted = result.proposal

    if submitted is None:
        raise RuntimeError("Successful proposal submission returned no proposal.")

    awaiting_confirmation = submitted.status is ActionStatus.AWAITING_CONFIRMATION
    message = (
        "Proposal awaiting confirmation."
        if awaiting_confirmation
        else "Proposal approved and awaiting explicit execution."
    )
    next_operation = "confirm" if awaiting_confirmation else "execute"
    response = _mapped(
        request,
        CliResult.succeeded(
            data=cast(
                JsonValue,
                {
                    "proposal": proposal_to_dict(submitted),
                    "audit_persisted": result.audit_persisted,
                    "proposal_persisted": result.proposal_persisted,
                    "persisted_audit_event_count": (result.persisted_audit_event_count),
                    "next_operation": next_operation,
                },
            )
        ),
        dependencies,
        success_message=message,
    )

    if not awaiting_confirmation:
        return response

    return replace(
        response,
        controls=_confirmation_controls(
            submitted.proposal_id,
            dependencies,
        ),
    )


def _confirmation_controls(
    proposal_id: str,
    dependencies: ChannelHandlerDependencies,
) -> tuple[ChannelControl, ...]:
    definitions = (
        ("Approve", "proposal.approve"),
        ("Reject", "proposal.reject"),
        ("Cancel", "proposal.cancel"),
    )
    capability = ChannelCapability.PROPOSALS_CONFIRM.value

    return tuple(
        ChannelControl(
            control_id=_next_identifier(
                dependencies.control_id_source,
                field="control_id",
            ),
            label=label,
            control_type=ChannelControlType.ACTION,
            action=action,
            parameters={"proposal_id": proposal_id},
            required_capability=capability,
        )
        for label, action in definitions
    )


def _approved_controls(
    proposal: ActionProposal,
    dependencies: ChannelHandlerDependencies,
) -> tuple[ChannelControl, ...]:
    """Return controls valid after one proposal is approved."""
    definitions: list[tuple[str, str, str]] = []
    execution_capability = _proposal_execution_capability(proposal.risk_level)

    if execution_capability is not None:
        definitions.append(
            (
                "Execute",
                "proposal.execute",
                execution_capability.value,
            )
        )

    definitions.append(
        (
            "Cancel",
            "proposal.cancel",
            ChannelCapability.PROPOSALS_CONFIRM.value,
        )
    )

    return tuple(
        ChannelControl(
            control_id=_next_identifier(
                dependencies.control_id_source,
                field="control_id",
            ),
            label=label,
            control_type=ChannelControlType.ACTION,
            action=action,
            parameters={"proposal_id": proposal.proposal_id},
            required_capability=capability,
        )
        for label, action, capability in definitions
    )


def _proposals_list(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse:
    parameters = _business_parameters(request)
    allowed = {"arguments", "status", "action_type", "limit"}
    unknown = sorted(set(parameters) - allowed)
    if unknown:
        return _unknown_parameter(request, dependencies, unknown[0])

    arguments = _arguments(parameters)
    if arguments is None:
        return _invalid_arguments(request, dependencies)
    if arguments:
        return _validation_response(
            request,
            dependencies,
            _issue(
                "channel_arguments_excessive",
                "proposals.list does not accept positional arguments.",
                "arguments",
            ),
        )

    try:
        status_text = _optional_text(parameters.get("status"))
        status = ActionStatus(status_text) if status_text is not None else None
        limit = _optional_positive_integer(parameters.get("limit"), field="limit")
    except (TypeError, ValueError) as error:
        return _validation_response(
            request,
            dependencies,
            _issue("proposal_list_query_invalid", str(error)),
        )

    result = dependencies.proposal_list_executor(
        config_path=dependencies.config_path,
        expected_profile=dependencies.expected_profile,
        status=status,
        action_type=_optional_text(parameters.get("action_type")),
        limit=limit,
        dependencies=dependencies.proposal_dependencies,
    )
    return _mapped(request, result, dependencies, success_message="Proposals loaded.")


def _proposal_execute(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse:
    """Authorise execution from the stored proposal risk before execution."""
    identifier = _identifier_parameter(request, name="proposal_id")

    if isinstance(identifier, CliIssue):
        return _validation_response(request, dependencies, identifier)

    shown = dependencies.proposal_show_executor(
        config_path=dependencies.config_path,
        expected_profile=dependencies.expected_profile,
        proposal_id=identifier,
        dependencies=dependencies.proposal_dependencies,
    )

    if not shown.success:
        return _mapped(
            request,
            shown,
            dependencies,
            success_message="",
        )

    data = shown.data

    if not isinstance(data, Mapping):
        return _proposal_execution_data_failure(request, dependencies)

    raw_proposal = data.get("proposal")

    if not isinstance(raw_proposal, Mapping):
        return _proposal_execution_data_failure(request, dependencies)

    try:
        proposal = ActionProposal.from_dict(cast(Mapping[str, object], raw_proposal))
    except Exception:
        return _proposal_execution_data_failure(request, dependencies)

    capability = _proposal_execution_capability(proposal.risk_level)

    if capability is None:
        return _mapped(
            request,
            CliResult.failed(
                exit_code=LocalCliExitCode.PERMISSION_DENIED,
                issues=(
                    CliIssue(
                        code="proposal_execution_risk_unsupported",
                        message=(
                            "Critical-risk proposals cannot be executed "
                            "through this channel."
                        ),
                        field="risk_level",
                    ),
                ),
                data=cast(
                    JsonValue,
                    {
                        "proposal_id": proposal.proposal_id,
                        "risk_level": proposal.risk_level.value,
                    },
                ),
            ),
            dependencies,
            success_message="",
        )

    if capability.value not in request.identity.capabilities:
        return _mapped(
            request,
            CliResult.failed(
                exit_code=LocalCliExitCode.PERMISSION_DENIED,
                issues=(
                    CliIssue(
                        code="proposal_execution_capability_required",
                        message=(
                            "The authenticated channel identity lacks the "
                            "capability required to execute this proposal."
                        ),
                        field="capabilities",
                    ),
                ),
                data=cast(
                    JsonValue,
                    {
                        "proposal_id": proposal.proposal_id,
                        "risk_level": proposal.risk_level.value,
                        "required_capability": capability.value,
                    },
                ),
            ),
            dependencies,
            success_message="",
        )

    result = dependencies.proposal_execute_executor(
        config_path=dependencies.config_path,
        expected_profile=dependencies.expected_profile,
        proposal_id=identifier,
        dependencies=dependencies.proposal_dependencies,
    )
    return _mapped(
        request,
        result,
        dependencies,
        success_message="Proposal executed.",
    )


def _proposal_execution_capability(
    risk_level: RiskLevel,
) -> ChannelCapability | None:
    """Return the exact channel execution capability for one risk."""
    return {
        RiskLevel.LOW: ChannelCapability.PROPOSALS_EXECUTE_LOW_RISK,
        RiskLevel.MEDIUM: ChannelCapability.PROPOSALS_EXECUTE_MEDIUM_RISK,
        RiskLevel.HIGH: ChannelCapability.PROPOSALS_EXECUTE_HIGH_RISK,
    }.get(risk_level)


def _proposal_execution_data_failure(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse:
    """Return one safe failure for invalid persistent proposal data."""
    return _mapped(
        request,
        CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=(
                CliIssue(
                    code="proposal_execution_data_invalid",
                    message=(
                        "The persistent proposal could not be inspected "
                        "for execution authorisation."
                    ),
                    field="proposal",
                ),
            ),
            data={"proposal": None},
        ),
        dependencies,
        success_message="",
    )


def _proposal_identifier_command(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
    *,
    executor: CommandExecutor,
    success_message: str,
) -> ChannelResponse:
    identifier = _identifier_parameter(request, name="proposal_id")

    if isinstance(identifier, CliIssue):
        return _validation_response(request, dependencies, identifier)

    result = executor(
        config_path=dependencies.config_path,
        expected_profile=dependencies.expected_profile,
        proposal_id=identifier,
        dependencies=dependencies.proposal_dependencies,
    )
    return _mapped(request, result, dependencies, success_message=success_message)


def _proposal_decision(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
    *,
    executor: CommandExecutor,
    success_message: str,
    approved_controls: bool = False,
) -> ChannelResponse:
    parameters = _business_parameters(request)
    allowed = {"arguments", "proposal_id", "reason"}
    unknown = sorted(set(parameters) - allowed)
    if unknown:
        return _unknown_parameter(request, dependencies, unknown[0])

    arguments = _arguments(parameters)
    if arguments is None:
        return _invalid_arguments(request, dependencies)

    proposal_id = parameters.get("proposal_id")
    reason = parameters.get("reason")

    if proposal_id is None and arguments:
        proposal_id = arguments[0]

    if reason is None and len(arguments) > 1:
        reason = " ".join(arguments[1:])

    try:
        canonical = _canonical_uuid(proposal_id, field="proposal_id")
        reason_text = _optional_text(reason)
    except (TypeError, ValueError) as error:
        return _validation_response(
            request,
            dependencies,
            _issue("proposal_decision_invalid", str(error)),
        )

    result = executor(
        config_path=dependencies.config_path,
        expected_profile=dependencies.expected_profile,
        proposal_id=canonical,
        actor=_actor(request),
        reason=reason_text,
        dependencies=dependencies.proposal_dependencies,
    )
    response = _safe_decision_actor(
        _mapped(
            request,
            result,
            dependencies,
            success_message=success_message,
        ),
        request,
    )

    if not approved_controls or not result.success:
        return response

    proposal = _proposal_from_cli_result(result)

    if proposal is None or proposal.status is not ActionStatus.APPROVED:
        return response

    return replace(
        response,
        controls=_approved_controls(proposal, dependencies),
    )


def _safe_decision_actor(
    response: ChannelResponse,
    request: ChannelRequest,
) -> ChannelResponse:
    """Replace a private decision actor with a channel-role label."""
    if response.data is None or "actor" not in response.data:
        return response

    data = dict(response.data)
    data["actor"] = _proposal_source(request)

    return replace(
        response,
        data=data,
    )


def _proposal_from_cli_result(
    result: CliResult,
) -> ActionProposal | None:
    """Read one canonical proposal from a successful CLI result."""
    data = result.data

    if not isinstance(data, Mapping):
        return None

    raw_proposal = data.get("proposal")

    if not isinstance(raw_proposal, Mapping):
        return None

    try:
        return ActionProposal.from_dict(cast(Mapping[str, object], raw_proposal))
    except Exception:
        return None


def _identifier_parameter(
    request: ChannelRequest,
    *,
    name: str,
) -> str | CliIssue:
    parameters = _business_parameters(request)
    allowed = {"arguments", name}
    unknown = sorted(set(parameters) - allowed)
    if unknown:
        return _issue(
            "channel_parameter_unknown",
            f"Unknown channel parameter '{unknown[0]}'.",
            unknown[0],
        )

    arguments = _arguments(parameters)
    if arguments is None:
        return _issue(
            "channel_arguments_invalid",
            "arguments must be a list of text.",
            "arguments",
        )

    value = parameters.get(name)

    if value is None and len(arguments) == 1:
        value = arguments[0]
    elif arguments and value is not None:
        return _issue(
            "channel_identifier_ambiguous",
            f"{name} must be supplied once.",
            name,
        )
    elif len(arguments) > 1:
        return _issue(
            "channel_arguments_excessive",
            "Only one identifier argument is permitted.",
            "arguments",
        )

    try:
        return _canonical_uuid(value, field=name)
    except (TypeError, ValueError) as error:
        return _issue("channel_identifier_invalid", str(error), name)


def _business_parameters(request: ChannelRequest) -> dict[str, object]:
    return {
        key: value
        for key, value in request.parameters.items()
        if key not in {"telegram_message_id", "callback_query_id"}
    }


def _require_only_metadata(request: ChannelRequest) -> CliIssue | None:
    parameters = _business_parameters(request)
    arguments = _arguments(parameters)

    if arguments is None:
        return _issue(
            "channel_arguments_invalid",
            "arguments must be a list of text.",
            "arguments",
        )

    unknown = sorted(set(parameters) - {"arguments"})
    if unknown:
        return _issue(
            "channel_parameter_unknown",
            f"Unknown channel parameter '{unknown[0]}'.",
            unknown[0],
        )

    if arguments:
        return _issue(
            "channel_arguments_excessive",
            "This command does not accept positional arguments.",
            "arguments",
        )

    return None


def _arguments(parameters: Mapping[str, object]) -> tuple[str, ...] | None:
    value = parameters.get("arguments", ())

    if not _is_sequence(value):
        return None

    if any(not isinstance(item, str) or not item.strip() for item in value):
        return None

    return tuple(item for item in value if isinstance(item, str))


def _is_sequence(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    )


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty.")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Optional text values must be non-empty.")
    return value


def _text_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not _is_sequence(value):
        raise TypeError(f"{field} must be a list of text.")
    result = tuple(value)
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise ValueError(f"{field} must contain non-empty text.")
    return tuple(item for item in result if isinstance(item, str))


def _boolean(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field} must be a boolean.")
    return value


def _optional_utc_datetime(
    value: object,
    *,
    field: str,
) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field} must be an ISO timestamp string.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be a valid ISO timestamp.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware.")
    if parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError(f"{field} must use UTC.")
    return parsed.astimezone(UTC)


def _next_identifier(
    source: IdentifierSource,
    *,
    field: str,
) -> str:
    return _canonical_uuid(source(), field=field)


def _proposal_source(request: ChannelRequest) -> str:
    return f"{request.identity.channel.value}:{request.identity.role}"


def _canonical_uuid(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string.")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ValueError(f"{field} must be a valid UUID.") from error
    if str(parsed) != value:
        raise ValueError(f"{field} must use canonical lower-case UUID format.")
    return value


def _optional_positive_integer(value: object, *, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer.")
    return value


def _actor(request: ChannelRequest) -> str:
    return f"{request.identity.channel.value}:{request.identity.user_id}"


def _mapped(
    request: ChannelRequest,
    result: CliResult,
    dependencies: ChannelHandlerDependencies,
    *,
    success_message: str,
) -> ChannelResponse:
    return channel_response_from_cli_result(
        request,
        result,
        clock=dependencies.clock,
        success_message=success_message,
    )


def _invalid_arguments(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse:
    return _validation_response(
        request,
        dependencies,
        _issue(
            "channel_arguments_invalid",
            "arguments must be a list of text.",
            "arguments",
        ),
    )


def _unknown_parameter(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
    field: str,
) -> ChannelResponse:
    return _validation_response(
        request,
        dependencies,
        _issue(
            "channel_parameter_unknown",
            f"Unknown channel parameter '{field}'.",
            field,
        ),
    )


def _validation_response(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
    issue: CliIssue,
) -> ChannelResponse:
    return _mapped(
        request,
        CliResult.failed(
            exit_code=LocalCliExitCode.VALIDATION_ERROR,
            issues=(issue,),
        ),
        dependencies,
        success_message="",
    )


def _issue(code: str, message: str, field: str | None = None) -> CliIssue:
    return CliIssue(code=code, message=message, field=field)
