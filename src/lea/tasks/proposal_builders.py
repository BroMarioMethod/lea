"""Deterministic builders for task action proposals."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

from lea.actions import (
    ActionProposal,
    ConfirmationPolicy,
    RiskLevel,
)
from lea.tasks.contracts import TaskCreateRequest, TaskModifyRequest


def build_task_create_proposal(
    request: TaskCreateRequest,
    *,
    proposal_id: str,
    source: str,
    created_at: datetime,
) -> ActionProposal:
    """Build one low-risk task-creation proposal."""
    parameters: dict[str, object] = {
        "description": request.description,
    }
    _add_optional(parameters, "project", request.project)
    _add_optional_timestamp(parameters, "due", request.due)
    _add_optional(parameters, "priority", request.priority)

    if request.tags:
        parameters["tags"] = list(request.tags)

    return _proposal(
        action="task.create",
        parameters=parameters,
        proposal_id=proposal_id,
        source=source,
        created_at=created_at,
        risk_level=RiskLevel.LOW,
        reason="Create one task.",
    )


def build_task_modify_proposal(
    request: TaskModifyRequest,
    *,
    proposal_id: str,
    source: str,
    created_at: datetime,
) -> ActionProposal:
    """Build one medium-risk task-modification proposal."""
    parameters: dict[str, object] = {
        "uuid": request.task_uuid,
    }
    _add_optional(parameters, "description", request.description)
    _add_optional(parameters, "project", request.project)
    _add_optional_timestamp(parameters, "due", request.due)
    _add_optional(parameters, "priority", request.priority)

    if request.clear_due:
        parameters["clear_due"] = True

    if request.clear_priority:
        parameters["clear_priority"] = True

    if request.add_tags:
        parameters["add_tags"] = list(request.add_tags)

    if request.remove_tags:
        parameters["remove_tags"] = list(request.remove_tags)

    return _proposal(
        action="task.modify",
        parameters=parameters,
        proposal_id=proposal_id,
        source=source,
        created_at=created_at,
        risk_level=RiskLevel.MEDIUM,
        reason="Modify one task.",
    )


def build_task_complete_proposal(
    task_uuid: str,
    *,
    proposal_id: str,
    source: str,
    created_at: datetime,
) -> ActionProposal:
    """Build one medium-risk task-completion proposal."""
    return _proposal(
        action="task.complete",
        parameters={"uuid": _canonical_uuid(task_uuid)},
        proposal_id=proposal_id,
        source=source,
        created_at=created_at,
        risk_level=RiskLevel.MEDIUM,
        reason="Complete one task.",
    )


def build_task_delete_proposal(
    task_uuid: str,
    *,
    proposal_id: str,
    source: str,
    created_at: datetime,
) -> ActionProposal:
    """Build one high-risk task-deletion proposal."""
    return _proposal(
        action="task.delete",
        parameters={"uuid": _canonical_uuid(task_uuid)},
        proposal_id=proposal_id,
        source=source,
        created_at=created_at,
        risk_level=RiskLevel.HIGH,
        reason="Delete one task.",
    )


def _proposal(
    *,
    action: str,
    parameters: Mapping[str, object],
    proposal_id: str,
    source: str,
    created_at: datetime,
    risk_level: RiskLevel,
    reason: str,
) -> ActionProposal:
    """Construct one canonical proposed task action."""
    return ActionProposal(
        proposal_id=proposal_id,
        action=action,
        parameters=parameters,
        source=source,
        risk_level=risk_level,
        confirmation_policy=ConfirmationPolicy.WHEN_REQUIRED,
        created_at=_utc_timestamp(created_at),
        reason=reason,
    )


def _add_optional(
    parameters: dict[str, object],
    field: str,
    value: str | None,
) -> None:
    """Add one present optional text field."""
    if value is not None:
        parameters[field] = value


def _add_optional_timestamp(
    parameters: dict[str, object],
    field: str,
    value: datetime | None,
) -> None:
    """Add one present optional UTC timestamp."""
    if value is not None:
        parameters[field] = _utc_timestamp(value).isoformat()


def _utc_timestamp(value: datetime) -> datetime:
    """Require and return one timezone-aware UTC timestamp."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Task proposal timestamps must be timezone-aware.")

    if value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("Task proposal timestamps must use UTC.")

    return value.astimezone(UTC)


def _canonical_uuid(value: str) -> str:
    """Require one canonical lower-case task UUID."""
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ValueError("task_uuid must be a valid UUID.") from error

    if str(parsed) != value:
        raise ValueError("task_uuid must use canonical lower-case UUID format.")

    return value
