"""Tests for deterministic confirmation-policy evaluation."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from lea.actions import (
    CONFIRMATION_MATRIX,
    DECISION_TARGET_STATUSES,
    ActionContractError,
    ActionProposal,
    ActionStatus,
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
    RiskLevel,
    apply_confirmation_decision,
    apply_confirmation_policy,
    evaluate_confirmation,
    record_confirmation,
    transition_proposal,
)

PROPOSAL_ID = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"
EVALUATED_AT = datetime(2026, 7, 20, 18, 0, tzinfo=UTC)


def create_validated_proposal(
    risk_level: RiskLevel,
    confirmation_policy: ConfirmationPolicy,
) -> ActionProposal:
    """Create a deterministic validated proposal."""
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={"description": "Call John"},
        source="user",
        status=ActionStatus.VALIDATED,
        risk_level=risk_level,
        confirmation_policy=confirmation_policy,
        created_at=datetime(2026, 7, 20, 17, 0, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("risk_level", "confirmation_policy", "requirement"),
    [
        (
            RiskLevel.LOW,
            ConfirmationPolicy.NEVER,
            ConfirmationRequirement.NOT_REQUIRED,
        ),
        (
            RiskLevel.LOW,
            ConfirmationPolicy.WHEN_REQUIRED,
            ConfirmationRequirement.NOT_REQUIRED,
        ),
        (
            RiskLevel.LOW,
            ConfirmationPolicy.ALWAYS,
            ConfirmationRequirement.REQUIRED,
        ),
        (
            RiskLevel.MEDIUM,
            ConfirmationPolicy.NEVER,
            ConfirmationRequirement.NOT_REQUIRED,
        ),
        (
            RiskLevel.MEDIUM,
            ConfirmationPolicy.WHEN_REQUIRED,
            ConfirmationRequirement.REQUIRED,
        ),
        (
            RiskLevel.MEDIUM,
            ConfirmationPolicy.ALWAYS,
            ConfirmationRequirement.REQUIRED,
        ),
        (
            RiskLevel.HIGH,
            ConfirmationPolicy.NEVER,
            ConfirmationRequirement.REQUIRED,
        ),
        (
            RiskLevel.HIGH,
            ConfirmationPolicy.WHEN_REQUIRED,
            ConfirmationRequirement.REQUIRED,
        ),
        (
            RiskLevel.HIGH,
            ConfirmationPolicy.ALWAYS,
            ConfirmationRequirement.REQUIRED,
        ),
        (
            RiskLevel.CRITICAL,
            ConfirmationPolicy.NEVER,
            ConfirmationRequirement.REQUIRED,
        ),
        (
            RiskLevel.CRITICAL,
            ConfirmationPolicy.WHEN_REQUIRED,
            ConfirmationRequirement.REQUIRED,
        ),
        (
            RiskLevel.CRITICAL,
            ConfirmationPolicy.ALWAYS,
            ConfirmationRequirement.REQUIRED,
        ),
    ],
)
def test_confirmation_matrix(
    risk_level: RiskLevel,
    confirmation_policy: ConfirmationPolicy,
    requirement: ConfirmationRequirement,
) -> None:
    """Every canonical matrix cell should produce its declared result."""
    proposal = create_validated_proposal(
        risk_level,
        confirmation_policy,
    )

    result = evaluate_confirmation(
        proposal,
        evaluated_at=EVALUATED_AT,
    )

    assert result.success is True
    assert result.evaluation is not None
    assert result.evaluation.requirement is requirement


def test_confirmation_matrix_covers_every_combination() -> None:
    """The policy matrix should cover all risk and policy values."""
    assert set(CONFIRMATION_MATRIX) == set(RiskLevel)

    for risk_level in RiskLevel:
        assert set(CONFIRMATION_MATRIX[risk_level]) == set(ConfirmationPolicy)


def test_high_risk_never_uses_override_reason() -> None:
    """High-risk proposals should override the never preference."""
    proposal = create_validated_proposal(
        RiskLevel.HIGH,
        ConfirmationPolicy.NEVER,
    )

    result = evaluate_confirmation(
        proposal,
        evaluated_at=EVALUATED_AT,
    )

    assert result.evaluation is not None
    assert result.evaluation.reason_code == "high_risk_override"


def test_critical_risk_never_uses_override_reason() -> None:
    """Critical-risk proposals should override the never preference."""
    proposal = create_validated_proposal(
        RiskLevel.CRITICAL,
        ConfirmationPolicy.NEVER,
    )

    result = evaluate_confirmation(
        proposal,
        evaluated_at=EVALUATED_AT,
    )

    assert result.evaluation is not None
    assert result.evaluation.reason_code == "critical_risk_override"


def test_invalid_proposal_state_returns_issue() -> None:
    """Only validated proposals should be evaluated."""
    proposal = ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={},
        source="user",
        status=ActionStatus.PROPOSED,
        created_at=datetime(2026, 7, 20, 17, 0, tzinfo=UTC),
    )

    result = evaluate_confirmation(
        proposal,
        evaluated_at=EVALUATED_AT,
    )

    assert result.success is False
    assert result.evaluation is None
    assert result.issues[0].code == "invalid_proposal_status"


def test_evaluation_rejects_naive_timestamp() -> None:
    """Evaluation timestamps should be timezone-aware."""
    proposal = create_validated_proposal(
        RiskLevel.LOW,
        ConfirmationPolicy.NEVER,
    )

    with pytest.raises(
        ActionContractError,
        match="timezone-aware",
    ):
        evaluate_confirmation(
            proposal,
            evaluated_at=datetime(2026, 7, 20, 18, 0),
        )


def test_successful_result_requires_evaluation() -> None:
    """Successful results should contain an evaluation record."""
    with pytest.raises(
        ActionContractError,
        match="must contain an evaluation record",
    ):
        ConfirmationEvaluationResult(
            success=True,
            evaluation=None,
            issues=(),
        )


def test_successful_result_rejects_issues() -> None:
    """Successful results should not contain issues."""
    evaluation = ConfirmationEvaluation(
        proposal_id=PROPOSAL_ID,
        risk_level=RiskLevel.LOW,
        confirmation_policy=ConfirmationPolicy.NEVER,
        requirement=ConfirmationRequirement.NOT_REQUIRED,
        evaluated_at=EVALUATED_AT,
        reason_code="low_risk_not_required",
        explanation="Confirmation is not required.",
    )
    issue = ConfirmationIssue(
        code="example",
        message="Example issue.",
        proposal_id=PROPOSAL_ID,
    )

    with pytest.raises(
        ActionContractError,
        match="must not contain issues",
    ):
        ConfirmationEvaluationResult(
            success=True,
            evaluation=evaluation,
            issues=(issue,),
        )


def test_failed_result_requires_issues() -> None:
    """Failed results should contain at least one issue."""
    with pytest.raises(
        ActionContractError,
        match="at least one issue",
    ):
        ConfirmationEvaluationResult(
            success=False,
            evaluation=None,
            issues=(),
        )


def test_failed_result_rejects_evaluation() -> None:
    """Failed results should not contain an evaluation record."""
    evaluation = ConfirmationEvaluation(
        proposal_id=PROPOSAL_ID,
        risk_level=RiskLevel.LOW,
        confirmation_policy=ConfirmationPolicy.NEVER,
        requirement=ConfirmationRequirement.NOT_REQUIRED,
        evaluated_at=EVALUATED_AT,
        reason_code="low_risk_not_required",
        explanation="Confirmation is not required.",
    )
    issue = ConfirmationIssue(
        code="example",
        message="Example issue.",
        proposal_id=PROPOSAL_ID,
    )

    with pytest.raises(
        ActionContractError,
        match="must not contain an evaluation record",
    ):
        ConfirmationEvaluationResult(
            success=False,
            evaluation=evaluation,
            issues=(issue,),
        )


def create_awaiting_confirmation_proposal() -> ActionProposal:
    """Create a deterministic proposal awaiting human confirmation."""
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={"description": "Call John"},
        source="user",
        status=ActionStatus.AWAITING_CONFIRMATION,
        risk_level=RiskLevel.HIGH,
        confirmation_policy=ConfirmationPolicy.ALWAYS,
        created_at=datetime(2026, 7, 20, 17, 0, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    "decision",
    [
        ConfirmationDecision.APPROVED,
        ConfirmationDecision.REJECTED,
        ConfirmationDecision.CANCELLED,
    ],
)
def test_record_confirmation_accepts_each_human_decision(
    decision: ConfirmationDecision,
) -> None:
    """Every declared human decision should produce a record."""
    proposal = create_awaiting_confirmation_proposal()

    result = record_confirmation(
        proposal,
        decision,
        "user:marius",
        reason="Decision reviewed by the user.",
        decided_at=EVALUATED_AT,
    )

    assert result.success is True
    assert result.record is not None
    assert result.record.proposal_id == PROPOSAL_ID
    assert result.record.decision is decision
    assert result.record.actor == "user:marius"
    assert result.record.reason == "Decision reviewed by the user."
    assert result.record.decided_at == EVALUATED_AT
    assert result.issues == ()


def test_confirmation_record_is_immutable() -> None:
    """Human confirmation records should not be mutable."""
    record = ConfirmationRecord(
        proposal_id=PROPOSAL_ID,
        decision=ConfirmationDecision.APPROVED,
        actor="user:marius",
        decided_at=EVALUATED_AT,
    )

    with pytest.raises(FrozenInstanceError):
        record.actor = "user:other"  # type: ignore[misc]


def test_record_confirmation_rejects_wrong_proposal_status() -> None:
    """Only proposals awaiting confirmation may receive a decision."""
    proposal = create_validated_proposal(
        RiskLevel.HIGH,
        ConfirmationPolicy.ALWAYS,
    )

    result = record_confirmation(
        proposal,
        ConfirmationDecision.APPROVED,
        "user:marius",
        decided_at=EVALUATED_AT,
    )

    assert result.success is False
    assert result.record is None
    assert result.issues[0].code == "invalid_proposal_status"
    assert result.issues[0].field == "status"


def test_record_confirmation_rejects_empty_actor() -> None:
    """The human actor identifier must not be empty."""
    proposal = create_awaiting_confirmation_proposal()

    result = record_confirmation(
        proposal,
        ConfirmationDecision.APPROVED,
        "   ",
        decided_at=EVALUATED_AT,
    )

    assert result.success is False
    assert result.record is None
    assert result.issues[0].code == "invalid_actor"
    assert result.issues[0].field == "actor"


def test_record_confirmation_rejects_naive_timestamp() -> None:
    """Human decision timestamps should be timezone-aware."""
    proposal = create_awaiting_confirmation_proposal()

    result = record_confirmation(
        proposal,
        ConfirmationDecision.APPROVED,
        "user:marius",
        decided_at=datetime(2026, 7, 20, 18, 0),
    )

    assert result.success is False
    assert result.record is None
    assert result.issues[0].code == "invalid_timestamp"
    assert result.issues[0].field == "decided_at"


def test_record_confirmation_rejects_blank_reason() -> None:
    """A supplied decision reason should contain meaningful text."""
    proposal = create_awaiting_confirmation_proposal()

    result = record_confirmation(
        proposal,
        ConfirmationDecision.REJECTED,
        "user:marius",
        reason="   ",
        decided_at=EVALUATED_AT,
    )

    assert result.success is False
    assert result.record is None
    assert result.issues[0].code == "invalid_reason"
    assert result.issues[0].field == "reason"


def test_record_confirmation_collects_multiple_issues() -> None:
    """Independent input problems should be reported together."""
    proposal = create_validated_proposal(
        RiskLevel.HIGH,
        ConfirmationPolicy.ALWAYS,
    )

    result = record_confirmation(
        proposal,
        ConfirmationDecision.APPROVED,
        "   ",
        reason="   ",
        decided_at=datetime(2026, 7, 20, 18, 0),
    )

    assert result.success is False
    assert result.record is None
    assert {issue.code for issue in result.issues} == {
        "invalid_proposal_status",
        "invalid_actor",
        "invalid_reason",
        "invalid_timestamp",
    }


def test_record_confirmation_preserves_original_proposal() -> None:
    """Recording a human decision should not mutate the proposal."""
    proposal = create_awaiting_confirmation_proposal()
    original_data = proposal.to_dict()

    record_confirmation(
        proposal,
        ConfirmationDecision.APPROVED,
        "user:marius",
        decided_at=EVALUATED_AT,
    )

    assert proposal.to_dict() == original_data
    assert proposal.status is ActionStatus.AWAITING_CONFIRMATION


def test_confirmation_record_rejects_naive_timestamp_directly() -> None:
    """Direct record construction should enforce timestamp invariants."""
    with pytest.raises(ActionContractError, match="timezone-aware"):
        ConfirmationRecord(
            proposal_id=PROPOSAL_ID,
            decision=ConfirmationDecision.APPROVED,
            actor="user:marius",
            decided_at=datetime(2026, 7, 20, 18, 0),
        )


def test_successful_record_result_requires_record() -> None:
    """Successful record results should contain a record."""
    with pytest.raises(
        ActionContractError,
        match="must contain a confirmation record",
    ):
        ConfirmationRecordResult(
            success=True,
            record=None,
            issues=(),
        )


def test_successful_record_result_rejects_issues() -> None:
    """Successful record results should not contain issues."""
    record = ConfirmationRecord(
        proposal_id=PROPOSAL_ID,
        decision=ConfirmationDecision.APPROVED,
        actor="user:marius",
        decided_at=EVALUATED_AT,
    )
    issue = ConfirmationIssue(
        code="example",
        message="Example issue.",
        proposal_id=PROPOSAL_ID,
    )

    with pytest.raises(
        ActionContractError,
        match="must not contain issues",
    ):
        ConfirmationRecordResult(
            success=True,
            record=record,
            issues=(issue,),
        )


def test_failed_record_result_requires_issues() -> None:
    """Failed record results should contain at least one issue."""
    with pytest.raises(
        ActionContractError,
        match="at least one issue",
    ):
        ConfirmationRecordResult(
            success=False,
            record=None,
            issues=(),
        )


def test_failed_record_result_rejects_record() -> None:
    """Failed record results should not contain a record."""
    record = ConfirmationRecord(
        proposal_id=PROPOSAL_ID,
        decision=ConfirmationDecision.REJECTED,
        actor="user:marius",
        decided_at=EVALUATED_AT,
    )
    issue = ConfirmationIssue(
        code="example",
        message="Example issue.",
        proposal_id=PROPOSAL_ID,
    )

    with pytest.raises(
        ActionContractError,
        match="must not contain a confirmation record",
    ):
        ConfirmationRecordResult(
            success=False,
            record=record,
            issues=(issue,),
        )


def test_apply_policy_approves_when_confirmation_is_not_required() -> None:
    """A proposal should be approved when confirmation is unnecessary."""
    proposal = create_validated_proposal(
        RiskLevel.LOW,
        ConfirmationPolicy.NEVER,
    )
    original_data = proposal.to_dict()

    result = apply_confirmation_policy(
        proposal,
        applied_at=EVALUATED_AT,
    )

    assert result.success is True
    assert result.proposal.status is ActionStatus.APPROVED
    assert result.evaluation is not None
    assert result.evaluation.requirement is ConfirmationRequirement.NOT_REQUIRED
    assert result.transition is not None
    assert result.transition.from_status is ActionStatus.VALIDATED
    assert result.transition.to_status is ActionStatus.APPROVED
    assert result.transition.transitioned_at == EVALUATED_AT
    assert result.issues == ()

    assert proposal.status is ActionStatus.VALIDATED
    assert proposal.to_dict() == original_data


def test_apply_policy_waits_when_confirmation_is_required() -> None:
    """A proposal should pause when human confirmation is required."""
    proposal = create_validated_proposal(
        RiskLevel.HIGH,
        ConfirmationPolicy.NEVER,
    )

    result = apply_confirmation_policy(
        proposal,
        applied_at=EVALUATED_AT,
    )

    assert result.success is True
    assert result.proposal.status is ActionStatus.AWAITING_CONFIRMATION
    assert result.evaluation is not None
    assert result.evaluation.requirement is ConfirmationRequirement.REQUIRED
    assert result.evaluation.reason_code == "high_risk_override"
    assert result.transition is not None
    assert result.transition.from_status is ActionStatus.VALIDATED
    assert result.transition.to_status is ActionStatus.AWAITING_CONFIRMATION
    assert result.transition.transitioned_at == EVALUATED_AT
    assert result.issues == ()


def test_apply_policy_rejects_invalid_proposal_status() -> None:
    """Policy application should fail outside the validated state."""
    proposal = ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={},
        source="user",
        status=ActionStatus.PROPOSED,
        created_at=datetime(2026, 7, 20, 17, 0, tzinfo=UTC),
    )

    result = apply_confirmation_policy(
        proposal,
        applied_at=EVALUATED_AT,
    )

    assert result.success is False
    assert result.proposal is proposal
    assert result.evaluation is None
    assert result.transition is None
    assert result.issues[0].code == "invalid_proposal_status"


def test_apply_policy_uses_same_timestamp_for_both_records() -> None:
    """Evaluation and transition should represent one workflow event."""
    proposal = create_validated_proposal(
        RiskLevel.MEDIUM,
        ConfirmationPolicy.WHEN_REQUIRED,
    )

    result = apply_confirmation_policy(
        proposal,
        applied_at=EVALUATED_AT,
    )

    assert result.evaluation is not None
    assert result.transition is not None
    assert result.evaluation.evaluated_at == EVALUATED_AT
    assert result.transition.transitioned_at == EVALUATED_AT


def test_successful_policy_application_requires_evaluation() -> None:
    """Successful policy application should contain an evaluation."""
    proposal = create_validated_proposal(
        RiskLevel.LOW,
        ConfirmationPolicy.NEVER,
    )

    transition_result = transition_proposal(
        proposal,
        ActionStatus.APPROVED,
        transitioned_at=EVALUATED_AT,
    )

    assert transition_result.transition is not None

    with pytest.raises(
        ActionContractError,
        match="must contain an evaluation record",
    ):
        ConfirmationPolicyApplicationResult(
            success=True,
            proposal=transition_result.proposal,
            evaluation=None,
            transition=transition_result.transition,
            issues=(),
        )


def test_successful_policy_application_requires_transition() -> None:
    """Successful policy application should contain a transition."""
    proposal = create_validated_proposal(
        RiskLevel.LOW,
        ConfirmationPolicy.NEVER,
    )
    evaluation_result = evaluate_confirmation(
        proposal,
        evaluated_at=EVALUATED_AT,
    )

    assert evaluation_result.evaluation is not None

    with pytest.raises(
        ActionContractError,
        match="must contain a transition record",
    ):
        ConfirmationPolicyApplicationResult(
            success=True,
            proposal=proposal,
            evaluation=evaluation_result.evaluation,
            transition=None,
            issues=(),
        )


def test_failed_policy_application_requires_issues() -> None:
    """Failed policy application should contain structured issues."""
    proposal = create_validated_proposal(
        RiskLevel.LOW,
        ConfirmationPolicy.NEVER,
    )

    with pytest.raises(
        ActionContractError,
        match="at least one issue",
    ):
        ConfirmationPolicyApplicationResult(
            success=False,
            proposal=proposal,
            evaluation=None,
            transition=None,
            issues=(),
        )


@pytest.mark.parametrize(
    ("decision", "expected_status"),
    [
        (
            ConfirmationDecision.APPROVED,
            ActionStatus.APPROVED,
        ),
        (
            ConfirmationDecision.REJECTED,
            ActionStatus.REJECTED,
        ),
        (
            ConfirmationDecision.CANCELLED,
            ActionStatus.CANCELLED,
        ),
    ],
)
def test_apply_confirmation_decision_transitions_proposal(
    decision: ConfirmationDecision,
    expected_status: ActionStatus,
) -> None:
    """Each human decision should produce its corresponding state."""
    proposal = create_awaiting_confirmation_proposal()
    original_data = proposal.to_dict()

    result = apply_confirmation_decision(
        proposal,
        decision,
        "user:marius",
        reason="Reviewed by the user.",
        decided_at=EVALUATED_AT,
    )

    assert result.success is True
    assert result.proposal.status is expected_status
    assert result.record is not None
    assert result.record.decision is decision
    assert result.record.actor == "user:marius"
    assert result.transition is not None
    assert result.transition.from_status is ActionStatus.AWAITING_CONFIRMATION
    assert result.transition.to_status is expected_status
    assert result.issues == ()

    assert proposal.status is ActionStatus.AWAITING_CONFIRMATION
    assert proposal.to_dict() == original_data


def test_decision_target_mapping_covers_every_decision() -> None:
    """Every declared human decision should map to a target state."""
    assert set(DECISION_TARGET_STATUSES) == set(ConfirmationDecision)


def test_decision_application_uses_one_timestamp() -> None:
    """The human record and transition should share one timestamp."""
    proposal = create_awaiting_confirmation_proposal()

    result = apply_confirmation_decision(
        proposal,
        ConfirmationDecision.APPROVED,
        "user:marius",
        decided_at=EVALUATED_AT,
    )

    assert result.record is not None
    assert result.transition is not None
    assert result.record.decided_at == EVALUATED_AT
    assert result.transition.transitioned_at == EVALUATED_AT


def test_decision_application_preserves_reason() -> None:
    """The human reason should be retained in both audit records."""
    proposal = create_awaiting_confirmation_proposal()

    result = apply_confirmation_decision(
        proposal,
        ConfirmationDecision.REJECTED,
        "user:marius",
        reason="The requested change is unsafe.",
        decided_at=EVALUATED_AT,
    )

    assert result.record is not None
    assert result.record.reason == "The requested change is unsafe."
    assert result.transition is not None
    assert result.transition.reason == "The requested change is unsafe."


def test_decision_application_rejects_wrong_proposal_state() -> None:
    """Human decisions should only apply while awaiting confirmation."""
    proposal = create_validated_proposal(
        RiskLevel.HIGH,
        ConfirmationPolicy.ALWAYS,
    )

    result = apply_confirmation_decision(
        proposal,
        ConfirmationDecision.APPROVED,
        "user:marius",
        decided_at=EVALUATED_AT,
    )

    assert result.success is False
    assert result.proposal is proposal
    assert result.record is None
    assert result.transition is None
    assert result.issues[0].code == "invalid_proposal_status"


def test_decision_application_propagates_actor_issue() -> None:
    """Invalid human actors should produce structured issues."""
    proposal = create_awaiting_confirmation_proposal()

    result = apply_confirmation_decision(
        proposal,
        ConfirmationDecision.APPROVED,
        "   ",
        decided_at=EVALUATED_AT,
    )

    assert result.success is False
    assert result.proposal is proposal
    assert result.record is None
    assert result.transition is None
    assert result.issues[0].code == "invalid_actor"


def test_successful_decision_application_requires_record() -> None:
    """Successful decision application should contain a record."""
    proposal = create_awaiting_confirmation_proposal()

    transition_result = transition_proposal(
        proposal,
        ActionStatus.APPROVED,
        transitioned_at=EVALUATED_AT,
    )

    assert transition_result.transition is not None

    with pytest.raises(
        ActionContractError,
        match="must contain a confirmation record",
    ):
        ConfirmationDecisionApplicationResult(
            success=True,
            proposal=transition_result.proposal,
            record=None,
            transition=transition_result.transition,
            issues=(),
        )


def test_successful_decision_application_requires_transition() -> None:
    """Successful decision application should contain a transition."""
    proposal = create_awaiting_confirmation_proposal()
    record_result = record_confirmation(
        proposal,
        ConfirmationDecision.APPROVED,
        "user:marius",
        decided_at=EVALUATED_AT,
    )

    assert record_result.record is not None

    with pytest.raises(
        ActionContractError,
        match="must contain a transition record",
    ):
        ConfirmationDecisionApplicationResult(
            success=True,
            proposal=proposal,
            record=record_result.record,
            transition=None,
            issues=(),
        )


def test_failed_decision_application_requires_issues() -> None:
    """Failed decision application should contain issues."""
    proposal = create_awaiting_confirmation_proposal()

    with pytest.raises(
        ActionContractError,
        match="at least one issue",
    ):
        ConfirmationDecisionApplicationResult(
            success=False,
            proposal=proposal,
            record=None,
            transition=None,
            issues=(),
        )
