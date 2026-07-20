"""Tests for deterministic action-execution orchestration."""

from datetime import UTC, datetime

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
)
from lea.orchestration import (
    ActionOrchestrator,
    OrchestrationOutcome,
)

PROPOSAL_ID = "11111111-1111-4111-8111-111111111111"
EVENT_ID = "21111111-1111-4111-8111-111111111111"

STARTED_AT = datetime(2026, 7, 21, 14, 0, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 7, 21, 14, 1, tzinfo=UTC)


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


def create_proposal(
    *,
    status: ActionStatus = ActionStatus.APPROVED,
) -> ActionProposal:
    """Create one deterministic action proposal."""
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={"description": "Test task"},
        status=status,
        risk_level=RiskLevel.LOW,
        confirmation_policy=ConfirmationPolicy.WHEN_REQUIRED,
        source="test",
        created_at=datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
        reason="Test execution orchestration.",
    )


def create_orchestrator(
    registry: ActionHandlerRegistry,
    sink: RecordingAuditSink,
) -> ActionOrchestrator:
    """Create an orchestrator with deterministic dependencies."""
    return ActionOrchestrator(
        registry,
        sink,
        SequenceSource((STARTED_AT, COMPLETED_AT)),
        SequenceSource((EVENT_ID,)),
    )


def test_successful_approved_execution() -> None:
    """An approved proposal should execute its registered handler."""
    registry = ActionHandlerRegistry()
    registry.register(
        "task.create",
        lambda proposal: {"created": True},
    )
    sink = RecordingAuditSink()

    result = create_orchestrator(
        registry,
        sink,
    ).execute(create_proposal())

    assert result.outcome is OrchestrationOutcome.EXECUTION_SUCCEEDED
    assert result.proposal.status is ActionStatus.SUCCEEDED
    assert result.execution is not None
    assert result.execution.success is True
    assert result.execution.execution is not None
    assert result.execution.execution.output == {"created": True}
    assert result.issue is None


def test_handler_receives_executing_proposal() -> None:
    """The handler should receive the executing proposal value."""
    received_statuses: list[ActionStatus] = []

    def handler(proposal: ActionProposal) -> None:
        received_statuses.append(proposal.status)

    registry = ActionHandlerRegistry()
    registry.register("task.create", handler)

    result = create_orchestrator(
        registry,
        RecordingAuditSink(),
    ).execute(create_proposal())

    assert result.outcome is OrchestrationOutcome.EXECUTION_SUCCEEDED
    assert received_statuses == [ActionStatus.EXECUTING]


def test_failed_handler_result_is_reported() -> None:
    """A handler exception should become a handled execution failure."""

    def handler(proposal: ActionProposal) -> None:
        raise RuntimeError("Simulated handler failure.")

    registry = ActionHandlerRegistry()
    registry.register("task.create", handler)

    result = create_orchestrator(
        registry,
        RecordingAuditSink(),
    ).execute(create_proposal())

    assert result.outcome is OrchestrationOutcome.EXECUTION_FAILED
    assert result.proposal.status is ActionStatus.FAILED
    assert result.execution is not None
    assert result.execution.success is False
    assert result.execution.execution is not None
    assert result.execution.execution.error is not None
    assert result.execution.execution.error.code == "handler_exception"
    assert result.issue is None


def test_invalid_handler_output_is_execution_failure() -> None:
    """Unsupported handler output should be contained."""

    def handler(proposal: ActionProposal) -> object:
        return object()

    registry = ActionHandlerRegistry()
    registry.register(
        "task.create",
        handler,  # type: ignore[arg-type]
    )

    result = create_orchestrator(
        registry,
        RecordingAuditSink(),
    ).execute(create_proposal())

    assert result.outcome is OrchestrationOutcome.EXECUTION_FAILED
    assert result.proposal.status is ActionStatus.FAILED
    assert result.execution is not None
    assert result.execution.execution is not None
    assert result.execution.execution.error is not None
    assert result.execution.execution.error.code == "invalid_handler_output"


def test_execution_persists_one_composite_event() -> None:
    """Execution should write one composite execution event."""
    registry = ActionHandlerRegistry()
    registry.register("task.create", lambda proposal: None)
    sink = RecordingAuditSink()

    result = create_orchestrator(
        registry,
        sink,
    ).execute(create_proposal())

    assert tuple(sink.events) == result.persisted_events
    assert len(result.persisted_events) == 1
    assert result.persisted_events[0].event_type is AuditEventType.EXECUTION_COMPLETED


def test_execution_uses_injected_timestamps() -> None:
    """Execution records should use both injected timestamps."""
    registry = ActionHandlerRegistry()
    registry.register("task.create", lambda proposal: None)

    result = create_orchestrator(
        registry,
        RecordingAuditSink(),
    ).execute(create_proposal())

    assert result.execution is not None
    assert result.execution.execution is not None
    assert result.execution.execution.started_at == STARTED_AT
    assert result.execution.execution.completed_at == COMPLETED_AT
    assert result.persisted_events[0].occurred_at == COMPLETED_AT


def test_execution_uses_injected_event_identifier() -> None:
    """The composite audit event should use the injected ID."""
    registry = ActionHandlerRegistry()
    registry.register("task.create", lambda proposal: None)

    result = create_orchestrator(
        registry,
        RecordingAuditSink(),
    ).execute(create_proposal())

    assert result.persisted_events[0].event_id == EVENT_ID


def test_execution_does_not_mutate_original_proposal() -> None:
    """Execution should return new immutable proposal values."""
    registry = ActionHandlerRegistry()
    registry.register("task.create", lambda proposal: None)
    proposal = create_proposal()

    result = create_orchestrator(
        registry,
        RecordingAuditSink(),
    ).execute(proposal)

    assert proposal.status is ActionStatus.APPROVED
    assert result.proposal is not proposal
    assert result.proposal.status is ActionStatus.SUCCEEDED


def test_non_approved_proposal_is_rejected() -> None:
    """Execution must not begin from a non-approved state."""
    called = False

    def handler(proposal: ActionProposal) -> None:
        nonlocal called
        called = True

    registry = ActionHandlerRegistry()
    registry.register("task.create", handler)
    sink = RecordingAuditSink()

    result = create_orchestrator(
        registry,
        sink,
    ).execute(create_proposal(status=ActionStatus.PROPOSED))

    assert result.outcome is OrchestrationOutcome.INVALID_OPERATION
    assert result.proposal.status is ActionStatus.PROPOSED
    assert result.execution is not None
    assert result.execution.execution is None
    assert result.persisted_events == ()
    assert sink.events == []
    assert called is False
    assert result.issue is not None
    assert result.issue.code == "execution_rejected"


def test_unknown_action_is_rejected() -> None:
    """An unregistered action must not enter execution."""
    result = create_orchestrator(
        ActionHandlerRegistry(),
        RecordingAuditSink(),
    ).execute(create_proposal())

    assert result.outcome is OrchestrationOutcome.INVALID_OPERATION
    assert result.execution is not None
    assert result.execution.execution is None
    assert result.persisted_events == ()
    assert result.issue is not None
    assert result.issue.code == "execution_rejected"


def test_audit_failure_retains_completed_execution() -> None:
    """Audit failure may occur after the handler side effect."""
    called = False

    def handler(proposal: ActionProposal) -> None:
        nonlocal called
        called = True

    registry = ActionHandlerRegistry()
    registry.register("task.create", handler)
    sink = RecordingAuditSink(fail=True)

    result = create_orchestrator(
        registry,
        sink,
    ).execute(create_proposal())

    assert result.outcome is OrchestrationOutcome.AUDIT_FAILED
    assert result.proposal.status is ActionStatus.SUCCEEDED
    assert result.execution is not None
    assert result.execution.success is True
    assert result.persisted_events == ()
    assert called is True
    assert result.issue is not None
    assert result.issue.code == "audit_append_failed"


def test_invalid_event_identifier_fails_after_execution() -> None:
    """Audit ID failure must retain the completed handler result."""
    called = False

    def handler(proposal: ActionProposal) -> None:
        nonlocal called
        called = True

    registry = ActionHandlerRegistry()
    registry.register("task.create", handler)
    sink = RecordingAuditSink()

    orchestrator = ActionOrchestrator(
        registry,
        sink,
        SequenceSource((STARTED_AT, COMPLETED_AT)),
        SequenceSource(("invalid-id",)),
    )

    result = orchestrator.execute(create_proposal())

    assert result.outcome is OrchestrationOutcome.INVALID_OPERATION
    assert result.proposal.status is ActionStatus.SUCCEEDED
    assert result.execution is not None
    assert result.persisted_events == ()
    assert sink.events == []
    assert called is True
    assert result.issue is not None
    assert result.issue.code == "execution_audit_event_failed"


def test_naive_start_timestamp_fails_before_handler() -> None:
    """A naive start timestamp must prevent execution."""
    called = False

    def handler(proposal: ActionProposal) -> None:
        nonlocal called
        called = True

    registry = ActionHandlerRegistry()
    registry.register("task.create", handler)

    orchestrator = ActionOrchestrator(
        registry,
        RecordingAuditSink(),
        SequenceSource(
            (
                datetime(2026, 7, 21, 14, 0),
                COMPLETED_AT,
            )
        ),
        SequenceSource((EVENT_ID,)),
    )

    result = orchestrator.execute(create_proposal())

    assert result.outcome is OrchestrationOutcome.INVALID_OPERATION
    assert result.execution is None
    assert result.persisted_events == ()
    assert called is False
    assert result.issue is not None
    assert result.issue.code == "execution_timestamp_failed"


def test_completion_before_start_is_handled_failure() -> None:
    """Invalid timestamp order should not invoke the handler."""
    called = False

    def handler(proposal: ActionProposal) -> None:
        nonlocal called
        called = True

    registry = ActionHandlerRegistry()
    registry.register("task.create", handler)

    earlier = datetime(2026, 7, 21, 13, 59, tzinfo=UTC)

    orchestrator = ActionOrchestrator(
        registry,
        RecordingAuditSink(),
        SequenceSource((STARTED_AT, earlier)),
        SequenceSource((EVENT_ID,)),
    )

    result = orchestrator.execute(create_proposal())

    assert result.outcome is OrchestrationOutcome.INVALID_OPERATION
    assert result.execution is not None
    assert result.execution.execution is None
    assert result.persisted_events == ()
    assert called is False


def test_execution_consumes_exactly_two_clock_values() -> None:
    """Execution should consume deterministic start and completion times."""
    registry = ActionHandlerRegistry()
    registry.register("task.create", lambda proposal: None)
    clock = SequenceSource((STARTED_AT, COMPLETED_AT))

    orchestrator = ActionOrchestrator(
        registry,
        RecordingAuditSink(),
        clock,
        SequenceSource((EVENT_ID,)),
    )

    result = orchestrator.execute(create_proposal())

    assert result.outcome is OrchestrationOutcome.EXECUTION_SUCCEEDED

    try:
        clock()
    except StopIteration:
        pass
    else:
        raise AssertionError("Execution consumed fewer than two clock values.")


def test_execution_consumes_exactly_one_event_identifier() -> None:
    """Completed execution should consume one audit-event identifier."""
    registry = ActionHandlerRegistry()
    registry.register("task.create", lambda proposal: None)
    identifier_source = SequenceSource((EVENT_ID,))

    orchestrator = ActionOrchestrator(
        registry,
        RecordingAuditSink(),
        SequenceSource((STARTED_AT, COMPLETED_AT)),
        identifier_source,
    )

    result = orchestrator.execute(create_proposal())

    assert result.outcome is OrchestrationOutcome.EXECUTION_SUCCEEDED

    try:
        identifier_source()
    except StopIteration:
        pass
    else:
        raise AssertionError("Execution consumed fewer than one event identifier.")
