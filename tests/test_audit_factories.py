"""Tests for deterministic LEA audit-event factories."""

from datetime import UTC, datetime

import pytest

from lea.actions import (
    ActionContractError,
    ActionExecutionIssue,
    ActionExecutionResult,
    ActionProposal,
    ActionStatus,
    ActionTransition,
    ConfirmationDecision,
    ConfirmationDecisionApplicationResult,
    ConfirmationEvaluation,
    ConfirmationEvaluationResult,
    ConfirmationIssue,
    ConfirmationPolicy,
    ConfirmationPolicyApplicationResult,
    ConfirmationRecord,
    ConfirmationRecordResult,
    ConfirmationRequirement,
    ExecutionError,
    ExecutionResult,
    RiskLevel,
    TransitionIssue,
    TransitionResult,
    ValidationIssue,
    ValidationResult,
)
from lea.audit import (
    AuditEventType,
    audit_action_execution,
    audit_confirmation_decision_application,
    audit_confirmation_evaluation,
    audit_confirmation_policy_application,
    audit_confirmation_record,
    audit_proposal_created,
    audit_transition_result,
    audit_validation_completed,
)

EVENT_ID = "11111111-1111-4111-8111-111111111111"
PROPOSAL_ID = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"

CREATED_AT = datetime(2026, 7, 20, 17, 0, tzinfo=UTC)
EVALUATED_AT = datetime(2026, 7, 20, 18, 0, tzinfo=UTC)
DECIDED_AT = datetime(2026, 7, 20, 18, 5, tzinfo=UTC)
TRANSITIONED_AT = datetime(2026, 7, 20, 18, 10, tzinfo=UTC)
STARTED_AT = datetime(2026, 7, 20, 18, 15, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 7, 20, 18, 16, tzinfo=UTC)
EXPLICIT_AT = datetime(2026, 7, 20, 18, 20, tzinfo=UTC)


def create_proposal(
    status: ActionStatus = ActionStatus.PROPOSED,
) -> ActionProposal:
    """Create a deterministic proposal for audit-factory tests."""
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={"description": "Call John"},
        source="user",
        status=status,
        risk_level=RiskLevel.MEDIUM,
        confirmation_policy=ConfirmationPolicy.WHEN_REQUIRED,
        created_at=CREATED_AT,
        reason="The user requested a follow-up task.",
    )


def create_transition(
    from_status: ActionStatus,
    to_status: ActionStatus,
    *,
    transitioned_at: datetime = TRANSITIONED_AT,
) -> ActionTransition:
    """Create a deterministic action transition."""
    return ActionTransition(
        proposal_id=PROPOSAL_ID,
        from_status=from_status,
        to_status=to_status,
        transitioned_at=transitioned_at,
        reason="Deterministic test transition.",
    )


def create_confirmation_evaluation() -> ConfirmationEvaluation:
    """Create a deterministic confirmation evaluation."""
    return ConfirmationEvaluation(
        proposal_id=PROPOSAL_ID,
        risk_level=RiskLevel.MEDIUM,
        confirmation_policy=ConfirmationPolicy.WHEN_REQUIRED,
        requirement=ConfirmationRequirement.REQUIRED,
        evaluated_at=EVALUATED_AT,
        reason_code="medium_risk_confirmation_required",
        explanation="Confirmation is required.",
    )


def create_confirmation_record() -> ConfirmationRecord:
    """Create a deterministic human confirmation record."""
    return ConfirmationRecord(
        proposal_id=PROPOSAL_ID,
        decision=ConfirmationDecision.APPROVED,
        actor="user:marius",
        decided_at=DECIDED_AT,
        reason="Approved by the user.",
    )


def create_confirmation_issue() -> ConfirmationIssue:
    """Create a deterministic confirmation issue."""
    return ConfirmationIssue(
        code="invalid_proposal_status",
        message="The proposal status is not permitted.",
        proposal_id=PROPOSAL_ID,
        field="status",
    )


def test_proposal_created_factory() -> None:
    """Proposal events should use proposal identity and creation time."""
    proposal = create_proposal()

    event = audit_proposal_created(
        proposal,
        event_id=EVENT_ID,
    )

    assert event.event_id == EVENT_ID
    assert event.proposal_id == PROPOSAL_ID
    assert event.event_type is AuditEventType.PROPOSAL_CREATED
    assert event.occurred_at == CREATED_AT
    assert event.payload == proposal.to_dict()


def test_validation_completed_factory() -> None:
    """Validation events should use the explicit proposal and timestamp."""
    result = ValidationResult(
        valid=True,
        issues=(),
    )

    event = audit_validation_completed(
        PROPOSAL_ID,
        result,
        occurred_at=EXPLICIT_AT,
        event_id=EVENT_ID,
    )

    assert event.event_type is AuditEventType.VALIDATION_COMPLETED
    assert event.occurred_at == EXPLICIT_AT
    assert event.to_dict()["payload"] == result.to_dict()


def test_invalid_validation_result_factory_payload() -> None:
    """Invalid validation results should also be recorded."""
    result = ValidationResult(
        valid=False,
        issues=(
            ValidationIssue(
                code="missing_field",
                message="Required field is missing.",
                field="action",
            ),
        ),
    )

    event = audit_validation_completed(
        PROPOSAL_ID,
        result,
        occurred_at=EXPLICIT_AT,
        event_id=EVENT_ID,
    )

    assert event.event_type is AuditEventType.VALIDATION_COMPLETED
    assert event.to_dict()["payload"] == result.to_dict()


def test_successful_transition_factory() -> None:
    """Successful transitions should use their canonical timestamp."""
    transition = create_transition(
        ActionStatus.PROPOSED,
        ActionStatus.VALIDATED,
    )
    result = TransitionResult(
        success=True,
        proposal=create_proposal(ActionStatus.VALIDATED),
        transition=transition,
        issues=(),
    )

    event = audit_transition_result(
        result,
        event_id=EVENT_ID,
    )

    assert event.event_type is AuditEventType.TRANSITION_COMPLETED
    assert event.occurred_at == TRANSITIONED_AT
    assert event.to_dict()["payload"] == result.to_dict()


def test_rejected_transition_factory() -> None:
    """Rejected transitions should use an explicit timestamp."""
    result = TransitionResult(
        success=False,
        proposal=create_proposal(),
        transition=None,
        issues=(
            TransitionIssue(
                code="invalid_transition",
                message="The transition is not permitted.",
                from_status=ActionStatus.PROPOSED,
                to_status=ActionStatus.SUCCEEDED,
            ),
        ),
    )

    event = audit_transition_result(
        result,
        occurred_at=EXPLICIT_AT,
        event_id=EVENT_ID,
    )

    assert event.event_type is AuditEventType.TRANSITION_REJECTED
    assert event.occurred_at == EXPLICIT_AT
    assert event.to_dict()["payload"] == result.to_dict()


def test_rejected_transition_requires_explicit_timestamp() -> None:
    """A rejected transition has no canonical timestamp of its own."""
    result = TransitionResult(
        success=False,
        proposal=create_proposal(),
        transition=None,
        issues=(
            TransitionIssue(
                code="invalid_transition",
                message="The transition is not permitted.",
                from_status=ActionStatus.PROPOSED,
                to_status=ActionStatus.SUCCEEDED,
            ),
        ),
    )

    with pytest.raises(
        ActionContractError,
        match="requires an explicit occurred_at",
    ):
        audit_transition_result(result)


def test_successful_confirmation_evaluation_factory() -> None:
    """Successful evaluation events should use evaluated_at."""
    evaluation = create_confirmation_evaluation()
    result = ConfirmationEvaluationResult(
        success=True,
        evaluation=evaluation,
        issues=(),
    )

    event = audit_confirmation_evaluation(
        result,
        event_id=EVENT_ID,
    )

    assert event.event_type is AuditEventType.CONFIRMATION_EVALUATED
    assert event.occurred_at == EVALUATED_AT
    assert event.to_dict()["payload"] == result.to_dict()


def test_failed_confirmation_evaluation_factory() -> None:
    """Failed evaluations should use their issue proposal and explicit time."""
    result = ConfirmationEvaluationResult(
        success=False,
        evaluation=None,
        issues=(create_confirmation_issue(),),
    )

    event = audit_confirmation_evaluation(
        result,
        occurred_at=EXPLICIT_AT,
        event_id=EVENT_ID,
    )

    assert event.proposal_id == PROPOSAL_ID
    assert event.event_type is AuditEventType.CONFIRMATION_EVALUATED
    assert event.occurred_at == EXPLICIT_AT


def test_successful_confirmation_record_factory() -> None:
    """Recorded confirmation events should use decided_at."""
    record = create_confirmation_record()
    result = ConfirmationRecordResult(
        success=True,
        record=record,
        issues=(),
    )

    event = audit_confirmation_record(
        result,
        event_id=EVENT_ID,
    )

    assert event.event_type is AuditEventType.CONFIRMATION_RECORDED
    assert event.occurred_at == DECIDED_AT
    assert event.to_dict()["payload"] == result.to_dict()


def test_failed_confirmation_record_requires_explicit_timestamp() -> None:
    """Failed confirmation recording has no canonical timestamp."""
    result = ConfirmationRecordResult(
        success=False,
        record=None,
        issues=(create_confirmation_issue(),),
    )

    with pytest.raises(
        ActionContractError,
        match="requires an explicit occurred_at",
    ):
        audit_confirmation_record(result)


def test_successful_confirmation_policy_application_factory() -> None:
    """Policy application should use its resulting transition time."""
    evaluation = create_confirmation_evaluation()
    transition = create_transition(
        ActionStatus.VALIDATED,
        ActionStatus.AWAITING_CONFIRMATION,
    )
    result = ConfirmationPolicyApplicationResult(
        success=True,
        proposal=create_proposal(ActionStatus.AWAITING_CONFIRMATION),
        evaluation=evaluation,
        transition=transition,
        issues=(),
    )

    event = audit_confirmation_policy_application(
        result,
        event_id=EVENT_ID,
    )

    assert event.event_type is AuditEventType.CONFIRMATION_POLICY_APPLIED
    assert event.occurred_at == TRANSITIONED_AT
    assert event.to_dict()["payload"] == result.to_dict()


def test_failed_policy_application_uses_evaluation_timestamp() -> None:
    """A failed application may retain a canonical evaluation timestamp."""
    evaluation = create_confirmation_evaluation()
    result = ConfirmationPolicyApplicationResult(
        success=False,
        proposal=create_proposal(ActionStatus.VALIDATED),
        evaluation=evaluation,
        transition=None,
        issues=(create_confirmation_issue(),),
    )

    event = audit_confirmation_policy_application(
        result,
        event_id=EVENT_ID,
    )

    assert event.occurred_at == EVALUATED_AT


def test_failed_policy_application_requires_time_without_evaluation() -> None:
    """A failed application without records needs an explicit timestamp."""
    result = ConfirmationPolicyApplicationResult(
        success=False,
        proposal=create_proposal(ActionStatus.PROPOSED),
        evaluation=None,
        transition=None,
        issues=(create_confirmation_issue(),),
    )

    with pytest.raises(
        ActionContractError,
        match="requires an explicit occurred_at",
    ):
        audit_confirmation_policy_application(result)


def test_successful_confirmation_decision_application_factory() -> None:
    """Decision application should use its resulting transition time."""
    record = create_confirmation_record()
    transition = create_transition(
        ActionStatus.AWAITING_CONFIRMATION,
        ActionStatus.APPROVED,
    )
    result = ConfirmationDecisionApplicationResult(
        success=True,
        proposal=create_proposal(ActionStatus.APPROVED),
        record=record,
        transition=transition,
        issues=(),
    )

    event = audit_confirmation_decision_application(
        result,
        event_id=EVENT_ID,
    )

    assert event.event_type is AuditEventType.CONFIRMATION_DECISION_APPLIED
    assert event.occurred_at == TRANSITIONED_AT
    assert event.to_dict()["payload"] == result.to_dict()


def test_failed_decision_application_requires_explicit_timestamp() -> None:
    """Failed decision application contains no canonical timestamp."""
    result = ConfirmationDecisionApplicationResult(
        success=False,
        proposal=create_proposal(ActionStatus.PROPOSED),
        record=None,
        transition=None,
        issues=(create_confirmation_issue(),),
    )

    with pytest.raises(
        ActionContractError,
        match="requires an explicit occurred_at",
    ):
        audit_confirmation_decision_application(result)


def test_successful_execution_factory() -> None:
    """Completed execution should use ExecutionResult.completed_at."""
    execution = ExecutionResult(
        proposal_id=PROPOSAL_ID,
        success=True,
        status=ActionStatus.SUCCEEDED,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
        output={"task_id": "task-001"},
        error=None,
    )
    result = ActionExecutionResult(
        success=True,
        proposal=create_proposal(ActionStatus.SUCCEEDED),
        execution=execution,
        start_transition=create_transition(
            ActionStatus.APPROVED,
            ActionStatus.EXECUTING,
            transitioned_at=STARTED_AT,
        ),
        completion_transition=create_transition(
            ActionStatus.EXECUTING,
            ActionStatus.SUCCEEDED,
            transitioned_at=COMPLETED_AT,
        ),
        issues=(),
    )

    event = audit_action_execution(
        result,
        event_id=EVENT_ID,
    )

    assert event.event_type is AuditEventType.EXECUTION_COMPLETED
    assert event.occurred_at == COMPLETED_AT
    assert event.to_dict()["payload"] == result.to_dict()


def test_handled_execution_failure_factory() -> None:
    """Handled handler failures are completed execution events."""
    execution = ExecutionResult(
        proposal_id=PROPOSAL_ID,
        success=False,
        status=ActionStatus.FAILED,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
        output=None,
        error=ExecutionError(
            code="handler_exception",
            message="The action handler failed.",
            details={"exception_type": "RuntimeError"},
        ),
    )
    result = ActionExecutionResult(
        success=False,
        proposal=create_proposal(ActionStatus.FAILED),
        execution=execution,
        start_transition=create_transition(
            ActionStatus.APPROVED,
            ActionStatus.EXECUTING,
            transitioned_at=STARTED_AT,
        ),
        completion_transition=create_transition(
            ActionStatus.EXECUTING,
            ActionStatus.FAILED,
            transitioned_at=COMPLETED_AT,
        ),
        issues=(),
    )

    event = audit_action_execution(
        result,
        event_id=EVENT_ID,
    )

    assert event.event_type is AuditEventType.EXECUTION_COMPLETED
    assert event.occurred_at == COMPLETED_AT


def test_execution_boundary_rejection_factory() -> None:
    """Pre-handler rejection should use an explicit timestamp."""
    result = ActionExecutionResult(
        success=False,
        proposal=create_proposal(ActionStatus.PROPOSED),
        execution=None,
        start_transition=None,
        completion_transition=None,
        issues=(
            ActionExecutionIssue(
                code="invalid_proposal_status",
                message="Only approved proposals may execute.",
                proposal_id=PROPOSAL_ID,
                field="status",
            ),
        ),
    )

    event = audit_action_execution(
        result,
        occurred_at=EXPLICIT_AT,
        event_id=EVENT_ID,
    )

    assert event.event_type is AuditEventType.EXECUTION_BOUNDARY_REJECTED
    assert event.occurred_at == EXPLICIT_AT
    assert event.to_dict()["payload"] == result.to_dict()


def test_execution_boundary_rejection_requires_explicit_timestamp() -> None:
    """Pre-handler rejection contains no execution timestamp."""
    result = ActionExecutionResult(
        success=False,
        proposal=create_proposal(ActionStatus.PROPOSED),
        execution=None,
        start_transition=None,
        completion_transition=None,
        issues=(
            ActionExecutionIssue(
                code="invalid_proposal_status",
                message="Only approved proposals may execute.",
                proposal_id=PROPOSAL_ID,
                field="status",
            ),
        ),
    )

    with pytest.raises(
        ActionContractError,
        match="requires an explicit occurred_at",
    ):
        audit_action_execution(result)


def test_factory_generated_identifier_is_canonical() -> None:
    """Production factory calls should generate a valid UUID."""
    event = audit_proposal_created(create_proposal())

    assert len(event.event_id) == 36
    assert event.event_id == event.event_id.lower()
