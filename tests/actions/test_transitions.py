"""Tests for the canonical action transition policy."""

from datetime import UTC, datetime

import pytest

from lea.actions import (
    TERMINAL_STATUSES,
    TRANSITION_TABLE,
    ActionContractError,
    ActionStatus,
    ActionTransition,
    TransitionIssue,
    TransitionResult,
    can_transition,
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
            proposal=object(),
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
            proposal=object(),
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
            proposal=object(),
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
            proposal=object(),
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
