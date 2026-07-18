"""Tests for action-proposal serialisation."""

from datetime import UTC, datetime

import pytest

from lea.actions import (
    ActionContractError,
    ActionProposal,
    ActionStatus,
    ConfirmationPolicy,
    RiskLevel,
    proposal_from_dict,
    proposal_to_dict,
)

PROPOSAL_ID = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"
CREATED_AT = datetime(2026, 7, 18, 20, 0, tzinfo=UTC)


def create_proposal() -> ActionProposal:
    """Create a deterministic proposal for serialisation tests."""
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={
            "description": "Call John",
            "metadata": {
                "tags": ["client", "follow_up"],
                "priority": 2,
            },
        },
        status=ActionStatus.PROPOSED,
        risk_level=RiskLevel.MEDIUM,
        confirmation_policy=ConfirmationPolicy.WHEN_REQUIRED,
        source="user",
        created_at=CREATED_AT,
        reason="The user requested a follow-up task.",
    )


def test_proposal_serialisation_is_json_compatible() -> None:
    """Serialised proposals should contain standard JSON-compatible values."""
    data = proposal_to_dict(create_proposal())

    assert data == {
        "schema_version": 1,
        "proposal_id": PROPOSAL_ID,
        "action": "task.create",
        "parameters": {
            "description": "Call John",
            "metadata": {
                "tags": ["client", "follow_up"],
                "priority": 2,
            },
        },
        "status": "proposed",
        "risk_level": "medium",
        "confirmation_policy": "when_required",
        "source": "user",
        "created_at": "2026-07-18T20:00:00+00:00",
        "reason": "The user requested a follow-up task.",
    }


def test_proposal_round_trip_preserves_values() -> None:
    """Serialisation and reconstruction should preserve proposal values."""
    proposal = create_proposal()

    reconstructed = proposal_from_dict(proposal_to_dict(proposal))

    assert reconstructed == proposal


def test_model_convenience_methods_round_trip() -> None:
    """Model methods should use the shared serialisation contract."""
    proposal = create_proposal()

    reconstructed = ActionProposal.from_dict(proposal.to_dict())

    assert reconstructed == proposal


def test_reconstruction_rejects_unknown_fields() -> None:
    """Unknown top-level fields should not be accepted silently."""
    data = proposal_to_dict(create_proposal())
    data["acton"] = "task.create"

    with pytest.raises(
        ActionContractError,
        match="Unknown field 'acton'",
    ):
        proposal_from_dict(data)


def test_reconstruction_rejects_unsupported_schema_version() -> None:
    """Unsupported schema versions should be rejected."""
    data = proposal_to_dict(create_proposal())
    data["schema_version"] = 2

    with pytest.raises(
        ActionContractError,
        match="schema_version must be 1",
    ):
        proposal_from_dict(data)


def test_reconstruction_rejects_invalid_nested_parameters() -> None:
    """Invalid nested parameter data should be rejected."""
    data = proposal_to_dict(create_proposal())
    parameters = data["parameters"]
    assert isinstance(parameters, dict)
    parameters["payload"] = b"bytes"  # type: ignore[assignment]

    with pytest.raises(
        ActionContractError,
        match="unsupported value",
    ):
        proposal_from_dict(data)


def test_serialised_data_does_not_share_mutable_state() -> None:
    """Changing serialised output should not alter the immutable proposal."""
    proposal = create_proposal()
    data = proposal_to_dict(proposal)

    parameters = data["parameters"]
    assert isinstance(parameters, dict)
    parameters["description"] = "Changed"

    assert proposal.parameters["description"] == "Call John"
