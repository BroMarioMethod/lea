"""Reusable channel handlers for established LEA command services."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeGuard, cast
from uuid import UUID

from lea.actions import ActionProposal, ActionStatus, proposal_to_dict
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
                "runtime.status",
                lambda request: _status(request, dependencies),
            ),
            ChannelCommandDefinition(
                "tasks.list",
                lambda request: _tasks_list(request, dependencies),
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
                lambda request: _proposal_identifier_command(
                    request,
                    dependencies,
                    executor=dependencies.proposal_execute_executor,
                    success_message="Proposal executed.",
                ),
            ),
        ),
        clock=dependencies.clock,
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
        proposal = build_task_create_proposal(
            task_request,
            proposal_id=_next_identifier(
                dependencies.proposal_id_source,
                field="proposal_id",
            ),
            source=_proposal_source(request),
            created_at=request.received_at,
        )
    except (TypeError, ValueError) as error:
        return _validation_response(
            request,
            dependencies,
            _issue("task_creation_invalid", str(error)),
        )

    return _submit_task_proposal(request, dependencies, proposal)


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
        proposal = build_task_modify_proposal(
            modify_request,
            proposal_id=_next_identifier(
                dependencies.proposal_id_source,
                field="proposal_id",
            ),
            source=_proposal_source(request),
            created_at=request.received_at,
        )
    except (TypeError, ValueError) as error:
        return _validation_response(
            request,
            dependencies,
            _issue("task_modification_invalid", str(error)),
        )

    return _submit_task_proposal(request, dependencies, proposal)


def _tasks_complete(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse:
    identifier = _identifier_parameter(request, name="task_uuid")

    if isinstance(identifier, CliIssue):
        return _validation_response(request, dependencies, identifier)

    try:
        proposal = build_task_complete_proposal(
            identifier,
            proposal_id=_next_identifier(
                dependencies.proposal_id_source,
                field="proposal_id",
            ),
            source=_proposal_source(request),
            created_at=request.received_at,
        )
    except (TypeError, ValueError) as error:
        return _validation_response(
            request,
            dependencies,
            _issue("task_completion_invalid", str(error)),
        )

    return _submit_task_proposal(request, dependencies, proposal)


def _tasks_delete(
    request: ChannelRequest,
    dependencies: ChannelHandlerDependencies,
) -> ChannelResponse:
    identifier = _identifier_parameter(request, name="task_uuid")

    if isinstance(identifier, CliIssue):
        return _validation_response(request, dependencies, identifier)

    try:
        proposal = build_task_delete_proposal(
            identifier,
            proposal_id=_next_identifier(
                dependencies.proposal_id_source,
                field="proposal_id",
            ),
            source=_proposal_source(request),
            created_at=request.received_at,
        )
    except (TypeError, ValueError) as error:
        return _validation_response(
            request,
            dependencies,
            _issue("task_deletion_invalid", str(error)),
        )

    return _submit_task_proposal(request, dependencies, proposal)


def _submit_task_proposal(
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
    return _mapped(request, result, dependencies, success_message=success_message)


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
