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
from lea.actions.transitions import ActionTransition, transition_proposal


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


DECISION_TARGET_STATUSES: Mapping[
    ConfirmationDecision,
    ActionStatus,
] = {
    ConfirmationDecision.APPROVED: ActionStatus.APPROVED,
    ConfirmationDecision.REJECTED: ActionStatus.REJECTED,
    ConfirmationDecision.CANCELLED: ActionStatus.CANCELLED,
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
class ConfirmationRecord:
    """Immutable record of a human confirmation decision."""

    proposal_id: str
    decision: ConfirmationDecision
    actor: str
    decided_at: datetime
    reason: str | None = None

    def __post_init__(self) -> None:
        """Validate confirmation-record invariants."""
        if not self.proposal_id.strip():
            raise ActionContractError("proposal_id must be a non-empty string.")

        if not self.actor.strip():
            raise ActionContractError("actor must be a non-empty string.")

        if self.decided_at.tzinfo is None or self.decided_at.utcoffset() is None:
            raise ActionContractError("decided_at must be timezone-aware.")

        if self.reason is not None and not self.reason.strip():
            raise ActionContractError(
                "reason must be a non-empty string when provided."
            )


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


@dataclass(frozen=True, slots=True)
class ConfirmationRecordResult:
    """Immutable result of recording a human confirmation decision."""

    success: bool
    record: ConfirmationRecord | None
    issues: tuple[ConfirmationIssue, ...]

    def __post_init__(self) -> None:
        """Enforce consistency between result fields."""
        if self.success:
            if self.record is None:
                raise ActionContractError(
                    "A successful confirmation record result must "
                    "contain a confirmation record."
                )

            if self.issues:
                raise ActionContractError(
                    "A successful confirmation record result must not contain issues."
                )

            return

        if self.record is not None:
            raise ActionContractError(
                "A failed confirmation record result must not contain "
                "a confirmation record."
            )

        if not self.issues:
            raise ActionContractError(
                "A failed confirmation record result must contain at least one issue."
            )


@dataclass(frozen=True, slots=True)
class ConfirmationPolicyApplicationResult:
    """Result of applying confirmation policy to a validated proposal."""

    success: bool
    proposal: ActionProposal
    evaluation: ConfirmationEvaluation | None
    transition: ActionTransition | None
    issues: tuple[ConfirmationIssue, ...]

    def __post_init__(self) -> None:
        """Enforce consistency between application-result fields."""
        if self.success:
            if self.evaluation is None:
                raise ActionContractError(
                    "A successful confirmation-policy application must "
                    "contain an evaluation record."
                )

            if self.transition is None:
                raise ActionContractError(
                    "A successful confirmation-policy application must "
                    "contain a transition record."
                )

            if self.issues:
                raise ActionContractError(
                    "A successful confirmation-policy application must "
                    "not contain issues."
                )

            return

        if self.transition is not None:
            raise ActionContractError(
                "A failed confirmation-policy application must not "
                "contain a transition record."
            )

        if not self.issues:
            raise ActionContractError(
                "A failed confirmation-policy application must contain "
                "at least one issue."
            )


@dataclass(frozen=True, slots=True)
class ConfirmationDecisionApplicationResult:
    """Result of applying a human confirmation decision."""

    success: bool
    proposal: ActionProposal
    record: ConfirmationRecord | None
    transition: ActionTransition | None
    issues: tuple[ConfirmationIssue, ...]

    def __post_init__(self) -> None:
        """Enforce consistency between decision-application fields."""
        if self.success:
            if self.record is None:
                raise ActionContractError(
                    "A successful confirmation-decision application must "
                    "contain a confirmation record."
                )

            if self.transition is None:
                raise ActionContractError(
                    "A successful confirmation-decision application must "
                    "contain a transition record."
                )

            if self.issues:
                raise ActionContractError(
                    "A successful confirmation-decision application must "
                    "not contain issues."
                )

            return

        if self.record is not None:
            raise ActionContractError(
                "A failed confirmation-decision application must not "
                "contain a confirmation record."
            )

        if self.transition is not None:
            raise ActionContractError(
                "A failed confirmation-decision application must not "
                "contain a transition record."
            )

        if not self.issues:
            raise ActionContractError(
                "A failed confirmation-decision application must contain "
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


def record_confirmation(
    proposal: ActionProposal,
    decision: ConfirmationDecision,
    actor: str,
    *,
    reason: str | None = None,
    decided_at: datetime | None = None,
) -> ConfirmationRecordResult:
    """Record a human decision for a proposal awaiting confirmation."""
    issues: list[ConfirmationIssue] = []

    if proposal.status is not ActionStatus.AWAITING_CONFIRMATION:
        issues.append(
            ConfirmationIssue(
                code="invalid_proposal_status",
                message=(
                    "A human confirmation decision may only be recorded "
                    "for proposals awaiting confirmation."
                ),
                proposal_id=proposal.proposal_id,
                field="status",
            )
        )

    if not actor.strip():
        issues.append(
            ConfirmationIssue(
                code="invalid_actor",
                message="The confirmation actor must be a non-empty string.",
                proposal_id=proposal.proposal_id,
                field="actor",
            )
        )

    if reason is not None and not reason.strip():
        issues.append(
            ConfirmationIssue(
                code="invalid_reason",
                message=(
                    "The confirmation reason must be a non-empty string when provided."
                ),
                proposal_id=proposal.proposal_id,
                field="reason",
            )
        )

    timestamp = decided_at if decided_at is not None else utc_now()

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        issues.append(
            ConfirmationIssue(
                code="invalid_timestamp",
                message=("The confirmation decision timestamp must be timezone-aware."),
                proposal_id=proposal.proposal_id,
                field="decided_at",
            )
        )

    if issues:
        return ConfirmationRecordResult(
            success=False,
            record=None,
            issues=tuple(issues),
        )

    record = ConfirmationRecord(
        proposal_id=proposal.proposal_id,
        decision=decision,
        actor=actor,
        decided_at=timestamp,
        reason=reason,
    )

    return ConfirmationRecordResult(
        success=True,
        record=record,
        issues=(),
    )


def apply_confirmation_policy(
    proposal: ActionProposal,
    *,
    applied_at: datetime | None = None,
) -> ConfirmationPolicyApplicationResult:
    """Evaluate and apply confirmation policy without executing an action."""
    evaluation_result = evaluate_confirmation(
        proposal,
        evaluated_at=applied_at,
    )

    if not evaluation_result.success:
        return ConfirmationPolicyApplicationResult(
            success=False,
            proposal=proposal,
            evaluation=None,
            transition=None,
            issues=evaluation_result.issues,
        )

    evaluation = evaluation_result.evaluation

    if evaluation is None:
        raise ActionContractError(
            "Successful confirmation evaluation did not contain an evaluation record."
        )

    if evaluation.requirement is ConfirmationRequirement.REQUIRED:
        target_status = ActionStatus.AWAITING_CONFIRMATION
        transition_reason = evaluation.explanation
    else:
        target_status = ActionStatus.APPROVED
        transition_reason = evaluation.explanation

    transition_result = transition_proposal(
        proposal,
        target_status,
        reason=transition_reason,
        transitioned_at=evaluation.evaluated_at,
    )

    if not transition_result.success:
        issues = tuple(
            ConfirmationIssue(
                code=issue.code,
                message=issue.message,
                proposal_id=proposal.proposal_id,
                field="status",
            )
            for issue in transition_result.issues
        )

        return ConfirmationPolicyApplicationResult(
            success=False,
            proposal=proposal,
            evaluation=evaluation,
            transition=None,
            issues=issues,
        )

    if transition_result.transition is None:
        raise ActionContractError(
            "Successful proposal transition did not contain a transition record."
        )

    return ConfirmationPolicyApplicationResult(
        success=True,
        proposal=transition_result.proposal,
        evaluation=evaluation,
        transition=transition_result.transition,
        issues=(),
    )


def apply_confirmation_decision(
    proposal: ActionProposal,
    decision: ConfirmationDecision,
    actor: str,
    *,
    reason: str | None = None,
    decided_at: datetime | None = None,
) -> ConfirmationDecisionApplicationResult:
    """Record and apply a human decision without executing the action."""
    record_result = record_confirmation(
        proposal,
        decision,
        actor,
        reason=reason,
        decided_at=decided_at,
    )

    if not record_result.success:
        return ConfirmationDecisionApplicationResult(
            success=False,
            proposal=proposal,
            record=None,
            transition=None,
            issues=record_result.issues,
        )

    record = record_result.record

    if record is None:
        raise ActionContractError(
            "Successful confirmation recording did not contain a confirmation record."
        )

    target_status = DECISION_TARGET_STATUSES[decision]

    transition_result = transition_proposal(
        proposal,
        target_status,
        reason=record.reason,
        transitioned_at=record.decided_at,
    )

    if not transition_result.success:
        issues = tuple(
            ConfirmationIssue(
                code=issue.code,
                message=issue.message,
                proposal_id=proposal.proposal_id,
                field="status",
            )
            for issue in transition_result.issues
        )

        return ConfirmationDecisionApplicationResult(
            success=False,
            proposal=proposal,
            record=None,
            transition=None,
            issues=issues,
        )

    if transition_result.transition is None:
        raise ActionContractError(
            "Successful proposal transition did not contain a transition record."
        )

    return ConfirmationDecisionApplicationResult(
        success=True,
        proposal=transition_result.proposal,
        record=record,
        transition=transition_result.transition,
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
