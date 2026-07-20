"""Tests for the canonical action transition policy."""

from datetime import UTC, datetime

import pytest

from lea.actions import (
    TERMINAL_STATUSES,
    TRANSITION_TABLE,
    ActionContractError,
    ActionProposal,
    ActionStatus,
    ActionTransition,
    TransitionIssue,
    TransitionResult,
    can_transition,
    transition_proposal,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ActionStatus.PROPOSED, ActionStatus.VALIDATED),
        (ActionStatus.PROPOSED, ActionStatus.REJECTED),
        (
            ActionStatus.VALIDATED,
            ActionStatus.AWAITING_CONFIRMATION,
        ),
        (ActionStatus.VALIDATED, ActionStatus.APPROVED),
        (ActionStatus.VALIDATED, ActionStatus.REJECTED),
        (
            ActionStatus.AWAITING_CONFIRMATION,
            ActionStatus.APPROVED,
        ),
        (
            ActionStatus.AWAITING_CONFIRMATION,
            ActionStatus.REJECTED,
        ),
        (
            ActionStatus.AWAITING_CONFIRMATION,
            ActionStatus.CANCELLED,
        ),
        (ActionStatus.APPROVED, ActionStatus.EXECUTING),
        (ActionStatus.APPROVED, ActionStatus.CANCELLED),
        (ActionStatus.EXECUTING, ActionStatus.SUCCEEDED),
        (ActionStatus.EXECUTING, ActionStatus.FAILED),
    ],
)
def test_permitted_transitions(
    current: ActionStatus,
    target: ActionStatus,
) -> None:
    """Every canonical permitted transition should be accepted."""
    assert can_transition(current, target) is True


def test_transition_table_covers_every_status() -> None:
    """The policy table should define every lifecycle state."""
    assert set(TRANSITION_TABLE) == set(ActionStatus)


@pytest.mark.parametrize("status", list(ActionStatus))
def test_self_transitions_are_not_permitted(
    status: ActionStatus,
) -> None:
    """No state should transition to itself."""
    assert can_transition(status, status) is False


@pytest.mark.parametrize("status", list(TERMINAL_STATUSES))
def test_terminal_states_have_no_outgoing_transitions(
    status: ActionStatus,
) -> None:
    """Terminal states should remain closed."""
    assert TRANSITION_TABLE[status] == frozenset()


def test_transition_record_requires_aware_timestamp() -> None:
    """Transition records should reject naive timestamps."""
    with pytest.raises(
        ActionContractError,
        match="timezone-aware",
    ):
        ActionTransition(
            proposal_id="4b10f26d-0c54-4f3d-a14c-bce8a743116f",
            from_status=ActionStatus.PROPOSED,
            to_status=ActionStatus.VALIDATED,
            transitioned_at=datetime(2026, 7, 18, 20, 0),
        )


def test_successful_result_requires_transition() -> None:
    """Successful results should contain a transition record."""
    with pytest.raises(
        ActionContractError,
        match="must contain a transition record",
    ):
        TransitionResult(
            success=True,
            proposal=create_proposal(),
            transition=None,
            issues=(),
        )


def test_successful_result_rejects_issues() -> None:
    """Successful results should not contain issues."""
    transition = ActionTransition(
        proposal_id="4b10f26d-0c54-4f3d-a14c-bce8a743116f",
        from_status=ActionStatus.PROPOSED,
        to_status=ActionStatus.VALIDATED,
        transitioned_at=datetime(
            2026,
            7,
            18,
            20,
            0,
            tzinfo=UTC,
        ),
    )
    issue = TransitionIssue(
        code="invalid_transition",
        message="The transition is not permitted.",
        from_status=ActionStatus.PROPOSED,
        to_status=ActionStatus.SUCCEEDED,
    )

    with pytest.raises(
        ActionContractError,
        match="must not contain issues",
    ):
        TransitionResult(
            success=True,
            proposal=create_proposal(),
            transition=transition,
            issues=(issue,),
        )


def test_failed_result_requires_issues() -> None:
    """Failed results should contain at least one issue."""
    with pytest.raises(
        ActionContractError,
        match="at least one issue",
    ):
        TransitionResult(
            success=False,
            proposal=create_proposal(),
            transition=None,
            issues=(),
        )


def test_failed_result_rejects_transition_record() -> None:
    """Failed results should not contain a transition record."""
    transition = ActionTransition(
        proposal_id="4b10f26d-0c54-4f3d-a14c-bce8a743116f",
        from_status=ActionStatus.PROPOSED,
        to_status=ActionStatus.VALIDATED,
        transitioned_at=datetime(
            2026,
            7,
            18,
            20,
            0,
            tzinfo=UTC,
        ),
    )

    with pytest.raises(
        ActionContractError,
        match="must not contain a transition record",
    ):
        TransitionResult(
            success=False,
            proposal=create_proposal(),
            transition=transition,
            issues=(
                TransitionIssue(
                    code="invalid_transition",
                    message="The transition is not permitted.",
                    from_status=ActionStatus.PROPOSED,
                    to_status=ActionStatus.SUCCEEDED,
                ),
            ),
        )


PROPOSAL_ID = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"
CREATED_AT = datetime(2026, 7, 18, 19, 0, tzinfo=UTC)
TRANSITIONED_AT = datetime(2026, 7, 18, 20, 0, tzinfo=UTC)


def create_proposal(
    status: ActionStatus = ActionStatus.PROPOSED,
) -> ActionProposal:
    """Create a deterministic proposal for transition tests."""
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={
            "description": "Call John",
            "metadata": {
                "tags": ["client"],
            },
        },
        source="user",
        status=status,
        created_at=CREATED_AT,
        reason="The user requested a follow-up task.",
    )


def test_transition_proposal_creates_new_record() -> None:
    """A permitted transition should create a new proposal."""
    original = create_proposal()

    result = transition_proposal(
        original,
        ActionStatus.VALIDATED,
        reason="Proposal data passed validation.",
        transitioned_at=TRANSITIONED_AT,
    )

    assert result.success is True
    assert result.proposal is not original
    assert result.proposal.status is ActionStatus.VALIDATED
    assert original.status is ActionStatus.PROPOSED


def test_transition_preserves_proposal_fields() -> None:
    """Only proposal status should change during a transition."""
    original = create_proposal()

    result = transition_proposal(
        original,
        ActionStatus.VALIDATED,
        transitioned_at=TRANSITIONED_AT,
    )

    transitioned = result.proposal

    assert transitioned.proposal_id == original.proposal_id
    assert transitioned.action == original.action
    assert transitioned.parameters == original.parameters
    assert transitioned.source == original.source
    assert transitioned.created_at == original.created_at
    assert transitioned.reason == original.reason
    assert transitioned.risk_level is original.risk_level
    assert transitioned.confirmation_policy is original.confirmation_policy


def test_transition_creates_audit_record() -> None:
    """A successful transition should produce an audit record."""
    original = create_proposal()

    result = transition_proposal(
        original,
        ActionStatus.VALIDATED,
        reason="Proposal data passed validation.",
        transitioned_at=TRANSITIONED_AT,
    )

    assert result.transition is not None
    assert result.transition.proposal_id == PROPOSAL_ID
    assert result.transition.from_status is ActionStatus.PROPOSED
    assert result.transition.to_status is ActionStatus.VALIDATED
    assert result.transition.transitioned_at == TRANSITIONED_AT
    assert result.transition.reason == "Proposal data passed validation."


def test_invalid_transition_returns_original_proposal() -> None:
    """Rejected transitions should preserve the original proposal."""
    original = create_proposal()

    result = transition_proposal(
        original,
        ActionStatus.SUCCEEDED,
        transitioned_at=TRANSITIONED_AT,
    )

    assert result.success is False
    assert result.proposal is original
    assert result.transition is None
    assert result.issues[0].code == "invalid_transition"


def test_self_transition_returns_structured_issue() -> None:
    """Self-transitions should return a dedicated issue."""
    original = create_proposal(ActionStatus.VALIDATED)

    result = transition_proposal(
        original,
        ActionStatus.VALIDATED,
        transitioned_at=TRANSITIONED_AT,
    )

    assert result.success is False
    assert result.issues[0].code == "self_transition"


@pytest.mark.parametrize("status", list(TERMINAL_STATUSES))
def test_terminal_transition_returns_structured_issue(
    status: ActionStatus,
) -> None:
    """Terminal states should reject every outgoing transition."""
    original = create_proposal(status)

    result = transition_proposal(
        original,
        ActionStatus.PROPOSED,
        transitioned_at=TRANSITIONED_AT,
    )

    assert result.success is False
    assert result.issues[0].code == "terminal_state"


def test_transition_rejects_naive_timestamp() -> None:
    """Explicit transition timestamps should be timezone-aware."""
    original = create_proposal()

    with pytest.raises(
        ActionContractError,
        match="timezone-aware",
    ):
        transition_proposal(
            original,
            ActionStatus.VALIDATED,
            transitioned_at=datetime(2026, 7, 18, 20, 0),
        )


def test_transition_parameters_remain_immutable() -> None:
    """Transitioned proposal parameters should remain deeply immutable."""
    original = create_proposal()

    result = transition_proposal(
        original,
        ActionStatus.VALIDATED,
        transitioned_at=TRANSITIONED_AT,
    )

    with pytest.raises(TypeError):
        result.proposal.parameters["changed"] = True  # type: ignore[index]
