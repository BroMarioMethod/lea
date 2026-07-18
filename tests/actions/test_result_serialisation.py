"""Tests for validation and execution-result serialisation."""

from datetime import UTC, datetime, timedelta

from lea.actions import (
    ActionStatus,
    ExecutionError,
    ExecutionResult,
    ValidationIssue,
    ValidationResult,
)

PROPOSAL_ID = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"
STARTED_AT = datetime(2026, 7, 18, 20, 0, tzinfo=UTC)
COMPLETED_AT = STARTED_AT + timedelta(seconds=1)


def test_validation_issue_serialisation() -> None:
    """Validation issues should serialise deterministically."""
    issue = ValidationIssue(
        code="invalid_action_name",
        message="The action name is invalid.",
        field="action",
    )

    assert issue.to_dict() == {
        "code": "invalid_action_name",
        "message": "The action name is invalid.",
        "field": "action",
    }


def test_validation_result_serialisation() -> None:
    """Validation results should serialise their issues."""
    issue = ValidationIssue(
        code="invalid_action_name",
        message="The action name is invalid.",
        field="action",
    )
    result = ValidationResult(
        valid=False,
        issues=(issue,),
    )

    assert result.to_dict() == {
        "valid": False,
        "issues": [
            {
                "code": "invalid_action_name",
                "message": "The action name is invalid.",
                "field": "action",
            }
        ],
    }


def test_execution_error_serialisation() -> None:
    """Execution errors should serialise structured details."""
    error = ExecutionError(
        code="handler_failure",
        message="The handler failed.",
        details={
            "retryable": False,
            "attempts": [1, 2],
        },
    )

    assert error.to_dict() == {
        "code": "handler_failure",
        "message": "The handler failed.",
        "details": {
            "retryable": False,
            "attempts": [1, 2],
        },
    }


def test_execution_result_serialisation() -> None:
    """Execution results should serialise all contract fields."""
    result = ExecutionResult(
        proposal_id=PROPOSAL_ID,
        success=True,
        status=ActionStatus.SUCCEEDED,
        output={
            "external_id": "42",
            "tags": ["created"],
        },
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )

    assert result.to_dict() == {
        "proposal_id": PROPOSAL_ID,
        "success": True,
        "status": "succeeded",
        "output": {
            "external_id": "42",
            "tags": ["created"],
        },
        "error": None,
        "started_at": "2026-07-18T20:00:00+00:00",
        "completed_at": "2026-07-18T20:00:01+00:00",
    }


def test_failed_execution_result_serialisation() -> None:
    """Failed results should include their structured execution error."""
    error = ExecutionError(
        code="handler_failure",
        message="The handler failed.",
    )
    result = ExecutionResult(
        proposal_id=PROPOSAL_ID,
        success=False,
        status=ActionStatus.FAILED,
        error=error,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )

    assert result.to_dict()["error"] == {
        "code": "handler_failure",
        "message": "The handler failed.",
        "details": None,
    }
