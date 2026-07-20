"""Deterministic action-handler registration for LEA."""

from collections.abc import Mapping
from typing import Protocol

from lea.actions.errors import ActionContractError
from lea.actions.models import ACTION_NAME_PATTERN, ActionProposal


class ActionHandler(Protocol):
    """Callable contract for one explicitly registered action handler."""

    def __call__(
        self,
        proposal: ActionProposal,
    ) -> Mapping[str, object] | None:
        """Handle one executing action proposal."""
        ...


class ActionHandlerRegistry:
    """Explicit deterministic mapping of action names to handlers."""

    __slots__ = ("_handlers",)

    def __init__(self) -> None:
        """Create an empty action-handler registry."""
        self._handlers: dict[str, ActionHandler] = {}

    def register(
        self,
        action: str,
        handler: ActionHandler,
    ) -> None:
        """Register exactly one handler for a canonical action name."""
        if ACTION_NAME_PATTERN.fullmatch(action) is None:
            raise ActionContractError(
                "action must use a lower-case namespaced identifier "
                "such as 'task.create'."
            )

        if not callable(handler):
            raise ActionContractError("handler must be callable.")

        if action in self._handlers:
            raise ActionContractError(
                f"A handler is already registered for action '{action}'."
            )

        self._handlers[action] = handler

    def get(
        self,
        action: str,
    ) -> ActionHandler | None:
        """Return the exactly registered handler for an action."""
        return self._handlers.get(action)

    def __contains__(self, action: object) -> bool:
        """Return whether an exact action name is registered."""
        return action in self._handlers

    def __len__(self) -> int:
        """Return the number of registered handlers."""
        return len(self._handlers)
