"""Tests for action execution-result contracts."""

from datetime import UTC, datetime, timedelta

import pytest

from lea.actions import (
    ActionContractError,
    ActionStatus,
    ExecutionError,
    ExecutionResult,
)

PROPOSAL_ID = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"
STARTED_AT = datetime(2026, 7, 18, 20, 0, tzinfo=UTC)
COMPLETED_AT = STARTED_AT + timedelta(seconds=1)


def test_successful_execution_result() -> None:
    """Successful results should use the succeeded state."""
    result = ExecutionResult(
        proposal_id=PROPOSAL_ID,
        success=True,
        status=ActionStatus.SUCCEEDED,
        output={"external_id": "42"},
        error=None,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )

    assert result.success is True
    assert result.status is ActionStatus.SUCCEEDED
    assert result.error is None
    assert result.output == {"external_id": "42"}


def test_failed_execution_result() -> None:
    """Failed results should contain structured error information."""
    error = ExecutionError(
        code="handler_failure",
        message="The action handler failed.",
        details={"retryable": False},
    )

    result = ExecutionResult(
        proposal_id=PROPOSAL_ID,
        success=False,
        status=ActionStatus.FAILED,
        output=None,
        error=error,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )

    assert result.success is False
    assert result.status is ActionStatus.FAILED
    assert result.error == error


def test_success_requires_succeeded_status() -> None:
    """Successful results should reject any other final status."""
    with pytest.raises(
        ActionContractError,
        match="must use status 'succeeded'",
    ):
        ExecutionResult(
            proposal_id=PROPOSAL_ID,
            success=True,
            status=ActionStatus.FAILED,
            started_at=STARTED_AT,
            completed_at=COMPLETED_AT,
        )


def test_success_rejects_execution_error() -> None:
    """Successful results should not contain an error."""
    error = ExecutionError(
        code="unexpected_error",
        message="Unexpected error.",
    )

    with pytest.raises(
        ActionContractError,
        match="must not contain",
    ):
        ExecutionResult(
            proposal_id=PROPOSAL_ID,
            success=True,
            status=ActionStatus.SUCCEEDED,
            error=error,
            started_at=STARTED_AT,
            completed_at=COMPLETED_AT,
        )


def test_failure_requires_failed_status() -> None:
    """Failed results should use the failed final status."""
    error = ExecutionError(
        code="handler_failure",
        message="The action handler failed.",
    )

    with pytest.raises(
        ActionContractError,
        match="must use status 'failed'",
    ):
        ExecutionResult(
            proposal_id=PROPOSAL_ID,
            success=False,
            status=ActionStatus.CANCELLED,
            error=error,
            started_at=STARTED_AT,
            completed_at=COMPLETED_AT,
        )


def test_failure_requires_execution_error() -> None:
    """Failed results should include structured error information."""
    with pytest.raises(
        ActionContractError,
        match="must contain an execution error",
    ):
        ExecutionResult(
            proposal_id=PROPOSAL_ID,
            success=False,
            status=ActionStatus.FAILED,
            started_at=STARTED_AT,
            completed_at=COMPLETED_AT,
        )


@pytest.mark.parametrize(
    ("field_name", "started_at", "completed_at"),
    [
        (
            "started_at",
            datetime(2026, 7, 18, 20, 0),
            COMPLETED_AT,
        ),
        (
            "completed_at",
            STARTED_AT,
            datetime(2026, 7, 18, 20, 0),
        ),
    ],
)
def test_execution_timestamps_must_be_timezone_aware(
    field_name: str,
    started_at: datetime,
    completed_at: datetime,
) -> None:
    """Execution timestamps should contain timezone information."""
    with pytest.raises(
        ActionContractError,
        match=rf"{field_name} must be timezone-aware",
    ):
        ExecutionResult(
            proposal_id=PROPOSAL_ID,
            success=True,
            status=ActionStatus.SUCCEEDED,
            started_at=started_at,
            completed_at=completed_at,
        )


def test_completion_cannot_precede_start() -> None:
    """Completion should not occur before execution begins."""
    with pytest.raises(
        ActionContractError,
        match="must not occur before",
    ):
        ExecutionResult(
            proposal_id=PROPOSAL_ID,
            success=True,
            status=ActionStatus.SUCCEEDED,
            started_at=COMPLETED_AT,
            completed_at=STARTED_AT,
        )


def test_execution_output_is_immutable() -> None:
    """Structured result output should be deeply immutable."""
    result = ExecutionResult(
        proposal_id=PROPOSAL_ID,
        success=True,
        status=ActionStatus.SUCCEEDED,
        output={
            "metadata": {
                "tags": ["created", "verified"],
            }
        },
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )

    assert result.output is not None

    with pytest.raises(TypeError):
        result.output["changed"] = True  # type: ignore[index]


def test_execution_error_details_are_immutable() -> None:
    """Structured error details should be deeply immutable."""
    error = ExecutionError(
        code="handler_failure",
        message="The action handler failed.",
        details={
            "context": {
                "attempt": 1,
            }
        },
    )

    assert error.details is not None

    with pytest.raises(TypeError):
        error.details["changed"] = True  # type: ignore[index]


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("", "A message."),
        ("   ", "A message."),
        ("example", ""),
        ("example", "   "),
    ],
)
def test_execution_error_requires_code_and_message(
    code: str,
    message: str,
) -> None:
    """Execution errors should contain meaningful identifiers and text."""
    with pytest.raises(
        ActionContractError,
        match="non-empty string",
    ):
        ExecutionError(
            code=code,
            message=message,
        )
