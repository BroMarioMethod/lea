"""Immutable data models for the LEA action contract."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from lea.actions.enums import (
    ActionStatus,
    ConfirmationPolicy,
    RiskLevel,
)
from lea.actions.errors import ActionContractError
from lea.actions.values import freeze_parameters

ACTION_NAME_PATTERN = re.compile(r"^[a-z0-9_]+(?:\.[a-z0-9_]+)+$")


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def generate_proposal_id() -> str:
    """Generate a canonical lower-case UUID proposal identifier."""
    return str(uuid4())


@dataclass(frozen=True, slots=True)
class ActionProposal:
    """Immutable description of a requested action."""

    action: str
    parameters: Mapping[str, object]
    source: str
    proposal_id: str = field(default_factory=generate_proposal_id)
    status: ActionStatus = ActionStatus.PROPOSED
    risk_level: RiskLevel = RiskLevel.MEDIUM
    confirmation_policy: ConfirmationPolicy = ConfirmationPolicy.WHEN_REQUIRED
    created_at: datetime = field(default_factory=utc_now)
    reason: str | None = None

    def __post_init__(self) -> None:
        """Validate and normalise the proposal after construction."""
        self._validate_proposal_id()
        self._validate_action()
        self._validate_source()
        self._validate_created_at()

        frozen_parameters = freeze_parameters(self.parameters)
        object.__setattr__(self, "parameters", frozen_parameters)

    def _validate_proposal_id(self) -> None:
        """Validate the canonical UUID proposal identifier."""
        try:
            parsed_identifier = UUID(self.proposal_id)
        except ValueError as error:
            raise ActionContractError("proposal_id must be a valid UUID.") from error

        if str(parsed_identifier) != self.proposal_id:
            raise ActionContractError(
                "proposal_id must use canonical lower-case UUID format."
            )

    def _validate_action(self) -> None:
        """Validate the namespaced action identifier."""
        if ACTION_NAME_PATTERN.fullmatch(self.action) is None:
            raise ActionContractError(
                "action must use a lower-case namespaced identifier "
                "such as 'task.create'."
            )

    def _validate_source(self) -> None:
        """Validate the proposal source."""
        if not self.source.strip():
            raise ActionContractError("source must be a non-empty string.")

    def _validate_created_at(self) -> None:
        """Validate the timezone-aware creation timestamp."""
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ActionContractError("created_at must be timezone-aware.")
