"""Tests for immutable action-orchestration contracts."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from lea.actions import (
    ActionProposal,
    ActionStatus,
    ConfirmationPolicy,
    RiskLevel,
    ValidationIssue,
    ValidationResult,
)
from lea.orchestration import (
    ConfirmationOrchestrationResult,
    ExecutionOrchestrationResult,
    OrchestrationIssue,
    OrchestrationOutcome,
    SubmissionResult,
)

PROPOSAL_ID = "11111111-1111-4111-8111-111111111111"


def create_proposal() -> ActionProposal:
    """Create one deterministic proposal."""
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={"description": "Test task"},
        status=ActionStatus.PROPOSED,
        risk_level=RiskLevel.LOW,
        confirmation_policy=ConfirmationPolicy.WHEN_REQUIRED,
        source="test",
        created_at=datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
        reason="Exercise orchestration contracts.",
    )


def valid_validation() -> ValidationResult:
    """Return one successful validation result."""
    return ValidationResult(
        valid=True,
        issues=(),
    )


def invalid_validation() -> ValidationResult:
    """Return one failed validation result."""
    return ValidationResult(
        valid=False,
        issues=(
            ValidationIssue(
                code="invalid_action",
                message="The action is invalid.",
                field="action",
            ),
        ),
    )


def create_issue() -> OrchestrationIssue:
    """Create one deterministic orchestration issue."""
    return OrchestrationIssue(
        code="audit_append_failed",
        message="The audit event could not be persisted.",
        operation="submit",
        proposal_id=PROPOSAL_ID,
    )


def test_outcome_values_are_stable() -> None:
    """Public outcomes should use stable serialisable values."""
    assert OrchestrationOutcome.SUBMITTED.value == "submitted"
    assert OrchestrationOutcome.AUDIT_FAILED.value == "audit_failed"
    assert OrchestrationOutcome.EXECUTION_SUCCEEDED.value == "execution_succeeded"


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("code", "code must be a non-empty"),
        ("message", "message must be a non-empty"),
        ("operation", "operation must be a non-empty"),
        ("proposal_id", "proposal_id must be a non-empty"),
    ],
)
def test_orchestration_issue_rejects_blank_fields(
    field: str,
    message: str,
) -> None:
    """Every orchestration issue field should contain useful text."""
    values = {
        "code": "audit_append_failed",
        "message": "The audit event could not be persisted.",
        "operation": "submit",
        "proposal_id": PROPOSAL_ID,
    }
    values[field] = "   "

    with pytest.raises(ValueError, match=message):
        OrchestrationIssue(**values)


def test_orchestration_issue_is_immutable() -> None:
    """Issue records should not permit field reassignment."""
    issue = create_issue()

    with pytest.raises(FrozenInstanceError):
        issue.code = "changed"  # type: ignore[misc]


def test_valid_submission_result() -> None:
    """A normal submission result should require no issue."""
    proposal = create_proposal()

    result = SubmissionResult(
        outcome=OrchestrationOutcome.SUBMITTED,
        proposal=proposal,
        validation=valid_validation(),
        confirmation_policy=None,
        persisted_events=(),
    )

    assert result.proposal is proposal
    assert result.issue is None


def test_validation_failure_rejects_confirmation_result() -> None:
    """Invalid proposals must not contain confirmation-policy output."""
    proposal = create_proposal()

    with pytest.raises(
        ValueError,
        match="validation failure",
    ):
        SubmissionResult(
            outcome=OrchestrationOutcome.VALIDATION_FAILED,
            proposal=proposal,
            validation=invalid_validation(),
            confirmation_policy=object(),  # type: ignore[arg-type]
            persisted_events=(),
        )


def test_submission_result_rejects_execution_outcome() -> None:
    """Submission results should accept only submission outcomes."""
    with pytest.raises(ValueError, match="unsupported outcome"):
        SubmissionResult(
            outcome=OrchestrationOutcome.EXECUTION_SUCCEEDED,
            proposal=create_proposal(),
            validation=valid_validation(),
            confirmation_policy=None,
            persisted_events=(),
        )


def test_audit_failure_requires_issue() -> None:
    """An audit failure must explain the orchestration problem."""
    with pytest.raises(
        ValueError,
        match="must contain an issue",
    ):
        SubmissionResult(
            outcome=OrchestrationOutcome.AUDIT_FAILED,
            proposal=create_proposal(),
            validation=valid_validation(),
            confirmation_policy=None,
            persisted_events=(),
        )


def test_non_failure_rejects_issue() -> None:
    """Normal workflow outcomes must not contain failure issues."""
    with pytest.raises(
        ValueError,
        match="must not contain an issue",
    ):
        SubmissionResult(
            outcome=OrchestrationOutcome.SUBMITTED,
            proposal=create_proposal(),
            validation=valid_validation(),
            confirmation_policy=None,
            persisted_events=(),
            issue=create_issue(),
        )


def test_confirmation_result_accepts_approved_outcome() -> None:
    """Confirmation results should represent an applied approval."""
    result = ConfirmationOrchestrationResult(
        outcome=OrchestrationOutcome.APPROVED,
        proposal=create_proposal(),
        decision_application=None,
        persisted_events=(),
    )

    assert result.outcome is OrchestrationOutcome.APPROVED


def test_confirmation_result_rejects_submission_outcome() -> None:
    """Confirmation results should reject unrelated outcomes."""
    with pytest.raises(ValueError, match="unsupported outcome"):
        ConfirmationOrchestrationResult(
            outcome=OrchestrationOutcome.SUBMITTED,
            proposal=create_proposal(),
            decision_application=None,
            persisted_events=(),
        )


def test_execution_result_accepts_handled_failure() -> None:
    """A handled action failure is not an orchestration issue."""
    result = ExecutionOrchestrationResult(
        outcome=OrchestrationOutcome.EXECUTION_FAILED,
        proposal=create_proposal(),
        execution=None,
        persisted_events=(),
    )

    assert result.issue is None


def test_execution_result_rejects_confirmation_outcome() -> None:
    """Execution results should reject unrelated outcomes."""
    with pytest.raises(ValueError, match="unsupported outcome"):
        ExecutionOrchestrationResult(
            outcome=OrchestrationOutcome.APPROVED,
            proposal=create_proposal(),
            execution=None,
            persisted_events=(),
        )


def test_submission_result_is_immutable() -> None:
    """Public orchestration results should be immutable."""
    result = SubmissionResult(
        outcome=OrchestrationOutcome.SUBMITTED,
        proposal=create_proposal(),
        validation=valid_validation(),
        confirmation_policy=None,
        persisted_events=(),
    )

    with pytest.raises(FrozenInstanceError):
        result.issue = create_issue()  # type: ignore[misc]
