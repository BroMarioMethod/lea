"""Tests for deterministic action-execution orchestration."""

from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from lea.actions import (
    ActionContractError,
    ActionExecutionIssue,
    ActionExecutionResult,
    ActionHandlerRegistry,
    ActionProposal,
    ActionStatus,
    ExecutionError,
    ExecutionResult,
    execute_action,
)

PROPOSAL_ID = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"
STARTED_AT = datetime(2026, 7, 20, 18, 0, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 7, 20, 18, 1, tzinfo=UTC)


def create_proposal(
    status: ActionStatus = ActionStatus.APPROVED,
) -> ActionProposal:
    """Create a deterministic proposal for execution tests."""
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={"description": "Call John"},
        source="user",
        status=status,
        created_at=datetime(2026, 7, 20, 17, 0, tzinfo=UTC),
    )


def test_successful_action_execution() -> None:
    """An approved proposal should execute through its handler."""
    received: list[ActionProposal] = []

    def handler(
        proposal: ActionProposal,
    ) -> Mapping[str, object]:
        received.append(proposal)
        return {
            "created": True,
            "task_id": "task-001",
        }

    registry = ActionHandlerRegistry()
    registry.register("task.create", handler)
    proposal = create_proposal()
    original_data = proposal.to_dict()

    result = execute_action(
        proposal,
        registry,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )

    assert result.success is True
    assert result.proposal.status is ActionStatus.SUCCEEDED
    assert result.execution is not None
    assert result.execution.success is True
    assert result.execution.status is ActionStatus.SUCCEEDED
    assert result.execution.output == {
        "created": True,
        "task_id": "task-001",
    }
    assert result.execution.error is None
    assert result.issues == ()

    assert len(received) == 1
    assert received[0].status is ActionStatus.EXECUTING

    assert proposal.status is ActionStatus.APPROVED
    assert proposal.to_dict() == original_data


def test_successful_execution_records_both_transitions() -> None:
    """Successful execution should record start and completion."""
    registry = ActionHandlerRegistry()
    registry.register("task.create", lambda proposal: None)

    result = execute_action(
        create_proposal(),
        registry,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )

    assert result.start_transition is not None
    assert result.start_transition.from_status is ActionStatus.APPROVED
    assert result.start_transition.to_status is ActionStatus.EXECUTING
    assert result.start_transition.transitioned_at == STARTED_AT

    assert result.completion_transition is not None
    assert result.completion_transition.from_status is ActionStatus.EXECUTING
    assert result.completion_transition.to_status is ActionStatus.SUCCEEDED
    assert result.completion_transition.transitioned_at == COMPLETED_AT


@pytest.mark.parametrize(
    "status",
    [
        ActionStatus.PROPOSED,
        ActionStatus.VALIDATED,
        ActionStatus.AWAITING_CONFIRMATION,
        ActionStatus.EXECUTING,
        ActionStatus.REJECTED,
        ActionStatus.SUCCEEDED,
        ActionStatus.FAILED,
        ActionStatus.CANCELLED,
    ],
)
def test_non_approved_proposals_are_rejected(
    status: ActionStatus,
) -> None:
    """Every non-approved proposal state should fail closed."""
    calls = 0

    def handler(
        proposal: ActionProposal,
    ) -> None:
        nonlocal calls
        calls += 1

    registry = ActionHandlerRegistry()
    registry.register("task.create", handler)
    proposal = create_proposal(status)

    result = execute_action(
        proposal,
        registry,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )

    assert result.success is False
    assert result.proposal is proposal
    assert result.execution is None
    assert result.start_transition is None
    assert result.completion_transition is None
    assert result.issues[0].code == "invalid_proposal_status"
    assert calls == 0


def test_unknown_action_fails_without_invocation() -> None:
    """Unknown actions should leave approved proposals unchanged."""
    registry = ActionHandlerRegistry()
    proposal = create_proposal()

    result = execute_action(
        proposal,
        registry,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )

    assert result.success is False
    assert result.proposal is proposal
    assert result.proposal.status is ActionStatus.APPROVED
    assert result.execution is None
    assert result.start_transition is None
    assert result.completion_transition is None
    assert result.issues[0].code == "unknown_action"


def test_handler_is_invoked_exactly_once() -> None:
    """The execution boundary should not retry handlers."""
    calls = 0

    def handler(
        proposal: ActionProposal,
    ) -> None:
        nonlocal calls
        calls += 1

    registry = ActionHandlerRegistry()
    registry.register("task.create", handler)

    execute_action(
        create_proposal(),
        registry,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )

    assert calls == 1


def test_handler_exception_becomes_failed_execution() -> None:
    """Handler exceptions should be contained and structured."""

    def handler(
        proposal: ActionProposal,
    ) -> None:
        raise RuntimeError("Sensitive internal failure.")

    registry = ActionHandlerRegistry()
    registry.register("task.create", handler)

    result = execute_action(
        create_proposal(),
        registry,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )

    assert result.success is False
    assert result.proposal.status is ActionStatus.FAILED
    assert result.execution is not None
    assert result.execution.success is False
    assert result.execution.status is ActionStatus.FAILED
    assert result.execution.error is not None
    assert result.execution.error.code == "handler_exception"
    assert result.execution.error.details == {
        "exception_type": "RuntimeError",
    }
    assert "Sensitive internal failure" not in (result.execution.error.message)
    assert result.issues == ()

    assert result.completion_transition is not None
    assert result.completion_transition.to_status is ActionStatus.FAILED


def test_expected_handler_failure_preserves_redaction_safe_diagnostic() -> None:
    from lea.actions import ActionHandlerFailure

    def handler(proposal: ActionProposal) -> None:
        del proposal
        raise ActionHandlerFailure(
            code="provider_bootstrap_required",
            message="Explicit provider bootstrap approval is required.",
        )

    registry = ActionHandlerRegistry()
    registry.register("task.create", handler)

    result = execute_action(
        create_proposal(),
        registry,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )

    assert result.execution is not None
    assert result.execution.error is not None
    assert result.execution.error.code == "provider_bootstrap_required"
    assert result.execution.error.details is None


def test_non_mapping_handler_output_fails_safely() -> None:
    """Unsupported handler output should become an execution failure."""

    def handler(
        proposal: ActionProposal,
    ) -> Mapping[str, object] | None:
        return ["unsupported"]  # type: ignore[return-value]

    registry = ActionHandlerRegistry()
    registry.register("task.create", handler)

    result = execute_action(
        create_proposal(),
        registry,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )

    assert result.success is False
    assert result.proposal.status is ActionStatus.FAILED
    assert result.execution is not None
    assert result.execution.error is not None
    assert result.execution.error.code == "invalid_handler_output"


def test_unsupported_nested_output_fails_safely() -> None:
    """Non-JSON-compatible nested values should fail safely."""

    def handler(
        proposal: ActionProposal,
    ) -> Mapping[str, object]:
        return {
            "unsupported": object(),
        }

    registry = ActionHandlerRegistry()
    registry.register("task.create", handler)

    result = execute_action(
        create_proposal(),
        registry,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )

    assert result.success is False
    assert result.proposal.status is ActionStatus.FAILED
    assert result.execution is not None
    assert result.execution.error is not None
    assert result.execution.error.code == "invalid_handler_output"


@pytest.mark.parametrize(
    ("started_at", "completed_at", "field"),
    [
        (
            datetime(2026, 7, 20, 18, 0),
            COMPLETED_AT,
            "started_at",
        ),
        (
            STARTED_AT,
            datetime(2026, 7, 20, 18, 1),
            "completed_at",
        ),
    ],
)
def test_naive_injected_timestamps_are_rejected(
    started_at: datetime,
    completed_at: datetime,
    field: str,
) -> None:
    """Injected execution timestamps should be timezone-aware."""
    calls = 0

    def handler(
        proposal: ActionProposal,
    ) -> None:
        nonlocal calls
        calls += 1

    registry = ActionHandlerRegistry()
    registry.register("task.create", handler)

    result = execute_action(
        create_proposal(),
        registry,
        started_at=started_at,
        completed_at=completed_at,
    )

    assert result.success is False
    assert result.execution is None
    assert result.issues[0].code == "invalid_timestamp"
    assert result.issues[0].field == field
    assert calls == 0


def test_completion_before_start_is_rejected() -> None:
    """Completion may not occur before execution begins."""
    registry = ActionHandlerRegistry()
    registry.register("task.create", lambda proposal: None)

    result = execute_action(
        create_proposal(),
        registry,
        started_at=COMPLETED_AT,
        completed_at=STARTED_AT,
    )

    assert result.success is False
    assert result.execution is None
    assert result.issues[0].code == "invalid_timestamp_order"


def test_handler_output_is_frozen() -> None:
    """Successful handler output should become immutable."""
    mutable_output = {
        "items": ["one", "two"],
    }

    def handler(
        proposal: ActionProposal,
    ) -> Mapping[str, object]:
        return mutable_output

    registry = ActionHandlerRegistry()
    registry.register("task.create", handler)

    result = execute_action(
        create_proposal(),
        registry,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )

    assert result.execution is not None
    assert result.execution.output == {
        "items": ("one", "two"),
    }

    mutable_output["items"].append("three")

    assert result.execution.output == {
        "items": ("one", "two"),
    }


def test_successful_result_requires_execution_result() -> None:
    """Completed workflows should contain execution records."""
    proposal = create_proposal(ActionStatus.SUCCEEDED)

    with pytest.raises(
        ActionContractError,
        match="must contain an execution result",
    ):
        ActionExecutionResult(
            success=True,
            proposal=proposal,
            execution=None,
            start_transition=None,
            completion_transition=None,
            issues=(),
        )


def test_boundary_failure_rejects_execution_data() -> None:
    """Pre-execution failures must not contain execution records."""
    proposal = create_proposal()
    issue = ActionExecutionIssue(
        code="unknown_action",
        message="No handler is registered.",
        proposal_id=PROPOSAL_ID,
        field="action",
    )
    execution = ExecutionResult(
        proposal_id=PROPOSAL_ID,
        success=False,
        status=ActionStatus.FAILED,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
        error=ExecutionError(
            code="handler_exception",
            message="The handler failed.",
        ),
    )

    with pytest.raises(
        ActionContractError,
        match="must not contain an execution result",
    ):
        ActionExecutionResult(
            success=False,
            proposal=proposal,
            execution=execution,
            start_transition=None,
            completion_transition=None,
            issues=(issue,),
        )
