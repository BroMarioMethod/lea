"""Immutable public contracts for deterministic action orchestration."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from lea.actions.confirmation import (
    ConfirmationDecisionApplicationResult,
    ConfirmationPolicyApplicationResult,
)
from lea.actions.execution import ActionExecutionResult
from lea.actions.models import ActionProposal
from lea.actions.validation import ValidationResult
from lea.audit.events import AuditEvent


class OrchestrationOutcome(StrEnum):
    """Stable outcome of one orchestration operation."""

    SUBMITTED = "submitted"
    VALIDATION_FAILED = "validation_failed"
    CONFIRMATION_REQUIRED = "confirmation_required"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXECUTION_SUCCEEDED = "execution_succeeded"
    EXECUTION_FAILED = "execution_failed"
    AUDIT_FAILED = "audit_failed"
    INVALID_OPERATION = "invalid_operation"


@dataclass(frozen=True, slots=True)
class OrchestrationIssue:
    """Immutable description of an orchestration-layer failure."""

    code: str
    message: str
    operation: str
    proposal_id: str

    def __post_init__(self) -> None:
        """Validate issue fields."""
        if not self.code.strip():
            raise ValueError("Orchestration issue code must be a non-empty string.")

        if not self.message.strip():
            raise ValueError("Orchestration issue message must be a non-empty string.")

        if not self.operation.strip():
            raise ValueError(
                "Orchestration issue operation must be a non-empty string."
            )

        if not self.proposal_id.strip():
            raise ValueError(
                "Orchestration issue proposal_id must be a non-empty string."
            )


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    """Immutable result of submitting one action proposal."""

    outcome: OrchestrationOutcome
    proposal: ActionProposal
    validation: ValidationResult
    confirmation_policy: ConfirmationPolicyApplicationResult | None
    persisted_events: tuple[AuditEvent, ...]
    issue: OrchestrationIssue | None = None

    def __post_init__(self) -> None:
        """Validate submission-result consistency."""
        allowed_outcomes = frozenset(
            {
                OrchestrationOutcome.SUBMITTED,
                OrchestrationOutcome.VALIDATION_FAILED,
                OrchestrationOutcome.CONFIRMATION_REQUIRED,
                OrchestrationOutcome.APPROVED,
                OrchestrationOutcome.AUDIT_FAILED,
                OrchestrationOutcome.INVALID_OPERATION,
            }
        )

        if self.outcome not in allowed_outcomes:
            raise ValueError("SubmissionResult contains an unsupported outcome.")

        _validate_issue_consistency(
            outcome=self.outcome,
            issue=self.issue,
        )

        if not self.validation.valid and self.confirmation_policy is not None:
            raise ValueError(
                "A validation failure must not contain a confirmation-policy "
                "application result."
            )


@dataclass(frozen=True, slots=True)
class ConfirmationOrchestrationResult:
    """Immutable result of applying one human confirmation decision."""

    outcome: OrchestrationOutcome
    proposal: ActionProposal
    decision_application: ConfirmationDecisionApplicationResult | None
    persisted_events: tuple[AuditEvent, ...]
    issue: OrchestrationIssue | None = None

    def __post_init__(self) -> None:
        """Validate confirmation-result consistency."""
        allowed_outcomes = frozenset(
            {
                OrchestrationOutcome.APPROVED,
                OrchestrationOutcome.REJECTED,
                OrchestrationOutcome.CANCELLED,
                OrchestrationOutcome.AUDIT_FAILED,
                OrchestrationOutcome.INVALID_OPERATION,
            }
        )

        if self.outcome not in allowed_outcomes:
            raise ValueError(
                "ConfirmationOrchestrationResult contains an unsupported outcome."
            )

        _validate_issue_consistency(
            outcome=self.outcome,
            issue=self.issue,
        )


@dataclass(frozen=True, slots=True)
class ExecutionOrchestrationResult:
    """Immutable result of orchestrating one action execution."""

    outcome: OrchestrationOutcome
    proposal: ActionProposal
    execution: ActionExecutionResult | None
    persisted_events: tuple[AuditEvent, ...]
    issue: OrchestrationIssue | None = None

    def __post_init__(self) -> None:
        """Validate execution-result consistency."""
        allowed_outcomes = frozenset(
            {
                OrchestrationOutcome.EXECUTION_SUCCEEDED,
                OrchestrationOutcome.EXECUTION_FAILED,
                OrchestrationOutcome.AUDIT_FAILED,
                OrchestrationOutcome.INVALID_OPERATION,
            }
        )

        if self.outcome not in allowed_outcomes:
            raise ValueError(
                "ExecutionOrchestrationResult contains an unsupported outcome."
            )

        _validate_issue_consistency(
            outcome=self.outcome,
            issue=self.issue,
        )


class AuditSink(Protocol):
    """Minimum append-only audit dependency required by orchestration."""

    def append(
        self,
        event: AuditEvent,
    ) -> object:
        """Persist one immutable audit event."""
        ...


class UtcClock(Protocol):
    """Callable source of timezone-aware UTC timestamps."""

    def __call__(self) -> object:
        """Return one timestamp.

        Concrete orchestration code validates that the value is a
        timezone-aware UTC datetime.
        """
        ...


class AuditEventIdSource(Protocol):
    """Callable source of canonical audit-event UUID strings."""

    def __call__(self) -> object:
        """Return one audit-event identifier.

        Concrete orchestration code validates the returned value before use.
        """
        ...


def _validate_issue_consistency(
    *,
    outcome: OrchestrationOutcome,
    issue: OrchestrationIssue | None,
) -> None:
    """Validate the relationship between outcome and orchestration issue."""
    failure_outcomes = frozenset(
        {
            OrchestrationOutcome.AUDIT_FAILED,
            OrchestrationOutcome.INVALID_OPERATION,
        }
    )

    if outcome in failure_outcomes:
        if issue is None:
            raise ValueError("An orchestration failure outcome must contain an issue.")

        return

    if issue is not None:
        raise ValueError(
            "A non-failure orchestration outcome must not contain an issue."
        )
