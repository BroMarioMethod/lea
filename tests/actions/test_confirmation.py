"""Tests for deterministic confirmation-policy evaluation."""

from datetime import UTC, datetime

import pytest

from lea.actions import (
    CONFIRMATION_MATRIX,
    ActionContractError,
    ActionProposal,
    ActionStatus,
    ConfirmationEvaluation,
    ConfirmationEvaluationResult,
    ConfirmationIssue,
    ConfirmationPolicy,
    ConfirmationRequirement,
    RiskLevel,
    evaluate_confirmation,
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
