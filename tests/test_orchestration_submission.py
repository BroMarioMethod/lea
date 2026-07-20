"""Tests for deterministic proposal-submission orchestration."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from lea.actions import (
    ActionHandlerRegistry,
    ActionProposal,
    ActionStatus,
    ConfirmationPolicy,
    RiskLevel,
)
from lea.audit import (
    AuditEvent,
    AuditEventType,
    JsonlAuditStore,
)
from lea.orchestration import (
    ActionOrchestrator,
    OrchestrationOutcome,
)

PROPOSAL_ID = "11111111-1111-4111-8111-111111111111"

EVENT_IDS = (
    "21111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
    "23333333-3333-4333-8333-333333333333",
    "24444444-4444-4444-8444-444444444444",
)

TIMESTAMPS = (
    datetime(2026, 7, 21, 12, 1, tzinfo=UTC),
    datetime(2026, 7, 21, 12, 2, tzinfo=UTC),
    datetime(2026, 7, 21, 12, 3, tzinfo=UTC),
)


class SequenceSource:
    """Return supplied deterministic values in order."""

    def __init__(self, values: tuple[object, ...]) -> None:
        self._values = iter(values)

    def __call__(self) -> object:
        return next(self._values)


class RecordingAuditSink:
    """Record appended audit events in memory."""

    def __init__(
        self,
        *,
        fail_on_call: int | None = None,
    ) -> None:
        self.events: list[AuditEvent] = []
        self.calls = 0
        self.fail_on_call = fail_on_call

    def append(self, event: AuditEvent) -> None:
        self.calls += 1

        if self.calls == self.fail_on_call:
            raise OSError("Simulated audit failure.")

        self.events.append(event)


def create_proposal(
    *,
    risk_level: RiskLevel = RiskLevel.LOW,
    confirmation_policy: ConfirmationPolicy = (ConfirmationPolicy.WHEN_REQUIRED),
) -> ActionProposal:
    """Create one deterministic proposed action."""
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={"description": "Test task"},
        status=ActionStatus.PROPOSED,
        risk_level=risk_level,
        confirmation_policy=confirmation_policy,
        source="test",
        created_at=datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
        reason="Test proposal submission.",
    )


def create_orchestrator(
    sink: RecordingAuditSink,
) -> ActionOrchestrator:
    """Create an orchestrator with deterministic dependencies."""
    return ActionOrchestrator(
        ActionHandlerRegistry(),
        sink,
        SequenceSource(TIMESTAMPS),
        SequenceSource(EVENT_IDS),
    )


def test_low_risk_submission_becomes_approved() -> None:
    """Low-risk proposals should be approved without execution."""
    sink = RecordingAuditSink()
    proposal = create_proposal()

    result = create_orchestrator(sink).submit(proposal)

    assert result.outcome is OrchestrationOutcome.APPROVED
    assert result.proposal.status is ActionStatus.APPROVED
    assert result.validation.valid is True
    assert result.confirmation_policy is not None
    assert result.confirmation_policy.success is True
    assert result.issue is None


def test_confirmation_required_submission_waits() -> None:
    """Medium-risk proposals should await explicit confirmation."""
    sink = RecordingAuditSink()
    proposal = create_proposal(
        risk_level=RiskLevel.MEDIUM,
    )

    result = create_orchestrator(sink).submit(proposal)

    assert result.outcome is OrchestrationOutcome.CONFIRMATION_REQUIRED
    assert result.proposal.status is ActionStatus.AWAITING_CONFIRMATION


def test_submission_persists_events_in_order() -> None:
    """Submission audit events should retain logical order."""
    sink = RecordingAuditSink()

    result = create_orchestrator(sink).submit(create_proposal())

    assert tuple(sink.events) == result.persisted_events
    assert tuple(event.event_type for event in sink.events) == (
        AuditEventType.PROPOSAL_CREATED,
        AuditEventType.VALIDATION_COMPLETED,
        AuditEventType.TRANSITION_COMPLETED,
        AuditEventType.CONFIRMATION_POLICY_APPLIED,
    )


def test_submission_uses_injected_event_identifiers() -> None:
    """Every submission event should use the injected ID source."""
    sink = RecordingAuditSink()

    create_orchestrator(sink).submit(create_proposal())

    assert tuple(event.event_id for event in sink.events) == EVENT_IDS


def test_submission_uses_injected_timestamps() -> None:
    """Validation and policy timestamps should come from the clock."""
    sink = RecordingAuditSink()

    result = create_orchestrator(sink).submit(create_proposal())

    assert sink.events[0].occurred_at == result.proposal.created_at
    assert sink.events[1].occurred_at == TIMESTAMPS[0]
    assert sink.events[2].occurred_at == TIMESTAMPS[1]
    assert result.confirmation_policy is not None
    assert result.confirmation_policy.evaluation is not None
    assert result.confirmation_policy.evaluation.evaluated_at == TIMESTAMPS[2]


def test_submission_does_not_execute_registered_handler() -> None:
    """Submission must never execute an action handler."""
    called = False

    def handler(proposal: ActionProposal) -> None:
        nonlocal called
        called = True

    registry = ActionHandlerRegistry()
    registry.register("task.create", handler)

    orchestrator = ActionOrchestrator(
        registry,
        RecordingAuditSink(),
        SequenceSource(TIMESTAMPS),
        SequenceSource(EVENT_IDS),
    )

    orchestrator.submit(create_proposal())

    assert called is False


def test_first_audit_failure_reports_no_persisted_events() -> None:
    """Failure on the first append should report an empty prefix."""
    sink = RecordingAuditSink(fail_on_call=1)

    result = create_orchestrator(sink).submit(create_proposal())

    assert result.outcome is OrchestrationOutcome.AUDIT_FAILED
    assert result.persisted_events == ()
    assert result.issue is not None
    assert result.issue.code == "audit_append_failed"


def test_second_audit_failure_reports_persisted_prefix() -> None:
    """Failure on validation persistence should retain event one."""
    sink = RecordingAuditSink(fail_on_call=2)

    result = create_orchestrator(sink).submit(create_proposal())

    assert result.outcome is OrchestrationOutcome.AUDIT_FAILED
    assert len(result.persisted_events) == 1
    assert result.persisted_events[0].event_type is AuditEventType.PROPOSAL_CREATED


def test_fourth_audit_failure_reports_three_event_prefix() -> None:
    """Failure on policy persistence should retain two events."""
    sink = RecordingAuditSink(fail_on_call=4)

    result = create_orchestrator(sink).submit(create_proposal())

    assert result.outcome is OrchestrationOutcome.AUDIT_FAILED
    assert len(result.persisted_events) == 3
    assert result.confirmation_policy is not None
    assert result.proposal.status is ActionStatus.APPROVED


def test_submission_does_not_mutate_original_proposal() -> None:
    """Policy application should return a new proposal value."""
    sink = RecordingAuditSink()
    proposal = create_proposal()

    result = create_orchestrator(sink).submit(proposal)

    assert proposal.status is ActionStatus.PROPOSED
    assert result.proposal is not proposal
    assert result.proposal.status is ActionStatus.APPROVED


def test_plain_jsonl_store_satisfies_audit_sink(
    tmp_path: Path,
) -> None:
    """The existing plain store should work without an adapter."""
    path = tmp_path / "audit.jsonl"
    store = JsonlAuditStore(path)

    orchestrator = ActionOrchestrator(
        ActionHandlerRegistry(),
        store,
        SequenceSource(TIMESTAMPS),
        SequenceSource(EVENT_IDS),
    )

    result = orchestrator.submit(create_proposal())

    assert result.outcome is OrchestrationOutcome.APPROVED
    assert store.read_all() == result.persisted_events


def test_invalid_clock_value_fails_before_validation_event() -> None:
    """An invalid clock result should produce a structured failure."""
    sink = RecordingAuditSink()
    orchestrator = ActionOrchestrator(
        ActionHandlerRegistry(),
        sink,
        SequenceSource(("not-a-datetime",)),
        SequenceSource(EVENT_IDS),
    )

    result = orchestrator.submit(create_proposal())

    assert result.outcome is OrchestrationOutcome.INVALID_OPERATION
    assert len(result.persisted_events) == 1
    assert result.issue is not None
    assert result.issue.code == "validation_audit_event_failed"


def test_invalid_event_identifier_fails_closed() -> None:
    """Invalid generated event IDs must not reach the audit sink."""
    sink = RecordingAuditSink()
    orchestrator = ActionOrchestrator(
        ActionHandlerRegistry(),
        sink,
        SequenceSource(TIMESTAMPS),
        SequenceSource(("invalid-id",)),
    )

    result = orchestrator.submit(create_proposal())

    assert result.outcome is OrchestrationOutcome.INVALID_OPERATION
    assert result.persisted_events == ()
    assert sink.events == []
    assert result.issue is not None
    assert result.issue.code == "proposal_audit_event_failed"


def test_third_audit_failure_reports_two_event_prefix() -> None:
    """Failure on transition persistence should retain two events."""
    sink = RecordingAuditSink(fail_on_call=3)

    result = create_orchestrator(sink).submit(create_proposal())

    assert result.outcome is OrchestrationOutcome.AUDIT_FAILED
    assert len(result.persisted_events) == 2
    assert tuple(event.event_type for event in result.persisted_events) == (
        AuditEventType.PROPOSAL_CREATED,
        AuditEventType.VALIDATION_COMPLETED,
    )
    assert result.confirmation_policy is None
    assert result.proposal.status is ActionStatus.VALIDATED
    assert result.issue is not None
    assert result.issue.code == "audit_append_failed"


def test_validation_transition_uses_injected_timestamp() -> None:
    """The validated transition should use the second clock value."""
    sink = RecordingAuditSink()

    result = create_orchestrator(sink).submit(create_proposal())

    transition_event = result.persisted_events[2]

    assert transition_event.event_type is AuditEventType.TRANSITION_COMPLETED
    assert transition_event.occurred_at == TIMESTAMPS[1]


def test_submission_event_identifiers_follow_creation_order() -> None:
    """Event identifiers should match deterministic creation order."""
    sink = RecordingAuditSink()

    result = create_orchestrator(sink).submit(create_proposal())

    assert tuple(event.event_id for event in result.persisted_events) == EVENT_IDS


def test_high_risk_submission_requires_confirmation() -> None:
    """High-risk proposals must never be automatically approved."""
    sink = RecordingAuditSink()

    result = create_orchestrator(sink).submit(
        create_proposal(
            risk_level=RiskLevel.HIGH,
            confirmation_policy=ConfirmationPolicy.NEVER,
        )
    )

    assert result.outcome is OrchestrationOutcome.CONFIRMATION_REQUIRED
    assert result.proposal.status is ActionStatus.AWAITING_CONFIRMATION
    assert result.confirmation_policy is not None
    assert result.confirmation_policy.success is True


def test_critical_risk_submission_requires_confirmation() -> None:
    """Critical-risk proposals must require explicit confirmation."""
    sink = RecordingAuditSink()

    result = create_orchestrator(sink).submit(
        create_proposal(
            risk_level=RiskLevel.CRITICAL,
            confirmation_policy=ConfirmationPolicy.NEVER,
        )
    )

    assert result.outcome is OrchestrationOutcome.CONFIRMATION_REQUIRED
    assert result.proposal.status is ActionStatus.AWAITING_CONFIRMATION


def test_always_confirmation_policy_requires_confirmation() -> None:
    """An always-confirm policy should apply even to low risk."""
    sink = RecordingAuditSink()

    result = create_orchestrator(sink).submit(
        create_proposal(
            risk_level=RiskLevel.LOW,
            confirmation_policy=ConfirmationPolicy.ALWAYS,
        )
    )

    assert result.outcome is OrchestrationOutcome.CONFIRMATION_REQUIRED
    assert result.proposal.status is ActionStatus.AWAITING_CONFIRMATION


def test_non_utc_clock_value_fails_closed() -> None:
    """The injected clock must return UTC rather than another zone."""
    non_utc = datetime.fromisoformat("2026-07-21T14:01:00+02:00")
    sink = RecordingAuditSink()

    orchestrator = ActionOrchestrator(
        ActionHandlerRegistry(),
        sink,
        SequenceSource((non_utc,)),
        SequenceSource(EVENT_IDS),
    )

    result = orchestrator.submit(create_proposal())

    assert result.outcome is OrchestrationOutcome.INVALID_OPERATION
    assert len(result.persisted_events) == 1
    assert result.issue is not None
    assert result.issue.code == "validation_audit_event_failed"


def test_naive_clock_value_fails_closed() -> None:
    """A timezone-naive clock value must not enter audit history."""
    naive = datetime(2026, 7, 21, 12, 1)
    sink = RecordingAuditSink()

    orchestrator = ActionOrchestrator(
        ActionHandlerRegistry(),
        sink,
        SequenceSource((naive,)),
        SequenceSource(EVENT_IDS),
    )

    result = orchestrator.submit(create_proposal())

    assert result.outcome is OrchestrationOutcome.INVALID_OPERATION
    assert len(result.persisted_events) == 1
    assert result.issue is not None
    assert result.issue.code == "validation_audit_event_failed"


def test_uppercase_event_identifier_fails_closed() -> None:
    """Generated event IDs must use canonical lower-case UUID form."""
    sink = RecordingAuditSink()
    uppercase_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa".upper()

    orchestrator = ActionOrchestrator(
        ActionHandlerRegistry(),
        sink,
        SequenceSource(TIMESTAMPS),
        SequenceSource((uppercase_id,)),
    )

    result = orchestrator.submit(create_proposal())

    assert result.outcome is OrchestrationOutcome.INVALID_OPERATION
    assert result.persisted_events == ()
    assert sink.events == []
    assert result.issue is not None
    assert result.issue.code == "proposal_audit_event_failed"


def test_integer_event_identifier_fails_closed() -> None:
    """The audit-event identifier source must return strings."""
    sink = RecordingAuditSink()

    orchestrator = ActionOrchestrator(
        ActionHandlerRegistry(),
        sink,
        SequenceSource(TIMESTAMPS),
        SequenceSource((123,)),
    )

    result = orchestrator.submit(create_proposal())

    assert result.outcome is OrchestrationOutcome.INVALID_OPERATION
    assert result.persisted_events == ()
    assert sink.events == []
    assert result.issue is not None
    assert result.issue.code == "proposal_audit_event_failed"


def test_audit_sink_return_value_is_ignored() -> None:
    """Different append return types should not affect orchestration."""

    class ReturningSink:
        def __init__(self) -> None:
            self.events: list[AuditEvent] = []

        def append(self, event: AuditEvent) -> object:
            self.events.append(event)
            return {"stored": True}

    sink = ReturningSink()

    orchestrator = ActionOrchestrator(
        ActionHandlerRegistry(),
        sink,
        SequenceSource(TIMESTAMPS),
        SequenceSource(EVENT_IDS),
    )

    result = orchestrator.submit(create_proposal())

    assert result.outcome is OrchestrationOutcome.APPROVED
    assert tuple(sink.events) == result.persisted_events


def test_submission_uses_exactly_three_clock_values() -> None:
    """Successful submission should consume its clock deterministically."""
    sink = RecordingAuditSink()
    clock = SequenceSource(TIMESTAMPS)

    orchestrator = ActionOrchestrator(
        ActionHandlerRegistry(),
        sink,
        clock,
        SequenceSource(EVENT_IDS),
    )

    result = orchestrator.submit(create_proposal())

    assert result.outcome is OrchestrationOutcome.APPROVED

    with pytest.raises(StopIteration):
        clock()


def test_submission_uses_exactly_four_event_identifiers() -> None:
    """Successful submission should consume four audit identifiers."""
    sink = RecordingAuditSink()
    identifier_source = SequenceSource(EVENT_IDS)

    orchestrator = ActionOrchestrator(
        ActionHandlerRegistry(),
        sink,
        SequenceSource(TIMESTAMPS),
        identifier_source,
    )

    result = orchestrator.submit(create_proposal())

    assert result.outcome is OrchestrationOutcome.APPROVED

    with pytest.raises(StopIteration):
        identifier_source()
