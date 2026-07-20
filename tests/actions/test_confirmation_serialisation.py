"""Tests for deterministic confirmation serialisation."""

from datetime import UTC, datetime

from lea.actions import (
    ActionProposal,
    ActionStatus,
    ConfirmationDecision,
    ConfirmationIssue,
    ConfirmationPolicy,
    RiskLevel,
    apply_confirmation_decision,
    apply_confirmation_policy,
    evaluate_confirmation,
    record_confirmation,
)

PROPOSAL_ID = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"
CREATED_AT = datetime(2026, 7, 20, 17, 0, tzinfo=UTC)
DECIDED_AT = datetime(2026, 7, 20, 18, 0, tzinfo=UTC)


def create_proposal(status: ActionStatus) -> ActionProposal:
    """Create a deterministic proposal for serialisation tests."""
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={"description": "Call John"},
        source="user",
        status=status,
        risk_level=RiskLevel.HIGH,
        confirmation_policy=ConfirmationPolicy.ALWAYS,
        created_at=CREATED_AT,
    )


def test_confirmation_evaluation_serialisation() -> None:
    """Evaluation records should use string enums and ISO timestamps."""
    proposal = create_proposal(ActionStatus.VALIDATED)

    result = evaluate_confirmation(
        proposal,
        evaluated_at=DECIDED_AT,
    )

    assert result.evaluation is not None
    assert result.evaluation.to_dict() == {
        "proposal_id": PROPOSAL_ID,
        "risk_level": "high",
        "confirmation_policy": "always",
        "requirement": "required",
        "evaluated_at": "2026-07-20T18:00:00+00:00",
        "reason_code": "high_risk_override",
        "explanation": ("High-risk proposals always require human confirmation."),
    }


def test_confirmation_issue_serialisation() -> None:
    """Confirmation issues should serialise deterministically."""
    issue = ConfirmationIssue(
        code="invalid_actor",
        message="The actor is invalid.",
        proposal_id=PROPOSAL_ID,
        field="actor",
    )

    assert issue.to_dict() == {
        "code": "invalid_actor",
        "message": "The actor is invalid.",
        "proposal_id": PROPOSAL_ID,
        "field": "actor",
    }


def test_evaluation_result_serialisation() -> None:
    """Evaluation results should serialise nested records."""
    proposal = create_proposal(ActionStatus.VALIDATED)

    result = evaluate_confirmation(
        proposal,
        evaluated_at=DECIDED_AT,
    )
    data = result.to_dict()

    assert data["success"] is True
    assert data["issues"] == []

    evaluation = data["evaluation"]
    assert isinstance(evaluation, dict)
    assert evaluation["requirement"] == "required"


def test_confirmation_record_serialisation() -> None:
    """Human confirmation records should serialise deterministically."""
    proposal = create_proposal(ActionStatus.AWAITING_CONFIRMATION)

    result = record_confirmation(
        proposal,
        ConfirmationDecision.APPROVED,
        "user:marius",
        reason="Reviewed by the user.",
        decided_at=DECIDED_AT,
    )

    assert result.record is not None
    assert result.record.to_dict() == {
        "proposal_id": PROPOSAL_ID,
        "decision": "approved",
        "actor": "user:marius",
        "decided_at": "2026-07-20T18:00:00+00:00",
        "reason": "Reviewed by the user.",
    }


def test_record_result_serialisation() -> None:
    """Record results should serialise nested records."""
    proposal = create_proposal(ActionStatus.AWAITING_CONFIRMATION)

    result = record_confirmation(
        proposal,
        ConfirmationDecision.REJECTED,
        "user:marius",
        decided_at=DECIDED_AT,
    )
    data = result.to_dict()

    assert data["success"] is True
    assert data["issues"] == []

    record = data["record"]
    assert isinstance(record, dict)
    assert record["decision"] == "rejected"


def test_policy_application_result_serialisation() -> None:
    """Policy applications should include proposal and transition data."""
    proposal = create_proposal(ActionStatus.VALIDATED)

    result = apply_confirmation_policy(
        proposal,
        applied_at=DECIDED_AT,
    )
    data = result.to_dict()

    assert data["success"] is True
    assert data["issues"] == []

    serialised_proposal = data["proposal"]
    assert isinstance(serialised_proposal, dict)
    assert serialised_proposal["status"] == "awaiting_confirmation"

    transition = data["transition"]
    assert isinstance(transition, dict)
    assert transition["from_status"] == "validated"
    assert transition["to_status"] == "awaiting_confirmation"

    evaluation = data["evaluation"]
    assert isinstance(evaluation, dict)
    assert evaluation["requirement"] == "required"


def test_decision_application_result_serialisation() -> None:
    """Decision applications should include record and transition data."""
    proposal = create_proposal(ActionStatus.AWAITING_CONFIRMATION)

    result = apply_confirmation_decision(
        proposal,
        ConfirmationDecision.CANCELLED,
        "user:marius",
        reason="The request is no longer needed.",
        decided_at=DECIDED_AT,
    )
    data = result.to_dict()

    assert data["success"] is True
    assert data["issues"] == []

    serialised_proposal = data["proposal"]
    assert isinstance(serialised_proposal, dict)
    assert serialised_proposal["status"] == "cancelled"

    record = data["record"]
    assert isinstance(record, dict)
    assert record["decision"] == "cancelled"

    transition = data["transition"]
    assert isinstance(transition, dict)
    assert transition["to_status"] == "cancelled"


def test_failed_result_serialises_issues_as_list() -> None:
    """Failed confirmation results should expose plain issue lists."""
    proposal = create_proposal(ActionStatus.VALIDATED)

    result = record_confirmation(
        proposal,
        ConfirmationDecision.APPROVED,
        "",
        decided_at=DECIDED_AT,
    )
    data = result.to_dict()

    assert data["success"] is False
    assert data["record"] is None

    issues = data["issues"]
    assert isinstance(issues, list)
    assert {issue["code"] for issue in issues} == {
        "invalid_proposal_status",
        "invalid_actor",
    }
