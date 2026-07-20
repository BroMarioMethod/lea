"""Deterministic action-proposal state transition policy."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from lea.actions.enums import ActionStatus
from lea.actions.errors import ActionContractError

TRANSITION_TABLE: Mapping[ActionStatus, frozenset[ActionStatus]] = {
    ActionStatus.PROPOSED: frozenset(
        {
            ActionStatus.VALIDATED,
            ActionStatus.REJECTED,
        }
    ),
    ActionStatus.VALIDATED: frozenset(
        {
            ActionStatus.AWAITING_CONFIRMATION,
            ActionStatus.APPROVED,
            ActionStatus.REJECTED,
        }
    ),
    ActionStatus.AWAITING_CONFIRMATION: frozenset(
        {
            ActionStatus.APPROVED,
            ActionStatus.REJECTED,
            ActionStatus.CANCELLED,
        }
    ),
    ActionStatus.APPROVED: frozenset(
        {
            ActionStatus.EXECUTING,
            ActionStatus.CANCELLED,
        }
    ),
    ActionStatus.EXECUTING: frozenset(
        {
            ActionStatus.SUCCEEDED,
            ActionStatus.FAILED,
        }
    ),
    ActionStatus.REJECTED: frozenset(),
    ActionStatus.SUCCEEDED: frozenset(),
    ActionStatus.FAILED: frozenset(),
    ActionStatus.CANCELLED: frozenset(),
}

TERMINAL_STATUSES = frozenset(
    {
        ActionStatus.REJECTED,
        ActionStatus.SUCCEEDED,
        ActionStatus.FAILED,
        ActionStatus.CANCELLED,
    }
)


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def can_transition(
    current: ActionStatus,
    target: ActionStatus,
) -> bool:
    """Return whether the canonical policy permits a transition."""
    return target in TRANSITION_TABLE[current]


@dataclass(frozen=True, slots=True)
class ActionTransition:
    """Immutable record of one successful proposal transition."""

    proposal_id: str
    from_status: ActionStatus
    to_status: ActionStatus
    transitioned_at: datetime
    reason: str | None = None

    def __post_init__(self) -> None:
        """Validate transition record invariants."""
        if (
            self.transitioned_at.tzinfo is None
            or self.transitioned_at.utcoffset() is None
        ):
            raise ActionContractError("transitioned_at must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class TransitionIssue:
    """Immutable description of one rejected transition."""

    code: str
    message: str
    from_status: ActionStatus
    to_status: ActionStatus


@dataclass(frozen=True, slots=True)
class TransitionResult:
    """Immutable result of evaluating a proposal transition."""

    success: bool
    proposal: object
    transition: ActionTransition | None
    issues: tuple[TransitionIssue, ...]

    def __post_init__(self) -> None:
        """Enforce consistency between transition outcome fields."""
        if self.success:
            if self.transition is None:
                raise ActionContractError(
                    "A successful transition result must contain a transition record."
                )

            if self.issues:
                raise ActionContractError(
                    "A successful transition result must not contain issues."
                )

            return

        if self.transition is not None:
            raise ActionContractError(
                "A failed transition result must not contain a transition record."
            )

        if not self.issues:
            raise ActionContractError(
                "A failed transition result must contain at least one issue."
            )
