"""Tests for deterministic action-execution serialisation."""

from collections.abc import Mapping
from datetime import UTC, datetime

from lea.actions import (
    ActionExecutionIssue,
    ActionHandlerRegistry,
    ActionProposal,
    ActionStatus,
    execute_action,
)

PROPOSAL_ID = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"
CREATED_AT = datetime(2026, 7, 20, 17, 0, tzinfo=UTC)
STARTED_AT = datetime(2026, 7, 20, 18, 0, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 7, 20, 18, 1, tzinfo=UTC)


def create_approved_proposal() -> ActionProposal:
    """Create a deterministic approved proposal."""
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={"description": "Call John"},
        source="user",
        status=ActionStatus.APPROVED,
        created_at=CREATED_AT,
    )


def test_execution_issue_serialisation() -> None:
    """Execution-boundary issues should serialise deterministically."""
    issue = ActionExecutionIssue(
        code="unknown_action",
        message="No handler is registered.",
        proposal_id=PROPOSAL_ID,
        field="action",
    )

    assert issue.to_dict() == {
        "code": "unknown_action",
        "message": "No handler is registered.",
        "proposal_id": PROPOSAL_ID,
        "field": "action",
    }


def test_successful_execution_result_serialisation() -> None:
    """Successful orchestration should serialise all nested records."""

    def handler(
        proposal: ActionProposal,
    ) -> Mapping[str, object]:
        return {
            "created": True,
            "task_id": "task-001",
        }

    registry = ActionHandlerRegistry()
    registry.register("task.create", handler)

    result = execute_action(
        create_approved_proposal(),
        registry,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )
    data = result.to_dict()

    assert data["success"] is True
    assert data["issues"] == []

    proposal = data["proposal"]
    assert isinstance(proposal, dict)
    assert proposal["status"] == "succeeded"

    execution = data["execution"]
    assert isinstance(execution, dict)
    assert execution["success"] is True
    assert execution["status"] == "succeeded"
    assert execution["output"] == {
        "created": True,
        "task_id": "task-001",
    }
    assert execution["error"] is None
    assert execution["started_at"] == "2026-07-20T18:00:00+00:00"
    assert execution["completed_at"] == "2026-07-20T18:01:00+00:00"

    start_transition = data["start_transition"]
    assert isinstance(start_transition, dict)
    assert start_transition["from_status"] == "approved"
    assert start_transition["to_status"] == "executing"

    completion_transition = data["completion_transition"]
    assert isinstance(completion_transition, dict)
    assert completion_transition["from_status"] == "executing"
    assert completion_transition["to_status"] == "succeeded"


def test_handler_failure_result_serialisation() -> None:
    """Handled exceptions should serialise without exception objects."""

    def handler(
        proposal: ActionProposal,
    ) -> None:
        raise RuntimeError("Sensitive internal failure.")

    registry = ActionHandlerRegistry()
    registry.register("task.create", handler)

    result = execute_action(
        create_approved_proposal(),
        registry,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )
    data = result.to_dict()

    assert data["success"] is False
    assert data["issues"] == []

    proposal = data["proposal"]
    assert isinstance(proposal, dict)
    assert proposal["status"] == "failed"

    execution = data["execution"]
    assert isinstance(execution, dict)
    assert execution["success"] is False
    assert execution["status"] == "failed"

    error = execution["error"]
    assert isinstance(error, dict)
    assert error == {
        "code": "handler_exception",
        "message": "The action handler raised an exception.",
        "details": {
            "exception_type": "RuntimeError",
        },
    }

    assert "Sensitive internal failure" not in str(data)


def test_pre_execution_failure_serialisation() -> None:
    """Boundary failures should serialise issues without execution data."""
    registry = ActionHandlerRegistry()

    result = execute_action(
        create_approved_proposal(),
        registry,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )
    data = result.to_dict()

    assert data["success"] is False
    assert data["execution"] is None
    assert data["start_transition"] is None
    assert data["completion_transition"] is None

    proposal = data["proposal"]
    assert isinstance(proposal, dict)
    assert proposal["status"] == "approved"

    issues = data["issues"]
    assert isinstance(issues, list)
    assert issues == [
        {
            "code": "unknown_action",
            "message": ("No action handler is registered for 'task.create'."),
            "proposal_id": PROPOSAL_ID,
            "field": "action",
        }
    ]


def test_serialised_result_contains_no_runtime_objects() -> None:
    """Serialised output should not expose handlers or registries."""
    registry = ActionHandlerRegistry()
    registry.register("task.create", lambda proposal: None)

    result = execute_action(
        create_approved_proposal(),
        registry,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )
    data = result.to_dict()
    rendered = repr(data)

    assert "ActionHandlerRegistry" not in rendered
    assert "function" not in rendered
    assert "lambda" not in rendered
