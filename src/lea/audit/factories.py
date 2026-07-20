"""Factories that convert workflow records into audit events."""

from collections.abc import Mapping
from datetime import datetime

from lea.actions.confirmation import (
    ConfirmationDecisionApplicationResult,
    ConfirmationEvaluationResult,
    ConfirmationPolicyApplicationResult,
    ConfirmationRecordResult,
)
from lea.actions.errors import ActionContractError
from lea.actions.execution import ActionExecutionResult
from lea.actions.models import ActionProposal
from lea.actions.transitions import TransitionResult
from lea.actions.validation import ValidationResult
from lea.audit.events import (
    AuditEvent,
    AuditEventType,
)


def audit_proposal_created(
    proposal: ActionProposal,
    *,
    event_id: str | None = None,
) -> AuditEvent:
    """Create an audit event for a newly created proposal."""
    return _create_event(
        proposal_id=proposal.proposal_id,
        event_type=AuditEventType.PROPOSAL_CREATED,
        occurred_at=proposal.created_at,
        payload=proposal.to_dict(),
        event_id=event_id,
    )


def audit_validation_completed(
    proposal_id: str,
    result: ValidationResult,
    *,
    occurred_at: datetime,
    event_id: str | None = None,
) -> AuditEvent:
    """Create an audit event for proposal-data validation."""
    return _create_event(
        proposal_id=proposal_id,
        event_type=AuditEventType.VALIDATION_COMPLETED,
        occurred_at=occurred_at,
        payload=result.to_dict(),
        event_id=event_id,
    )


def audit_transition_result(
    result: TransitionResult,
    *,
    occurred_at: datetime | None = None,
    event_id: str | None = None,
) -> AuditEvent:
    """Create an audit event for a transition outcome."""
    if result.success:
        if result.transition is None:
            raise ActionContractError(
                "A successful transition result must contain a transition record."
            )

        event_type = AuditEventType.TRANSITION_COMPLETED
        event_timestamp = result.transition.transitioned_at
    else:
        event_type = AuditEventType.TRANSITION_REJECTED
        event_timestamp = _require_explicit_timestamp(
            occurred_at,
            event_name="transition_rejected",
        )

    return _create_event(
        proposal_id=result.proposal.proposal_id,
        event_type=event_type,
        occurred_at=event_timestamp,
        payload=result.to_dict(),
        event_id=event_id,
    )


def audit_confirmation_evaluation(
    result: ConfirmationEvaluationResult,
    *,
    occurred_at: datetime | None = None,
    event_id: str | None = None,
) -> AuditEvent:
    """Create an audit event for confirmation evaluation."""
    if result.success:
        if result.evaluation is None:
            raise ActionContractError(
                "A successful confirmation evaluation result must "
                "contain an evaluation record."
            )

        proposal_id = result.evaluation.proposal_id
        event_timestamp = result.evaluation.evaluated_at
    else:
        proposal_id = _proposal_id_from_issues(result.issues)
        event_timestamp = _require_explicit_timestamp(
            occurred_at,
            event_name="confirmation_evaluated",
        )

    return _create_event(
        proposal_id=proposal_id,
        event_type=AuditEventType.CONFIRMATION_EVALUATED,
        occurred_at=event_timestamp,
        payload=result.to_dict(),
        event_id=event_id,
    )


def audit_confirmation_record(
    result: ConfirmationRecordResult,
    *,
    occurred_at: datetime | None = None,
    event_id: str | None = None,
) -> AuditEvent:
    """Create an audit event for a human confirmation decision."""
    if result.success:
        if result.record is None:
            raise ActionContractError(
                "A successful confirmation record result must "
                "contain a confirmation record."
            )

        proposal_id = result.record.proposal_id
        event_timestamp = result.record.decided_at
    else:
        proposal_id = _proposal_id_from_issues(result.issues)
        event_timestamp = _require_explicit_timestamp(
            occurred_at,
            event_name="confirmation_recorded",
        )

    return _create_event(
        proposal_id=proposal_id,
        event_type=AuditEventType.CONFIRMATION_RECORDED,
        occurred_at=event_timestamp,
        payload=result.to_dict(),
        event_id=event_id,
    )


def audit_confirmation_policy_application(
    result: ConfirmationPolicyApplicationResult,
    *,
    occurred_at: datetime | None = None,
    event_id: str | None = None,
) -> AuditEvent:
    """Create an audit event for confirmation-policy application."""
    if result.transition is not None:
        event_timestamp = result.transition.transitioned_at
    elif result.evaluation is not None:
        event_timestamp = result.evaluation.evaluated_at
    else:
        event_timestamp = _require_explicit_timestamp(
            occurred_at,
            event_name="confirmation_policy_applied",
        )

    return _create_event(
        proposal_id=result.proposal.proposal_id,
        event_type=AuditEventType.CONFIRMATION_POLICY_APPLIED,
        occurred_at=event_timestamp,
        payload=result.to_dict(),
        event_id=event_id,
    )


def audit_confirmation_decision_application(
    result: ConfirmationDecisionApplicationResult,
    *,
    occurred_at: datetime | None = None,
    event_id: str | None = None,
) -> AuditEvent:
    """Create an audit event for confirmation-decision application."""
    if result.transition is not None:
        event_timestamp = result.transition.transitioned_at
    elif result.record is not None:
        event_timestamp = result.record.decided_at
    else:
        event_timestamp = _require_explicit_timestamp(
            occurred_at,
            event_name="confirmation_decision_applied",
        )

    return _create_event(
        proposal_id=result.proposal.proposal_id,
        event_type=AuditEventType.CONFIRMATION_DECISION_APPLIED,
        occurred_at=event_timestamp,
        payload=result.to_dict(),
        event_id=event_id,
    )


def audit_action_execution(
    result: ActionExecutionResult,
    *,
    occurred_at: datetime | None = None,
    event_id: str | None = None,
) -> AuditEvent:
    """Create an audit event for an execution-boundary outcome."""
    if result.execution is not None:
        event_type = AuditEventType.EXECUTION_COMPLETED
        event_timestamp = result.execution.completed_at
    else:
        event_type = AuditEventType.EXECUTION_BOUNDARY_REJECTED
        event_timestamp = _require_explicit_timestamp(
            occurred_at,
            event_name="execution_boundary_rejected",
        )

    return _create_event(
        proposal_id=result.proposal.proposal_id,
        event_type=event_type,
        occurred_at=event_timestamp,
        payload=result.to_dict(),
        event_id=event_id,
    )


def _create_event(
    *,
    proposal_id: str,
    event_type: AuditEventType,
    occurred_at: datetime,
    payload: Mapping[str, object],
    event_id: str | None,
) -> AuditEvent:
    """Create an event while preserving optional identifier injection."""
    if event_id is None:
        return AuditEvent(
            proposal_id=proposal_id,
            event_type=event_type,
            occurred_at=occurred_at,
            payload=payload,
        )

    return AuditEvent(
        event_id=event_id,
        proposal_id=proposal_id,
        event_type=event_type,
        occurred_at=occurred_at,
        payload=payload,
    )


def _require_explicit_timestamp(
    occurred_at: datetime | None,
    *,
    event_name: str,
) -> datetime:
    """Return an explicitly supplied timestamp or fail closed."""
    if occurred_at is None:
        raise ActionContractError(
            f"{event_name} requires an explicit occurred_at timestamp "
            "because the workflow result has no canonical timestamp."
        )

    return occurred_at


def _proposal_id_from_issues(
    issues: tuple[object, ...],
) -> str:
    """Obtain the common proposal identifier from an issue tuple."""
    if not issues:
        raise ActionContractError(
            "A failed workflow result must contain at least one issue."
        )

    first_issue = issues[0]
    proposal_id = getattr(first_issue, "proposal_id", None)

    if not isinstance(proposal_id, str):
        raise ActionContractError(
            "The workflow issue must contain a proposal_id string."
        )

    for issue in issues[1:]:
        if getattr(issue, "proposal_id", None) != proposal_id:
            raise ActionContractError(
                "All workflow issues must refer to the same proposal_id."
            )

    return proposal_id
