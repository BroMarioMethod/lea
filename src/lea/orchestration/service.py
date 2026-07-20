"""Deterministic application service for LEA action orchestration."""

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

from lea.actions import (
    ActionExecutionResult,
    ActionHandlerRegistry,
    ActionProposal,
    ActionStatus,
    ConfirmationDecision,
    ConfirmationDecisionApplicationResult,
    ConfirmationPolicyApplicationResult,
    TransitionResult,
    ValidationResult,
    apply_confirmation_decision,
    apply_confirmation_policy,
    execute_action,
    transition_proposal,
    validate_proposal_data,
)
from lea.audit import (
    AuditEvent,
    audit_action_execution,
    audit_confirmation_decision_application,
    audit_confirmation_policy_application,
    audit_proposal_created,
    audit_transition_result,
    audit_validation_completed,
)
from lea.orchestration.contracts import (
    AuditEventIdSource,
    AuditSink,
    ConfirmationOrchestrationResult,
    ExecutionOrchestrationResult,
    OrchestrationIssue,
    OrchestrationOutcome,
    SubmissionResult,
    UtcClock,
)


class ActionOrchestrator:
    """Coordinate deterministic action workflows through injected services."""

    __slots__ = (
        "_audit_event_id_source",
        "_audit_sink",
        "_clock",
        "_registry",
    )

    def __init__(
        self,
        registry: ActionHandlerRegistry,
        audit_sink: AuditSink,
        clock: UtcClock,
        audit_event_id_source: AuditEventIdSource,
    ) -> None:
        """Initialise an orchestrator with explicit dependencies."""
        self._registry = registry
        self._audit_sink = audit_sink
        self._clock = clock
        self._audit_event_id_source = audit_event_id_source

    def submit(
        self,
        proposal: ActionProposal,
    ) -> SubmissionResult:
        """Validate and apply confirmation policy without executing."""
        validation = validate_proposal_data(_proposal_data(proposal))
        persisted_events: list[AuditEvent] = []

        failure = self._create_proposal_event(
            proposal,
            validation=validation,
            persisted_events=persisted_events,
        )

        if failure is not None:
            return failure

        failure = self._create_validation_event(
            proposal,
            validation=validation,
            persisted_events=persisted_events,
        )

        if failure is not None:
            return failure

        if not validation.valid:
            return SubmissionResult(
                outcome=OrchestrationOutcome.VALIDATION_FAILED,
                proposal=proposal,
                validation=validation,
                confirmation_policy=None,
                persisted_events=tuple(persisted_events),
            )

        transition_result = self._validate_proposal(
            proposal,
            validation=validation,
            persisted_events=persisted_events,
        )

        if isinstance(transition_result, SubmissionResult):
            return transition_result

        failure = self._create_transition_event(
            transition_result,
            validation=validation,
            persisted_events=persisted_events,
        )

        if failure is not None:
            return failure

        if not transition_result.success:
            return SubmissionResult(
                outcome=OrchestrationOutcome.INVALID_OPERATION,
                proposal=transition_result.proposal,
                validation=validation,
                confirmation_policy=None,
                persisted_events=tuple(persisted_events),
                issue=OrchestrationIssue(
                    code="validation_transition_rejected",
                    message=("The validated proposal transition was rejected."),
                    operation="submit",
                    proposal_id=proposal.proposal_id,
                ),
            )

        validated_proposal = transition_result.proposal

        try:
            confirmation_policy = apply_confirmation_policy(
                validated_proposal,
                applied_at=self._next_utc_timestamp(),
            )
        except Exception:
            return _invalid_submission(
                proposal=validated_proposal,
                validation=validation,
                persisted_events=persisted_events,
                code="confirmation_policy_failed",
                message="Confirmation policy could not be applied.",
            )

        failure = self._create_policy_event(
            confirmation_policy,
            validation=validation,
            persisted_events=persisted_events,
        )

        if failure is not None:
            return failure

        if not confirmation_policy.success:
            return SubmissionResult(
                outcome=OrchestrationOutcome.INVALID_OPERATION,
                proposal=confirmation_policy.proposal,
                validation=validation,
                confirmation_policy=confirmation_policy,
                persisted_events=tuple(persisted_events),
                issue=OrchestrationIssue(
                    code="confirmation_policy_rejected",
                    message=("Confirmation policy application did not complete."),
                    operation="submit",
                    proposal_id=proposal.proposal_id,
                ),
            )

        return SubmissionResult(
            outcome=_submission_outcome(confirmation_policy.proposal.status),
            proposal=confirmation_policy.proposal,
            validation=validation,
            confirmation_policy=confirmation_policy,
            persisted_events=tuple(persisted_events),
        )

    def confirm(
        self,
        proposal: ActionProposal,
        decision: ConfirmationDecision,
        actor: str,
        *,
        reason: str | None = None,
    ) -> ConfirmationOrchestrationResult:
        """Apply one explicit human confirmation decision."""
        try:
            decision_application = apply_confirmation_decision(
                proposal,
                decision,
                actor,
                reason=reason,
                decided_at=self._next_utc_timestamp(),
            )
        except Exception:
            return _invalid_confirmation(
                proposal=proposal,
                code="confirmation_decision_failed",
                message=("The confirmation decision could not be applied."),
            )

        if not decision_application.success:
            return ConfirmationOrchestrationResult(
                outcome=OrchestrationOutcome.INVALID_OPERATION,
                proposal=decision_application.proposal,
                decision_application=decision_application,
                persisted_events=(),
                issue=OrchestrationIssue(
                    code="confirmation_decision_rejected",
                    message=(
                        "The confirmation decision was rejected by the "
                        "deterministic workflow."
                    ),
                    operation="confirm",
                    proposal_id=proposal.proposal_id,
                ),
            )

        try:
            event = audit_confirmation_decision_application(
                decision_application,
                event_id=self._next_event_id(),
            )
        except Exception:
            return _invalid_confirmation(
                proposal=decision_application.proposal,
                code="confirmation_audit_event_failed",
                message=("The confirmation-decision audit event could not be created."),
                decision_application=decision_application,
            )

        try:
            self._audit_sink.append(event)
        except Exception:
            return ConfirmationOrchestrationResult(
                outcome=OrchestrationOutcome.AUDIT_FAILED,
                proposal=decision_application.proposal,
                decision_application=decision_application,
                persisted_events=(),
                issue=OrchestrationIssue(
                    code="audit_append_failed",
                    message=(
                        "The confirmation-decision audit event could not be persisted."
                    ),
                    operation="confirm",
                    proposal_id=proposal.proposal_id,
                ),
            )

        return ConfirmationOrchestrationResult(
            outcome=_confirmation_outcome(decision_application.proposal.status),
            proposal=decision_application.proposal,
            decision_application=decision_application,
            persisted_events=(event,),
        )

    def execute(
        self,
        proposal: ActionProposal,
    ) -> ExecutionOrchestrationResult:
        """Execute one approved proposal through the registered handler."""
        try:
            started_at = self._next_utc_timestamp()
            completed_at = self._next_utc_timestamp()
        except Exception:
            return _invalid_execution(
                proposal=proposal,
                code="execution_timestamp_failed",
                message=("Execution timestamps could not be obtained."),
            )

        try:
            execution = execute_action(
                proposal,
                self._registry,
                started_at=started_at,
                completed_at=completed_at,
            )
        except Exception:
            return _invalid_execution(
                proposal=proposal,
                code="execution_boundary_failed",
                message=("The action execution boundary could not complete."),
            )

        if execution.execution is None:
            return ExecutionOrchestrationResult(
                outcome=OrchestrationOutcome.INVALID_OPERATION,
                proposal=execution.proposal,
                execution=execution,
                persisted_events=(),
                issue=OrchestrationIssue(
                    code="execution_rejected",
                    message=("The action was rejected before execution began."),
                    operation="execute",
                    proposal_id=proposal.proposal_id,
                ),
            )

        try:
            event = audit_action_execution(
                execution,
                event_id=self._next_event_id(),
            )
        except Exception:
            return _invalid_execution(
                proposal=execution.proposal,
                code="execution_audit_event_failed",
                message=("The action-execution audit event could not be created."),
                execution=execution,
            )

        try:
            self._audit_sink.append(event)
        except Exception:
            return ExecutionOrchestrationResult(
                outcome=OrchestrationOutcome.AUDIT_FAILED,
                proposal=execution.proposal,
                execution=execution,
                persisted_events=(),
                issue=OrchestrationIssue(
                    code="audit_append_failed",
                    message=(
                        "The action-execution audit event could not be persisted."
                    ),
                    operation="execute",
                    proposal_id=proposal.proposal_id,
                ),
            )

        return ExecutionOrchestrationResult(
            outcome=_execution_outcome(execution),
            proposal=execution.proposal,
            execution=execution,
            persisted_events=(event,),
        )

    def _validate_proposal(
        self,
        proposal: ActionProposal,
        *,
        validation: ValidationResult,
        persisted_events: list[AuditEvent],
    ) -> TransitionResult | SubmissionResult:
        """Transition a successfully validated proposal."""
        try:
            return transition_proposal(
                proposal,
                ActionStatus.VALIDATED,
                reason="Proposal data passed validation.",
                transitioned_at=self._next_utc_timestamp(),
            )
        except Exception:
            return _invalid_submission(
                proposal=proposal,
                validation=validation,
                persisted_events=persisted_events,
                code="validation_transition_failed",
                message=("The proposal could not transition to validated."),
            )

    def _create_proposal_event(
        self,
        proposal: ActionProposal,
        *,
        validation: ValidationResult,
        persisted_events: list[AuditEvent],
    ) -> SubmissionResult | None:
        """Create and persist the proposal-created audit event."""
        try:
            event = audit_proposal_created(
                proposal,
                event_id=self._next_event_id(),
            )
        except Exception:
            return _invalid_submission(
                proposal=proposal,
                validation=validation,
                persisted_events=persisted_events,
                code="proposal_audit_event_failed",
                message=("The proposal-created audit event could not be created."),
            )

        return self._persist_submission_event(
            event,
            proposal=proposal,
            validation=validation,
            confirmation_policy=None,
            persisted_events=persisted_events,
        )

    def _create_validation_event(
        self,
        proposal: ActionProposal,
        *,
        validation: ValidationResult,
        persisted_events: list[AuditEvent],
    ) -> SubmissionResult | None:
        """Create and persist the validation-completed audit event."""
        try:
            event = audit_validation_completed(
                proposal.proposal_id,
                validation,
                occurred_at=self._next_utc_timestamp(),
                event_id=self._next_event_id(),
            )
        except Exception:
            return _invalid_submission(
                proposal=proposal,
                validation=validation,
                persisted_events=persisted_events,
                code="validation_audit_event_failed",
                message=("The validation-completed audit event could not be created."),
            )

        return self._persist_submission_event(
            event,
            proposal=proposal,
            validation=validation,
            confirmation_policy=None,
            persisted_events=persisted_events,
        )

    def _create_transition_event(
        self,
        transition: TransitionResult,
        *,
        validation: ValidationResult,
        persisted_events: list[AuditEvent],
    ) -> SubmissionResult | None:
        """Create and persist the validation-transition audit event."""
        try:
            event = audit_transition_result(
                transition,
                event_id=self._next_event_id(),
            )
        except Exception:
            return _invalid_submission(
                proposal=transition.proposal,
                validation=validation,
                persisted_events=persisted_events,
                code="validation_transition_audit_event_failed",
                message=("The validation-transition audit event could not be created."),
            )

        return self._persist_submission_event(
            event,
            proposal=transition.proposal,
            validation=validation,
            confirmation_policy=None,
            persisted_events=persisted_events,
        )

    def _create_policy_event(
        self,
        confirmation_policy: ConfirmationPolicyApplicationResult,
        *,
        validation: ValidationResult,
        persisted_events: list[AuditEvent],
    ) -> SubmissionResult | None:
        """Create and persist the confirmation-policy audit event."""
        try:
            event = audit_confirmation_policy_application(
                confirmation_policy,
                event_id=self._next_event_id(),
            )
        except Exception:
            return _invalid_submission(
                proposal=confirmation_policy.proposal,
                validation=validation,
                persisted_events=persisted_events,
                code="confirmation_policy_audit_event_failed",
                message=("The confirmation-policy audit event could not be created."),
                confirmation_policy=confirmation_policy,
            )

        return self._persist_submission_event(
            event,
            proposal=confirmation_policy.proposal,
            validation=validation,
            confirmation_policy=confirmation_policy,
            persisted_events=persisted_events,
        )

    def _persist_submission_event(
        self,
        event: AuditEvent,
        *,
        proposal: ActionProposal,
        validation: ValidationResult,
        confirmation_policy: ConfirmationPolicyApplicationResult | None,
        persisted_events: list[AuditEvent],
    ) -> SubmissionResult | None:
        """Persist one event and report partial audit failure."""
        try:
            self._audit_sink.append(event)
        except Exception:
            return SubmissionResult(
                outcome=OrchestrationOutcome.AUDIT_FAILED,
                proposal=proposal,
                validation=validation,
                confirmation_policy=confirmation_policy,
                persisted_events=tuple(persisted_events),
                issue=OrchestrationIssue(
                    code="audit_append_failed",
                    message="An audit event could not be persisted.",
                    operation="submit",
                    proposal_id=proposal.proposal_id,
                ),
            )

        persisted_events.append(event)
        return None

    def _next_utc_timestamp(self) -> datetime:
        """Return one validated timezone-aware UTC timestamp."""
        value = self._clock()

        if not isinstance(value, datetime):
            raise ValueError("The orchestration clock must return a datetime.")

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "The orchestration clock must return a timezone-aware datetime."
            )

        if value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("The orchestration clock must return a UTC datetime.")

        return value.astimezone(UTC)

    def _next_event_id(self) -> str:
        """Return one validated canonical audit-event UUID."""
        value = self._audit_event_id_source()

        if not isinstance(value, str):
            raise ValueError("The audit-event identifier source must return a string.")

        try:
            parsed_identifier = UUID(value)
        except ValueError as error:
            raise ValueError(
                "The audit-event identifier source must return a valid UUID."
            ) from error

        if str(parsed_identifier) != value:
            raise ValueError(
                "The audit-event identifier source must return a "
                "canonical lower-case UUID."
            )

        return value


def _proposal_data(
    proposal: ActionProposal,
) -> Mapping[str, object]:
    """Return canonical proposal data for deterministic validation."""
    return proposal.to_dict()


def _submission_outcome(
    status: ActionStatus,
) -> OrchestrationOutcome:
    """Map the applied confirmation-policy status to an outcome."""
    if status is ActionStatus.AWAITING_CONFIRMATION:
        return OrchestrationOutcome.CONFIRMATION_REQUIRED

    if status is ActionStatus.APPROVED:
        return OrchestrationOutcome.APPROVED

    raise ValueError("Confirmation policy produced an unsupported proposal status.")


def _confirmation_outcome(
    status: ActionStatus,
) -> OrchestrationOutcome:
    """Map a confirmed proposal status to its orchestration outcome."""
    if status is ActionStatus.APPROVED:
        return OrchestrationOutcome.APPROVED

    if status is ActionStatus.REJECTED:
        return OrchestrationOutcome.REJECTED

    if status is ActionStatus.CANCELLED:
        return OrchestrationOutcome.CANCELLED

    raise ValueError("Confirmation decision produced an unsupported proposal status.")


def _invalid_confirmation(
    *,
    proposal: ActionProposal,
    code: str,
    message: str,
    decision_application: (ConfirmationDecisionApplicationResult | None) = None,
) -> ConfirmationOrchestrationResult:
    """Return a structured confirmation dependency failure."""
    return ConfirmationOrchestrationResult(
        outcome=OrchestrationOutcome.INVALID_OPERATION,
        proposal=proposal,
        decision_application=decision_application,
        persisted_events=(),
        issue=OrchestrationIssue(
            code=code,
            message=message,
            operation="confirm",
            proposal_id=proposal.proposal_id,
        ),
    )


def _execution_outcome(
    execution: ActionExecutionResult,
) -> OrchestrationOutcome:
    """Map a completed execution boundary result to an outcome."""
    if execution.success:
        return OrchestrationOutcome.EXECUTION_SUCCEEDED

    return OrchestrationOutcome.EXECUTION_FAILED


def _invalid_execution(
    *,
    proposal: ActionProposal,
    code: str,
    message: str,
    execution: ActionExecutionResult | None = None,
) -> ExecutionOrchestrationResult:
    """Return a structured execution dependency failure."""
    return ExecutionOrchestrationResult(
        outcome=OrchestrationOutcome.INVALID_OPERATION,
        proposal=proposal,
        execution=execution,
        persisted_events=(),
        issue=OrchestrationIssue(
            code=code,
            message=message,
            operation="execute",
            proposal_id=proposal.proposal_id,
        ),
    )


def _invalid_submission(
    *,
    proposal: ActionProposal,
    validation: ValidationResult,
    persisted_events: list[AuditEvent],
    code: str,
    message: str,
    confirmation_policy: ConfirmationPolicyApplicationResult | None = None,
) -> SubmissionResult:
    """Return a structured submission dependency failure."""
    return SubmissionResult(
        outcome=OrchestrationOutcome.INVALID_OPERATION,
        proposal=proposal,
        validation=validation,
        confirmation_policy=confirmation_policy,
        persisted_events=tuple(persisted_events),
        issue=OrchestrationIssue(
            code=code,
            message=message,
            operation="submit",
            proposal_id=proposal.proposal_id,
        ),
    )
