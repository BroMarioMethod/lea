"""Tests for action-transition serialisation."""

from datetime import UTC, datetime

from lea.actions import (
    ActionProposal,
    ActionStatus,
    ActionTransition,
    TransitionIssue,
    TransitionResult,
)

PROPOSAL_ID = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"
CREATED_AT = datetime(2026, 7, 18, 19, 0, tzinfo=UTC)
TRANSITIONED_AT = datetime(2026, 7, 18, 20, 0, tzinfo=UTC)


def create_proposal(
    status: ActionStatus = ActionStatus.PROPOSED,
) -> ActionProposal:
    """Create a deterministic proposal for serialisation tests."""
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={"description": "Call John"},
        source="user",
        status=status,
        created_at=CREATED_AT,
    )


def test_action_transition_serialisation() -> None:
    """Transition records should serialise deterministically."""
    transition = ActionTransition(
        proposal_id=PROPOSAL_ID,
        from_status=ActionStatus.PROPOSED,
        to_status=ActionStatus.VALIDATED,
        transitioned_at=TRANSITIONED_AT,
        reason="Proposal data passed validation.",
    )

    assert transition.to_dict() == {
        "proposal_id": PROPOSAL_ID,
        "from_status": "proposed",
        "to_status": "validated",
        "transitioned_at": "2026-07-18T20:00:00+00:00",
        "reason": "Proposal data passed validation.",
    }


def test_transition_issue_serialisation() -> None:
    """Transition issues should serialise deterministically."""
    issue = TransitionIssue(
        code="invalid_transition",
        message="The transition is not permitted.",
        from_status=ActionStatus.PROPOSED,
        to_status=ActionStatus.SUCCEEDED,
    )

    assert issue.to_dict() == {
        "code": "invalid_transition",
        "message": "The transition is not permitted.",
        "from_status": "proposed",
        "to_status": "succeeded",
    }


def test_successful_transition_result_serialisation() -> None:
    """Successful transition results should include the new proposal."""
    transitioned = create_proposal(ActionStatus.VALIDATED)
    transition = ActionTransition(
        proposal_id=PROPOSAL_ID,
        from_status=ActionStatus.PROPOSED,
        to_status=ActionStatus.VALIDATED,
        transitioned_at=TRANSITIONED_AT,
    )
    result = TransitionResult(
        success=True,
        proposal=transitioned,
        transition=transition,
        issues=(),
    )

    data = result.to_dict()

    assert data["success"] is True
    assert data["transition"] == {
        "proposal_id": PROPOSAL_ID,
        "from_status": "proposed",
        "to_status": "validated",
        "transitioned_at": "2026-07-18T20:00:00+00:00",
        "reason": None,
    }

    proposal = data["proposal"]
    assert isinstance(proposal, dict)
    assert proposal["status"] == "validated"

    assert data["issues"] == []


def test_failed_transition_result_serialisation() -> None:
    """Failed transition results should include structured issues."""
    original = create_proposal()
    issue = TransitionIssue(
        code="invalid_transition",
        message="The transition is not permitted.",
        from_status=ActionStatus.PROPOSED,
        to_status=ActionStatus.SUCCEEDED,
    )
    result = TransitionResult(
        success=False,
        proposal=original,
        transition=None,
        issues=(issue,),
    )

    data = result.to_dict()

    assert data["success"] is False
    assert data["transition"] is None
    assert data["issues"] == [
        {
            "code": "invalid_transition",
            "message": "The transition is not permitted.",
            "from_status": "proposed",
            "to_status": "succeeded",
        }
    ]

    proposal = data["proposal"]
    assert isinstance(proposal, dict)
    assert proposal["status"] == "proposed"
