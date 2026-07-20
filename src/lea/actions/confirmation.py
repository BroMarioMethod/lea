"""Deterministic confirmation policy for LEA action proposals."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from lea.actions.enums import (
    ActionStatus,
    ConfirmationPolicy,
    RiskLevel,
)
from lea.actions.errors import ActionContractError
from lea.actions.models import ActionProposal


class ConfirmationRequirement(StrEnum):
    """Whether explicit human confirmation is required."""

    NOT_REQUIRED = "not_required"
    REQUIRED = "required"


class ConfirmationDecision(StrEnum):
    """Human decision for a proposal awaiting confirmation."""

    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


CONFIRMATION_MATRIX: Mapping[
    RiskLevel,
    Mapping[ConfirmationPolicy, ConfirmationRequirement],
] = {
    RiskLevel.LOW: {
        ConfirmationPolicy.NEVER: ConfirmationRequirement.NOT_REQUIRED,
        ConfirmationPolicy.WHEN_REQUIRED: ConfirmationRequirement.NOT_REQUIRED,
        ConfirmationPolicy.ALWAYS: ConfirmationRequirement.REQUIRED,
    },
    RiskLevel.MEDIUM: {
        ConfirmationPolicy.NEVER: ConfirmationRequirement.NOT_REQUIRED,
        ConfirmationPolicy.WHEN_REQUIRED: ConfirmationRequirement.REQUIRED,
        ConfirmationPolicy.ALWAYS: ConfirmationRequirement.REQUIRED,
    },
    RiskLevel.HIGH: {
        ConfirmationPolicy.NEVER: ConfirmationRequirement.REQUIRED,
        ConfirmationPolicy.WHEN_REQUIRED: ConfirmationRequirement.REQUIRED,
        ConfirmationPolicy.ALWAYS: ConfirmationRequirement.REQUIRED,
    },
    RiskLevel.CRITICAL: {
        ConfirmationPolicy.NEVER: ConfirmationRequirement.REQUIRED,
        ConfirmationPolicy.WHEN_REQUIRED: ConfirmationRequirement.REQUIRED,
        ConfirmationPolicy.ALWAYS: ConfirmationRequirement.REQUIRED,
    },
}


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ConfirmationEvaluation:
    """Immutable record of a confirmation-policy evaluation."""

    proposal_id: str
    risk_level: RiskLevel
    confirmation_policy: ConfirmationPolicy
    requirement: ConfirmationRequirement
    evaluated_at: datetime
    reason_code: str
    explanation: str

    def __post_init__(self) -> None:
        """Validate evaluation record invariants."""
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ActionContractError("evaluated_at must be timezone-aware.")

        if not self.reason_code.strip():
            raise ActionContractError("reason_code must be a non-empty string.")

        if not self.explanation.strip():
            raise ActionContractError("explanation must be a non-empty string.")


@dataclass(frozen=True, slots=True)
class ConfirmationIssue:
    """Immutable description of a confirmation-policy problem."""

    code: str
    message: str
    proposal_id: str
    field: str | None = None


@dataclass(frozen=True, slots=True)
class ConfirmationEvaluationResult:
    """Immutable result of evaluating confirmation requirements."""

    success: bool
    evaluation: ConfirmationEvaluation | None
    issues: tuple[ConfirmationIssue, ...]

    def __post_init__(self) -> None:
        """Enforce consistency between result fields."""
        if self.success:
            if self.evaluation is None:
                raise ActionContractError(
                    "A successful confirmation evaluation result must "
                    "contain an evaluation record."
                )

            if self.issues:
                raise ActionContractError(
                    "A successful confirmation evaluation result must "
                    "not contain issues."
                )

            return

        if self.evaluation is not None:
            raise ActionContractError(
                "A failed confirmation evaluation result must not "
                "contain an evaluation record."
            )

        if not self.issues:
            raise ActionContractError(
                "A failed confirmation evaluation result must contain "
                "at least one issue."
            )


def evaluate_confirmation(
    proposal: ActionProposal,
    *,
    evaluated_at: datetime | None = None,
) -> ConfirmationEvaluationResult:
    """Evaluate whether a validated proposal requires confirmation."""
    if proposal.status is not ActionStatus.VALIDATED:
        issue = ConfirmationIssue(
            code="invalid_proposal_status",
            message=(
                "Confirmation policy may only be evaluated for validated proposals."
            ),
            proposal_id=proposal.proposal_id,
            field="status",
        )

        return ConfirmationEvaluationResult(
            success=False,
            evaluation=None,
            issues=(issue,),
        )

    requirement = CONFIRMATION_MATRIX[proposal.risk_level][proposal.confirmation_policy]

    reason_code, explanation = _describe_requirement(
        proposal.risk_level,
        proposal.confirmation_policy,
        requirement,
    )

    timestamp = evaluated_at if evaluated_at is not None else utc_now()

    evaluation = ConfirmationEvaluation(
        proposal_id=proposal.proposal_id,
        risk_level=proposal.risk_level,
        confirmation_policy=proposal.confirmation_policy,
        requirement=requirement,
        evaluated_at=timestamp,
        reason_code=reason_code,
        explanation=explanation,
    )

    return ConfirmationEvaluationResult(
        success=True,
        evaluation=evaluation,
        issues=(),
    )


def _describe_requirement(
    risk_level: RiskLevel,
    confirmation_policy: ConfirmationPolicy,
    requirement: ConfirmationRequirement,
) -> tuple[str, str]:
    """Return the canonical reason for a confirmation requirement."""
    if risk_level is RiskLevel.CRITICAL:
        return (
            "critical_risk_override",
            "Critical-risk proposals always require human confirmation.",
        )

    if risk_level is RiskLevel.HIGH:
        return (
            "high_risk_override",
            "High-risk proposals always require human confirmation.",
        )

    if confirmation_policy is ConfirmationPolicy.ALWAYS:
        return (
            "policy_always",
            "The proposal confirmation policy always requires confirmation.",
        )

    if risk_level is RiskLevel.LOW:
        return (
            "low_risk_not_required",
            "Low-risk proposals do not require confirmation under this policy.",
        )

    if confirmation_policy is ConfirmationPolicy.NEVER:
        return (
            "medium_risk_never",
            "Medium-risk confirmation is bypassed by the never policy.",
        )

    if requirement is ConfirmationRequirement.REQUIRED:
        return (
            "medium_risk_required",
            "Medium-risk proposals require confirmation under this policy.",
        )

    raise ActionContractError("Unable to determine the confirmation-policy reason.")
