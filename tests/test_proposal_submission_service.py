"""Tests for the reusable persistent proposal-submission service."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from lea.actions import (
    ActionHandlerRegistry,
    ActionProposal,
    ActionStatus,
    ConfirmationPolicy,
    RiskLevel,
)
from lea.audit import AuditEvent, JsonlAuditStore
from lea.orchestration import ActionOrchestrator
from lea.proposals import (
    MarkdownProposalRepository,
    ProposalSubmissionService,
)

PROPOSAL_ID = "11111111-1111-4111-8111-111111111111"
EVENT_IDS = (
    "21111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
    "23333333-3333-4333-8333-333333333333",
    "24444444-4444-4444-8444-444444444444",
)
TIMESTAMPS = (
    datetime(2026, 7, 29, 7, 1, tzinfo=UTC),
    datetime(2026, 7, 29, 7, 2, tzinfo=UTC),
    datetime(2026, 7, 29, 7, 3, tzinfo=UTC),
)


class DatetimeSequence:
    """Return deterministic UTC timestamps."""

    def __init__(self) -> None:
        self._values = iter(TIMESTAMPS)

    def __call__(self) -> datetime:
        return next(self._values)


class IdentifierSequence:
    """Return deterministic event identifiers."""

    def __init__(self) -> None:
        self._values = iter(EVENT_IDS)

    def __call__(self) -> str:
        return next(self._values)


class FailingAuditSink:
    """Reject the first audit append."""

    def append(self, _event: AuditEvent) -> None:
        raise OSError("Simulated audit failure.")


def _proposal(
    *,
    risk: RiskLevel = RiskLevel.LOW,
    policy: ConfirmationPolicy = ConfirmationPolicy.WHEN_REQUIRED,
) -> ActionProposal:
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={"description": "Telegram submission test"},
        source="telegram:owner",
        risk_level=risk,
        confirmation_policy=policy,
        created_at=datetime(2026, 7, 29, 7, 0, tzinfo=UTC),
        reason="Create one test task through Telegram.",
    )


def _service(
    tmp_path: Path,
    *,
    registry: ActionHandlerRegistry | None = None,
    repository_root: Path | None = None,
) -> ProposalSubmissionService:
    proposal_root = repository_root or (tmp_path / "proposals")
    proposal_root.mkdir(parents=True, exist_ok=True)
    audit_path = tmp_path / "audit" / "actions.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)

    orchestrator = ActionOrchestrator(
        registry or ActionHandlerRegistry(),
        JsonlAuditStore(audit_path),
        DatetimeSequence(),
        IdentifierSequence(),
    )
    return ProposalSubmissionService(
        orchestrator,
        MarkdownProposalRepository(proposal_root),
    )


def test_approved_submission_persists_without_executing(
    tmp_path: Path,
) -> None:
    """Low-risk submission should persist but never invoke its handler."""
    called = False

    def handler(proposal: ActionProposal) -> dict[str, object]:
        nonlocal called
        del proposal
        called = True
        return {"unexpected": True}

    registry = ActionHandlerRegistry()
    registry.register("task.create", handler)
    root = tmp_path / "proposals"

    result = _service(
        tmp_path,
        registry=registry,
        repository_root=root,
    ).submit(_proposal())

    assert result.success is True
    assert result.proposal is not None
    assert result.proposal.status is ActionStatus.APPROVED
    assert result.audit_persisted is True
    assert result.proposal_persisted is True
    assert result.persisted_audit_event_count == 4
    assert called is False

    stored = MarkdownProposalRepository(root).read(PROPOSAL_ID)
    assert stored.success is True
    assert stored.proposal == result.proposal


def test_confirmation_required_submission_is_persisted(
    tmp_path: Path,
) -> None:
    """Medium-risk submission should stop awaiting confirmation."""
    result = _service(tmp_path).submit(_proposal(risk=RiskLevel.MEDIUM))

    assert result.success is True
    assert result.proposal is not None
    assert result.proposal.status is ActionStatus.AWAITING_CONFIRMATION
    assert result.proposal_persisted is True


def test_audit_failure_prevents_proposal_persistence(
    tmp_path: Path,
) -> None:
    """An incomplete audit workflow must not publish a proposal document."""
    root = tmp_path / "proposals"
    root.mkdir()
    orchestrator = ActionOrchestrator(
        ActionHandlerRegistry(),
        FailingAuditSink(),
        DatetimeSequence(),
        IdentifierSequence(),
    )
    service = ProposalSubmissionService(
        orchestrator,
        MarkdownProposalRepository(root),
    )

    result = service.submit(_proposal())

    assert result.success is False
    assert result.audit_persisted is False
    assert result.proposal_persisted is False
    assert result.persisted_audit_event_count == 0
    assert result.issues[0].code == "audit_append_failed"
    assert tuple(root.iterdir()) == ()


def test_repository_failure_reports_partial_persistence(
    tmp_path: Path,
) -> None:
    """Audit success followed by write failure must be explicit."""
    occupied_root = tmp_path / "proposals"
    occupied_root.write_text("not a directory", encoding="utf-8")
    audit_path = tmp_path / "audit" / "actions.jsonl"
    audit_path.parent.mkdir(parents=True)

    service = ProposalSubmissionService(
        ActionOrchestrator(
            ActionHandlerRegistry(),
            JsonlAuditStore(audit_path),
            DatetimeSequence(),
            IdentifierSequence(),
        ),
        MarkdownProposalRepository(occupied_root),
    )

    result = service.submit(_proposal())

    assert result.success is False
    assert result.audit_persisted is True
    assert result.proposal_persisted is False
    assert result.persisted_audit_event_count == 4
    assert result.issues[0].code == ("proposal_submission_partial_persistence")
    assert result.issues[1].code == ("proposal_directory_not_directory")


def test_orchestrator_exception_fails_closed(
    tmp_path: Path,
) -> None:
    """Unexpected orchestration failures should not reach persistence."""

    class RaisingOrchestrator:
        def submit(self, _proposal: ActionProposal) -> object:
            raise RuntimeError("Simulated failure.")

    root = tmp_path / "proposals"
    root.mkdir()
    service = ProposalSubmissionService(
        RaisingOrchestrator(),  # type: ignore[arg-type]
        MarkdownProposalRepository(root),
    )

    result = service.submit(_proposal())

    assert result.success is False
    assert result.issues[0].code == ("proposal_submission_orchestration_failed")
    assert tuple(root.iterdir()) == ()
