"""Tests for action proposal models."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from lea.actions import (
    ActionContractError,
    ActionProposal,
    ActionStatus,
    ConfirmationPolicy,
    RiskLevel,
)


def test_proposal_uses_safe_defaults() -> None:
    """New proposals should favour review rather than execution."""
    proposal = ActionProposal(
        action="task.create",
        parameters={"description": "Call John"},
        source="user",
    )

    assert proposal.status is ActionStatus.PROPOSED
    assert proposal.risk_level is RiskLevel.MEDIUM
    assert proposal.confirmation_policy is ConfirmationPolicy.WHEN_REQUIRED
    assert proposal.created_at.tzinfo is not None


def test_proposal_generates_canonical_uuid() -> None:
    """A proposal should receive a canonical UUID by default."""
    proposal = ActionProposal(
        action="task.create",
        parameters={},
        source="user",
    )

    assert str(UUID(proposal.proposal_id)) == proposal.proposal_id
    assert proposal.proposal_id == proposal.proposal_id.lower()


def test_proposal_accepts_supplied_identifier() -> None:
    """Callers should be able to supply deterministic identifiers."""
    proposal_id = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"

    proposal = ActionProposal(
        proposal_id=proposal_id,
        action="calendar.event_create",
        parameters={},
        source="workflow",
    )

    assert proposal.proposal_id == proposal_id


@pytest.mark.parametrize(
    "action",
    [
        "task.create",
        "calendar.event_create",
        "finance.transaction_record",
        "crm.person_update",
        "domain_2.operation_3",
    ],
)
def test_proposal_accepts_valid_action_names(action: str) -> None:
    """Namespaced lower-case action names should be accepted."""
    proposal = ActionProposal(
        action=action,
        parameters={},
        source="user",
    )

    assert proposal.action == action


@pytest.mark.parametrize(
    "action",
    [
        "create",
        "Task.create",
        ".task.create",
        "task.create.",
        "task..create",
        "task-create",
        "task create",
    ],
)
def test_proposal_rejects_invalid_action_names(action: str) -> None:
    """Malformed action names should be rejected."""
    with pytest.raises(
        ActionContractError,
        match="namespaced identifier",
    ):
        ActionProposal(
            action=action,
            parameters={},
            source="user",
        )


def test_proposal_accepts_nested_json_parameters() -> None:
    """Nested JSON-compatible parameters should be accepted."""
    proposal = ActionProposal(
        action="task.create",
        parameters={
            "description": "Call John",
            "priority": 2,
            "completed": False,
            "metadata": {
                "tags": ["client", "follow_up"],
                "estimate_hours": 1.5,
                "note": None,
            },
        },
        source="user",
    )

    assert proposal.parameters["description"] == "Call John"


@pytest.mark.parametrize(
    "unsupported_value",
    [
        object(),
        b"bytes",
        {"set"},
        ("tuple",),
    ],
)
def test_proposal_rejects_unsupported_parameter_values(
    unsupported_value: object,
) -> None:
    """Parameters should reject values unsupported by JSON."""
    with pytest.raises(
        ActionContractError,
        match="unsupported value",
    ):
        ActionProposal(
            action="task.create",
            parameters={"value": unsupported_value},
            source="user",
        )


@pytest.mark.parametrize(
    "number",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_proposal_rejects_non_finite_numbers(number: float) -> None:
    """JSON parameters should reject non-finite floating-point values."""
    with pytest.raises(
        ActionContractError,
        match="non-finite",
    ):
        ActionProposal(
            action="task.create",
            parameters={"value": number},
            source="user",
        )


def test_proposal_rejects_naive_timestamp() -> None:
    """Creation timestamps should include timezone information."""
    with pytest.raises(
        ActionContractError,
        match="timezone-aware",
    ):
        ActionProposal(
            action="task.create",
            parameters={},
            source="user",
            created_at=datetime(2026, 7, 18, 20, 0),
        )


def test_proposal_accepts_aware_timestamp() -> None:
    """Timezone-aware creation timestamps should be accepted."""
    timestamp = datetime(2026, 7, 18, 20, 0, tzinfo=UTC)

    proposal = ActionProposal(
        action="task.create",
        parameters={},
        source="user",
        created_at=timestamp,
    )

    assert proposal.created_at == timestamp


def test_proposal_rejects_empty_source() -> None:
    """Proposal sources should not be empty."""
    with pytest.raises(
        ActionContractError,
        match="non-empty",
    ):
        ActionProposal(
            action="task.create",
            parameters={},
            source="   ",
        )


def test_proposal_parameters_are_deeply_immutable() -> None:
    """Nested proposal parameters should not be mutable."""
    proposal = ActionProposal(
        action="task.create",
        parameters={
            "metadata": {
                "tags": ["client", "follow_up"],
            }
        },
        source="user",
    )

    with pytest.raises(TypeError):
        proposal.parameters["new"] = "value"  # type: ignore[index]
