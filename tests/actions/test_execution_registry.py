"""Tests for explicit deterministic action-handler registration."""

from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from lea.actions import (
    ActionContractError,
    ActionHandlerRegistry,
    ActionProposal,
    ActionStatus,
)

PROPOSAL_ID = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"


def create_executing_proposal() -> ActionProposal:
    """Create a deterministic proposal for registry handler tests."""
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={"description": "Call John"},
        source="user",
        status=ActionStatus.EXECUTING,
        created_at=datetime(2026, 7, 20, 17, 0, tzinfo=UTC),
    )


def example_handler(
    proposal: ActionProposal,
) -> Mapping[str, object]:
    """Return deterministic output for a test proposal."""
    return {
        "proposal_id": proposal.proposal_id,
        "handled": True,
    }


def test_registry_starts_empty() -> None:
    """A new handler registry should contain no registrations."""
    registry = ActionHandlerRegistry()

    assert len(registry) == 0
    assert "task.create" not in registry


def test_register_and_get_handler() -> None:
    """A registered handler should be returned by exact lookup."""
    registry = ActionHandlerRegistry()

    registry.register("task.create", example_handler)

    assert len(registry) == 1
    assert "task.create" in registry
    assert registry.get("task.create") is example_handler


def test_registered_handler_can_be_called() -> None:
    """Registry lookup should preserve the original callable."""
    registry = ActionHandlerRegistry()
    proposal = create_executing_proposal()

    registry.register("task.create", example_handler)
    handler = registry.get("task.create")

    assert handler is not None
    assert handler(proposal) == {
        "proposal_id": PROPOSAL_ID,
        "handled": True,
    }


def test_unknown_action_returns_none() -> None:
    """Unknown action names should not resolve to another handler."""
    registry = ActionHandlerRegistry()

    registry.register("task.create", example_handler)

    assert registry.get("task.delete") is None
    assert "task.delete" not in registry


def test_lookup_uses_exact_action_name() -> None:
    """Lookup should not perform aliases or partial matching."""
    registry = ActionHandlerRegistry()

    registry.register("task.create", example_handler)

    assert registry.get("task") is None
    assert registry.get("create") is None
    assert registry.get("Task.Create") is None
    assert registry.get("task.create.extra") is None


def test_duplicate_registration_is_rejected() -> None:
    """An action name should map to exactly one handler."""
    registry = ActionHandlerRegistry()

    registry.register("task.create", example_handler)

    with pytest.raises(
        ActionContractError,
        match="already registered",
    ):
        registry.register("task.create", example_handler)

    assert len(registry) == 1
    assert registry.get("task.create") is example_handler


@pytest.mark.parametrize(
    "action",
    [
        "",
        "task",
        "Task.create",
        "task-create",
        "task create",
        ".task.create",
        "task.create.",
        "task..create",
    ],
)
def test_invalid_action_names_are_rejected(action: str) -> None:
    """Registrations should use canonical namespaced action names."""
    registry = ActionHandlerRegistry()

    with pytest.raises(
        ActionContractError,
        match="lower-case namespaced identifier",
    ):
        registry.register(action, example_handler)

    assert len(registry) == 0


def test_non_callable_handler_is_rejected() -> None:
    """Registry entries must be callable action handlers."""
    registry = ActionHandlerRegistry()

    with pytest.raises(
        ActionContractError,
        match="handler must be callable",
    ):
        registry.register(
            "task.create",
            object(),  # type: ignore[arg-type]
        )

    assert len(registry) == 0


def test_failed_duplicate_registration_preserves_original_handler() -> None:
    """Rejected replacement should not alter the existing mapping."""

    def replacement_handler(
        proposal: ActionProposal,
    ) -> Mapping[str, object] | None:
        return None

    registry = ActionHandlerRegistry()
    registry.register("task.create", example_handler)

    with pytest.raises(ActionContractError):
        registry.register("task.create", replacement_handler)

    assert registry.get("task.create") is example_handler
