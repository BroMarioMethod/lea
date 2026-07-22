"""Provider-neutral task action handlers."""

from collections.abc import Mapping
from datetime import datetime

from lea.actions import ActionHandler, ActionHandlerRegistry, ActionProposal
from lea.tasks.contracts import (
    TaskCreateRequest,
    TaskCreateResult,
    TaskModifyRequest,
    TaskMutationResult,
    TaskProviderIssue,
    TaskRecord,
)
from lea.tasks.provider import TaskProvider


class TaskActionHandlerError(RuntimeError):
    """Deterministic failure raised by a task action handler."""

    def __init__(self, *, code: str, message: str) -> None:
        if not code.strip():
            raise ValueError("code must be non-empty.")

        if not message.strip():
            raise ValueError("message must be non-empty.")

        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def create_task_action_handler(provider: TaskProvider) -> ActionHandler:
    """Return a handler for one ``task.create`` proposal."""

    def handle(proposal: ActionProposal) -> Mapping[str, object]:
        parameters = _parameters(
            proposal,
            allowed={"description", "project", "priority", "tags"},
        )
        request = TaskCreateRequest(
            description=_required_string(parameters, "description"),
            project=_optional_string(parameters, "project"),
            priority=_optional_priority(parameters, "priority"),
            tags=_optional_string_tuple(parameters, "tags"),
        )
        return _create_output(provider.create_task(request))

    return handle


def modify_task_action_handler(provider: TaskProvider) -> ActionHandler:
    """Return a handler for one ``task.modify`` proposal."""

    def handle(proposal: ActionProposal) -> Mapping[str, object]:
        parameters = _parameters(
            proposal,
            allowed={
                "uuid",
                "description",
                "project",
                "priority",
                "add_tags",
                "remove_tags",
            },
        )
        request = TaskModifyRequest(
            task_uuid=_required_string(parameters, "uuid"),
            description=_optional_string(parameters, "description"),
            project=_optional_string(parameters, "project"),
            priority=_optional_priority(parameters, "priority"),
            add_tags=_optional_string_tuple(parameters, "add_tags"),
            remove_tags=_optional_string_tuple(parameters, "remove_tags"),
        )
        return _mutation_output(provider.modify_task(request))

    return handle


def complete_task_action_handler(provider: TaskProvider) -> ActionHandler:
    """Return a handler for one ``task.complete`` proposal."""

    def handle(proposal: ActionProposal) -> Mapping[str, object]:
        parameters = _parameters(proposal, allowed={"uuid"})
        task_uuid = _required_string(parameters, "uuid")
        return _mutation_output(provider.complete_task(task_uuid))

    return handle


def delete_task_action_handler(provider: TaskProvider) -> ActionHandler:
    """Return a handler for one ``task.delete`` proposal."""

    def handle(proposal: ActionProposal) -> Mapping[str, object]:
        parameters = _parameters(proposal, allowed={"uuid"})
        task_uuid = _required_string(parameters, "uuid")
        return _mutation_output(provider.delete_task(task_uuid))

    return handle


def task_action_handler_registry(
    provider: TaskProvider,
) -> ActionHandlerRegistry:
    """Return the canonical task action-handler registry."""
    registry = ActionHandlerRegistry()
    registry.register("task.create", create_task_action_handler(provider))
    registry.register("task.modify", modify_task_action_handler(provider))
    registry.register("task.complete", complete_task_action_handler(provider))
    registry.register("task.delete", delete_task_action_handler(provider))
    return registry


def _parameters(
    proposal: ActionProposal,
    *,
    allowed: set[str],
) -> Mapping[str, object]:
    parameters = proposal.parameters
    unknown = sorted(set(parameters) - allowed)

    if unknown:
        raise TaskActionHandlerError(
            code="task_action_parameter_unknown",
            message=f"Unsupported task action parameter: {unknown[0]}.",
        )

    return parameters


def _required_string(
    parameters: Mapping[str, object],
    field: str,
) -> str:
    value = parameters.get(field)

    if not isinstance(value, str) or not value.strip():
        raise TaskActionHandlerError(
            code="task_action_parameter_invalid",
            message=f"{field} must be a non-empty string.",
        )

    return value


def _optional_string(
    parameters: Mapping[str, object],
    field: str,
) -> str | None:
    if field not in parameters:
        return None

    value = parameters[field]

    if not isinstance(value, str) or not value.strip():
        raise TaskActionHandlerError(
            code="task_action_parameter_invalid",
            message=f"{field} must be a non-empty string when provided.",
        )

    return value


def _optional_priority(
    parameters: Mapping[str, object],
    field: str,
) -> str | None:
    value = _optional_string(parameters, field)

    if value is not None and value not in {"H", "M", "L"}:
        raise TaskActionHandlerError(
            code="task_action_parameter_invalid",
            message="priority must be 'H', 'M' or 'L' when provided.",
        )

    return value


def _optional_string_tuple(
    parameters: Mapping[str, object],
    field: str,
) -> tuple[str, ...]:
    if field not in parameters:
        return ()

    value = parameters[field]

    if not isinstance(value, (list, tuple)):
        raise TaskActionHandlerError(
            code="task_action_parameter_invalid",
            message=f"{field} must be an array of non-empty strings.",
        )

    values: list[str] = []

    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise TaskActionHandlerError(
                code="task_action_parameter_invalid",
                message=f"{field} must contain only non-empty strings.",
            )

        values.append(item)

    return tuple(values)


def _create_output(result: TaskCreateResult) -> Mapping[str, object]:
    if not result.success:
        _raise_provider_failure(result.issues)

    if result.task is None:
        raise TaskActionHandlerError(
            code="task_action_result_invalid",
            message="Successful task creation returned no task.",
        )

    return {"task": _task_to_dict(result.task)}


def _mutation_output(result: TaskMutationResult) -> Mapping[str, object]:
    if not result.success:
        _raise_provider_failure(result.issues)

    if result.task is None:
        raise TaskActionHandlerError(
            code="task_action_result_invalid",
            message="Successful task mutation returned no task.",
        )

    return {"task": _task_to_dict(result.task)}


def _raise_provider_failure(
    issues: tuple[TaskProviderIssue, ...],
) -> None:
    if not issues:
        raise TaskActionHandlerError(
            code="task_provider_failed",
            message="The task provider failed without reporting an issue.",
        )

    issue = issues[0]
    raise TaskActionHandlerError(
        code=issue.code,
        message=issue.message,
    )


def _task_to_dict(task: TaskRecord) -> dict[str, object]:
    return {
        "uuid": task.uuid,
        "description": task.description,
        "status": task.status.value,
        "entry": _timestamp(task.entry),
        "modified": _optional_timestamp(task.modified),
        "due": _optional_timestamp(task.due),
        "project": task.project,
        "tags": list(task.tags),
        "priority": task.priority,
    }


def _timestamp(value: datetime) -> str:
    return value.isoformat()


def _optional_timestamp(value: datetime | None) -> str | None:
    return None if value is None else _timestamp(value)
