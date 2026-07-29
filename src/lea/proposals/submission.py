"""Reusable application service for persistent proposal submission."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from lea.actions import ActionProposal
from lea.orchestration import (
    OrchestrationOutcome,
    SubmissionResult,
)
from lea.proposals.contracts import ProposalWriteResult


class _SubmissionOrchestrator(Protocol):
    """Boundary required to submit one action proposal."""

    def submit(self, proposal: ActionProposal) -> SubmissionResult:
        """Validate, apply policy and persist audit events."""
        ...


class _SubmissionRepository(Protocol):
    """Boundary required to create one canonical proposal document."""

    def create(self, proposal: ActionProposal) -> ProposalWriteResult:
        """Persist one proposal without overwriting."""
        ...


@dataclass(frozen=True, slots=True)
class ProposalSubmissionIssue:
    """One deterministic proposal-submission problem."""

    code: str
    message: str
    field: str | None = None

    def __post_init__(self) -> None:
        """Validate safe issue fields."""
        if not self.code.strip():
            raise ValueError("code must be non-empty.")

        if not self.message.strip():
            raise ValueError("message must be non-empty.")

        if self.field is not None and not self.field.strip():
            raise ValueError("field must be non-empty when provided.")


@dataclass(frozen=True, slots=True)
class ProposalSubmissionResult:
    """Result of orchestration followed by canonical persistence."""

    success: bool
    proposal: ActionProposal | None
    submission: SubmissionResult | None
    write: ProposalWriteResult | None
    audit_persisted: bool
    proposal_persisted: bool
    persisted_audit_event_count: int
    issues: tuple[ProposalSubmissionIssue, ...]

    def __post_init__(self) -> None:
        """Enforce result consistency."""
        if self.persisted_audit_event_count < 0:
            raise ValueError("persisted_audit_event_count must not be negative.")

        if self.success:
            if self.proposal is None:
                raise ValueError("A successful submission must contain a proposal.")

            if self.submission is None:
                raise ValueError(
                    "A successful submission must contain orchestration output."
                )

            if self.write is None or not self.write.success:
                raise ValueError(
                    "A successful submission must contain a successful write."
                )

            if not self.audit_persisted or not self.proposal_persisted:
                raise ValueError(
                    "A successful submission must persist audit and proposal data."
                )

            if self.issues:
                raise ValueError("A successful submission must not contain issues.")
            return

        if not self.issues:
            raise ValueError("A failed submission must contain at least one issue.")

        if self.proposal_persisted:
            raise ValueError("A failed submission must not claim proposal persistence.")


class ProposalSubmissionService:
    """Submit one proposal and persist its resulting canonical state."""

    def __init__(
        self,
        orchestrator: _SubmissionOrchestrator,
        repository: _SubmissionRepository,
    ) -> None:
        """Construct the service from explicit deterministic boundaries."""
        self._orchestrator = orchestrator
        self._repository = repository

    def submit(
        self,
        proposal: ActionProposal,
    ) -> ProposalSubmissionResult:
        """Submit without executing and persist an accepted workflow state."""
        try:
            submission = self._orchestrator.submit(proposal)
        except Exception:
            return _failure(
                proposal=proposal,
                code="proposal_submission_orchestration_failed",
                message="The proposal submission workflow could not complete.",
            )

        event_count = len(submission.persisted_events)

        if submission.outcome not in {
            OrchestrationOutcome.APPROVED,
            OrchestrationOutcome.CONFIRMATION_REQUIRED,
        }:
            issue = submission.issue
            return _failure(
                proposal=submission.proposal,
                submission=submission,
                audit_persisted=False,
                persisted_audit_event_count=event_count,
                code=(
                    issue.code if issue is not None else "proposal_submission_rejected"
                ),
                message=(
                    issue.message
                    if issue is not None
                    else "The proposal submission was rejected."
                ),
            )

        try:
            write = self._repository.create(submission.proposal)
        except Exception:
            return _failure(
                proposal=submission.proposal,
                submission=submission,
                audit_persisted=True,
                persisted_audit_event_count=event_count,
                code="proposal_submission_persistence_failed",
                message=(
                    "Submission audit events were persisted, but the proposal "
                    "document could not be created."
                ),
            )

        if not write.success:
            repository_issues = tuple(
                ProposalSubmissionIssue(
                    code=issue.code,
                    message=issue.message,
                    field=issue.field,
                )
                for issue in write.issues
            )
            return ProposalSubmissionResult(
                success=False,
                proposal=submission.proposal,
                submission=submission,
                write=write,
                audit_persisted=True,
                proposal_persisted=False,
                persisted_audit_event_count=event_count,
                issues=(
                    ProposalSubmissionIssue(
                        code="proposal_submission_partial_persistence",
                        message=(
                            "Submission audit events were persisted, but the "
                            "proposal document could not be created."
                        ),
                    ),
                    *repository_issues,
                ),
            )

        return ProposalSubmissionResult(
            success=True,
            proposal=submission.proposal,
            submission=submission,
            write=write,
            audit_persisted=True,
            proposal_persisted=True,
            persisted_audit_event_count=event_count,
            issues=(),
        )


def _failure(
    *,
    proposal: ActionProposal | None,
    code: str,
    message: str,
    submission: SubmissionResult | None = None,
    audit_persisted: bool = False,
    persisted_audit_event_count: int = 0,
) -> ProposalSubmissionResult:
    """Return one stable failed submission result."""
    return ProposalSubmissionResult(
        success=False,
        proposal=proposal,
        submission=submission,
        write=None,
        audit_persisted=audit_persisted,
        proposal_persisted=False,
        persisted_audit_event_count=persisted_audit_event_count,
        issues=(
            ProposalSubmissionIssue(
                code=code,
                message=message,
            ),
        ),
    )
