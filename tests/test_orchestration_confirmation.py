"""Tests for deterministic confirmation-decision orchestration."""

from datetime import UTC, datetime

from lea.actions import (
    ActionHandlerRegistry,
    ActionProposal,
    ActionStatus,
    ConfirmationDecision,
    ConfirmationPolicy,
    RiskLevel,
)
from lea.audit import (
    AuditEvent,
    AuditEventType,
)
from lea.orchestration import (
    ActionOrchestrator,
    OrchestrationOutcome,
)

PROPOSAL_ID = "11111111-1111-4111-8111-111111111111"
EVENT_ID = "21111111-1111-4111-8111-111111111111"
DECIDED_AT = datetime(2026, 7, 21, 13, 0, tzinfo=UTC)


class SequenceSource:
    """Return supplied deterministic values in order."""

    def __init__(self, values: tuple[object, ...]) -> None:
        self._values = iter(values)

    def __call__(self) -> object:
        return next(self._values)


class RecordingAuditSink:
    """Record or reject appended audit events."""

    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[AuditEvent] = []
        self.fail = fail

    def append(self, event: AuditEvent) -> None:
        if self.fail:
            raise OSError("Simulated audit failure.")

        self.events.append(event)


def create_awaiting_proposal() -> ActionProposal:
    """Create one proposal awaiting explicit confirmation."""
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={"description": "Test task"},
        status=ActionStatus.AWAITING_CONFIRMATION,
        risk_level=RiskLevel.HIGH,
        confirmation_policy=ConfirmationPolicy.WHEN_REQUIRED,
        source="test",
        created_at=datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
        reason="Test confirmation orchestration.",
    )


def create_orchestrator(
    sink: RecordingAuditSink,
) -> ActionOrchestrator:
    """Create an orchestrator with deterministic dependencies."""
    return ActionOrchestrator(
        ActionHandlerRegistry(),
        sink,
        SequenceSource((DECIDED_AT,)),
        SequenceSource((EVENT_ID,)),
    )


def test_explicit_approval_is_applied() -> None:
    """An explicit approval should produce an approved proposal."""
    sink = RecordingAuditSink()

    result = create_orchestrator(sink).confirm(
        create_awaiting_proposal(),
        ConfirmationDecision.APPROVED,
        "human@example.test",
        reason="Reviewed and accepted.",
    )

    assert result.outcome is OrchestrationOutcome.APPROVED
    assert result.proposal.status is ActionStatus.APPROVED
    assert result.decision_application is not None
    assert result.decision_application.success is True
    assert result.issue is None


def test_explicit_rejection_is_applied() -> None:
    """An explicit rejection should produce a rejected proposal."""
    result = create_orchestrator(RecordingAuditSink()).confirm(
        create_awaiting_proposal(),
        ConfirmationDecision.REJECTED,
        "human@example.test",
        reason="Not authorised.",
    )

    assert result.outcome is OrchestrationOutcome.REJECTED
    assert result.proposal.status is ActionStatus.REJECTED


def test_explicit_cancellation_is_applied() -> None:
    """An explicit cancellation should produce a cancelled proposal."""
    result = create_orchestrator(RecordingAuditSink()).confirm(
        create_awaiting_proposal(),
        ConfirmationDecision.CANCELLED,
        "human@example.test",
        reason="No longer required.",
    )

    assert result.outcome is OrchestrationOutcome.CANCELLED
    assert result.proposal.status is ActionStatus.CANCELLED


def test_confirmation_persists_one_composite_event() -> None:
    """Confirmation should write one composite application event."""
    sink = RecordingAuditSink()

    result = create_orchestrator(sink).confirm(
        create_awaiting_proposal(),
        ConfirmationDecision.APPROVED,
        "human@example.test",
    )

    assert tuple(sink.events) == result.persisted_events
    assert len(result.persisted_events) == 1
    assert (
        result.persisted_events[0].event_type
        is AuditEventType.CONFIRMATION_DECISION_APPLIED
    )


def test_confirmation_uses_injected_event_identifier() -> None:
    """The audit event should use the injected identifier."""
    sink = RecordingAuditSink()

    result = create_orchestrator(sink).confirm(
        create_awaiting_proposal(),
        ConfirmationDecision.APPROVED,
        "human@example.test",
    )

    assert result.persisted_events[0].event_id == EVENT_ID


def test_confirmation_uses_injected_timestamp() -> None:
    """The confirmation record should use the injected UTC time."""
    result = create_orchestrator(RecordingAuditSink()).confirm(
        create_awaiting_proposal(),
        ConfirmationDecision.APPROVED,
        "human@example.test",
    )

    assert result.decision_application is not None
    assert result.decision_application.record is not None
    assert result.decision_application.record.decided_at == DECIDED_AT
    assert result.persisted_events[0].occurred_at == DECIDED_AT


def test_confirmation_preserves_actor_and_reason() -> None:
    """The human actor and reason should remain in the record."""
    result = create_orchestrator(RecordingAuditSink()).confirm(
        create_awaiting_proposal(),
        ConfirmationDecision.APPROVED,
        "Marius",
        reason="Manually verified.",
    )

    assert result.decision_application is not None
    assert result.decision_application.record is not None
    assert result.decision_application.record.actor == "Marius"
    assert result.decision_application.record.reason == "Manually verified."


def test_confirmation_does_not_mutate_original_proposal() -> None:
    """Decision application should return a new proposal value."""
    proposal = create_awaiting_proposal()

    result = create_orchestrator(RecordingAuditSink()).confirm(
        proposal,
        ConfirmationDecision.APPROVED,
        "human@example.test",
    )

    assert proposal.status is ActionStatus.AWAITING_CONFIRMATION
    assert result.proposal is not proposal
    assert result.proposal.status is ActionStatus.APPROVED


def test_confirmation_rejects_invalid_proposal_state() -> None:
    """A decision must not apply to an already approved proposal."""
    proposal = ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={"description": "Test task"},
        status=ActionStatus.APPROVED,
        risk_level=RiskLevel.HIGH,
        confirmation_policy=ConfirmationPolicy.WHEN_REQUIRED,
        source="test",
        created_at=datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
        reason="Already approved.",
    )
    sink = RecordingAuditSink()

    result = create_orchestrator(sink).confirm(
        proposal,
        ConfirmationDecision.APPROVED,
        "human@example.test",
    )

    assert result.outcome is OrchestrationOutcome.INVALID_OPERATION
    assert result.proposal is proposal
    assert result.persisted_events == ()
    assert sink.events == []
    assert result.issue is not None
    assert result.issue.code == "confirmation_decision_rejected"


def test_blank_actor_fails_closed() -> None:
    """A blank human actor must not create an audit event."""
    sink = RecordingAuditSink()

    result = create_orchestrator(sink).confirm(
        create_awaiting_proposal(),
        ConfirmationDecision.APPROVED,
        "   ",
    )

    assert result.outcome is OrchestrationOutcome.INVALID_OPERATION
    assert result.persisted_events == ()
    assert sink.events == []


def test_naive_clock_value_fails_closed() -> None:
    """A naive confirmation timestamp must be rejected."""
    sink = RecordingAuditSink()
    orchestrator = ActionOrchestrator(
        ActionHandlerRegistry(),
        sink,
        SequenceSource((datetime(2026, 7, 21, 13, 0),)),
        SequenceSource((EVENT_ID,)),
    )

    result = orchestrator.confirm(
        create_awaiting_proposal(),
        ConfirmationDecision.APPROVED,
        "human@example.test",
    )

    assert result.outcome is OrchestrationOutcome.INVALID_OPERATION
    assert result.persisted_events == ()
    assert result.issue is not None
    assert result.issue.code == "confirmation_decision_failed"


def test_invalid_event_identifier_fails_closed() -> None:
    """Invalid audit identifiers must not reach the sink."""
    sink = RecordingAuditSink()
    orchestrator = ActionOrchestrator(
        ActionHandlerRegistry(),
        sink,
        SequenceSource((DECIDED_AT,)),
        SequenceSource(("invalid-id",)),
    )

    result = orchestrator.confirm(
        create_awaiting_proposal(),
        ConfirmationDecision.APPROVED,
        "human@example.test",
    )

    assert result.outcome is OrchestrationOutcome.INVALID_OPERATION
    assert result.proposal.status is ActionStatus.APPROVED
    assert result.persisted_events == ()
    assert sink.events == []
    assert result.issue is not None
    assert result.issue.code == "confirmation_audit_event_failed"


def test_audit_failure_reports_applied_decision() -> None:
    """Audit failure should retain the deterministic proposal result."""
    sink = RecordingAuditSink(fail=True)

    result = create_orchestrator(sink).confirm(
        create_awaiting_proposal(),
        ConfirmationDecision.APPROVED,
        "human@example.test",
    )

    assert result.outcome is OrchestrationOutcome.AUDIT_FAILED
    assert result.proposal.status is ActionStatus.APPROVED
    assert result.decision_application is not None
    assert result.decision_application.success is True
    assert result.persisted_events == ()
    assert result.issue is not None
    assert result.issue.code == "audit_append_failed"


def test_confirmation_does_not_execute_handler() -> None:
    """Confirmation must never invoke an action handler."""
    called = False

    def handler(proposal: ActionProposal) -> None:
        nonlocal called
        called = True

    registry = ActionHandlerRegistry()
    registry.register("task.create", handler)

    orchestrator = ActionOrchestrator(
        registry,
        RecordingAuditSink(),
        SequenceSource((DECIDED_AT,)),
        SequenceSource((EVENT_ID,)),
    )

    result = orchestrator.confirm(
        create_awaiting_proposal(),
        ConfirmationDecision.APPROVED,
        "human@example.test",
    )

    assert result.outcome is OrchestrationOutcome.APPROVED
    assert called is False
