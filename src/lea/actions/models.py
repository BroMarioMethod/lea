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


@dataclass(frozen=True, slots=True)
class ExecutionError:
    """Immutable description of an action execution failure."""

    code: str
    message: str
    details: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        """Validate and freeze execution-error data."""
        if not self.code.strip():
            raise ActionContractError(
                "Execution error code must be a non-empty string."
            )

        if not self.message.strip():
            raise ActionContractError(
                "Execution error message must be a non-empty string."
            )

        if self.details is not None:
            frozen_details = freeze_parameters(self.details)
            object.__setattr__(self, "details", frozen_details)


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Immutable result of attempting an authorised action."""

    proposal_id: str
    success: bool
    status: ActionStatus
    started_at: datetime
    completed_at: datetime
    output: Mapping[str, object] | None = None
    error: ExecutionError | None = None

    def __post_init__(self) -> None:
        """Validate execution-result consistency."""
        self._validate_proposal_id()
        self._validate_timestamps()
        self._validate_outcome()

        if self.output is not None:
            frozen_output = freeze_parameters(self.output)
            object.__setattr__(self, "output", frozen_output)

    def _validate_proposal_id(self) -> None:
        """Validate the canonical proposal UUID."""
        try:
            parsed_identifier = UUID(self.proposal_id)
        except ValueError as error:
            raise ActionContractError("proposal_id must be a valid UUID.") from error

        if str(parsed_identifier) != self.proposal_id:
            raise ActionContractError(
                "proposal_id must use canonical lower-case UUID format."
            )

    def _validate_timestamps(self) -> None:
        """Validate timezone awareness and execution ordering."""
        for field_name, timestamp in (
            ("started_at", self.started_at),
            ("completed_at", self.completed_at),
        ):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ActionContractError(f"{field_name} must be timezone-aware.")

        if self.completed_at < self.started_at:
            raise ActionContractError("completed_at must not occur before started_at.")

    def _validate_outcome(self) -> None:
        """Validate consistency between success, status and error."""
        if self.success:
            if self.status is not ActionStatus.SUCCEEDED:
                raise ActionContractError(
                    "A successful execution result must use status 'succeeded'."
                )

            if self.error is not None:
                raise ActionContractError(
                    "A successful execution result must not contain an execution error."
                )

            return

        if self.status is not ActionStatus.FAILED:
            raise ActionContractError(
                "A failed execution result must use status 'failed'."
            )

        if self.error is None:
            raise ActionContractError(
                "A failed execution result must contain an execution error."
            )
