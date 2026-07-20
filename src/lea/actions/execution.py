"""Deterministic action-execution boundary for LEA."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from lea.actions.enums import ActionStatus
from lea.actions.errors import ActionContractError
from lea.actions.models import (
    ACTION_NAME_PATTERN,
    ActionProposal,
    ExecutionError,
    ExecutionResult,
    utc_now,
)
from lea.actions.transitions import (
    ActionTransition,
    transition_proposal,
)


class ActionHandler(Protocol):
    """Callable contract for one explicitly registered action handler."""

    def __call__(
        self,
        proposal: ActionProposal,
    ) -> Mapping[str, object] | None:
        """Handle one executing action proposal."""
        ...


class ActionHandlerRegistry:
    """Explicit deterministic mapping of action names to handlers."""

    __slots__ = ("_handlers",)

    def __init__(self) -> None:
        """Create an empty action-handler registry."""
        self._handlers: dict[str, ActionHandler] = {}

    def register(
        self,
        action: str,
        handler: ActionHandler,
    ) -> None:
        """Register exactly one handler for a canonical action name."""
        if ACTION_NAME_PATTERN.fullmatch(action) is None:
            raise ActionContractError(
                "action must use a lower-case namespaced identifier "
                "such as 'task.create'."
            )

        if not callable(handler):
            raise ActionContractError("handler must be callable.")

        if action in self._handlers:
            raise ActionContractError(
                f"A handler is already registered for action '{action}'."
            )

        self._handlers[action] = handler

    def get(
        self,
        action: str,
    ) -> ActionHandler | None:
        """Return the exactly registered handler for an action."""
        return self._handlers.get(action)

    def __contains__(self, action: object) -> bool:
        """Return whether an exact action name is registered."""
        return action in self._handlers

    def __len__(self) -> int:
        """Return the number of registered handlers."""
        return len(self._handlers)


@dataclass(frozen=True, slots=True)
class ActionExecutionIssue:
    """Immutable description of an execution-boundary problem."""

    code: str
    message: str
    proposal_id: str
    field: str | None = None

    def __post_init__(self) -> None:
        """Validate execution-boundary issue fields."""
        if not self.code.strip():
            raise ActionContractError(
                "Execution issue code must be a non-empty string."
            )

        if not self.message.strip():
            raise ActionContractError(
                "Execution issue message must be a non-empty string."
            )

        if not self.proposal_id.strip():
            raise ActionContractError(
                "Execution issue proposal_id must be a non-empty string."
            )

    def to_dict(self) -> Mapping[str, object]:
        """Return a JSON-compatible representation of this issue."""
        from lea.actions.serialisation import (
            action_execution_issue_to_dict,
        )

        return action_execution_issue_to_dict(self)


@dataclass(frozen=True, slots=True)
class ActionExecutionResult:
    """Immutable result of action-execution orchestration."""

    success: bool
    proposal: ActionProposal
    execution: ExecutionResult | None
    start_transition: ActionTransition | None
    completion_transition: ActionTransition | None
    issues: tuple[ActionExecutionIssue, ...]

    def __post_init__(self) -> None:
        """Enforce execution-boundary result consistency."""
        if self.issues:
            if self.success:
                raise ActionContractError(
                    "An execution-boundary result containing issues "
                    "must not be successful."
                )

            if self.execution is not None:
                raise ActionContractError(
                    "A pre-execution boundary failure must not contain "
                    "an execution result."
                )

            if self.start_transition is not None:
                raise ActionContractError(
                    "A pre-execution boundary failure must not contain "
                    "a start transition."
                )

            if self.completion_transition is not None:
                raise ActionContractError(
                    "A pre-execution boundary failure must not contain "
                    "a completion transition."
                )

            return

        if self.execution is None:
            raise ActionContractError(
                "A completed execution workflow must contain an execution result."
            )

        if self.start_transition is None:
            raise ActionContractError(
                "A completed execution workflow must contain a start transition."
            )

        if self.completion_transition is None:
            raise ActionContractError(
                "A completed execution workflow must contain a completion transition."
            )

        if self.success:
            if not self.execution.success:
                raise ActionContractError(
                    "A successful execution-boundary result must contain "
                    "a successful execution result."
                )

            if self.proposal.status is not ActionStatus.SUCCEEDED:
                raise ActionContractError(
                    "A successful execution-boundary result must contain "
                    "a succeeded proposal."
                )

            return

        if self.execution.success:
            raise ActionContractError(
                "A failed execution-boundary result must contain "
                "a failed execution result."
            )

        if self.proposal.status is not ActionStatus.FAILED:
            raise ActionContractError(
                "A handled execution failure must contain a failed proposal."
            )

    def to_dict(self) -> Mapping[str, object]:
        """Return a JSON-compatible representation of this result."""
        from lea.actions.serialisation import (
            action_execution_result_to_dict,
        )

        return action_execution_result_to_dict(self)


def execute_action(
    proposal: ActionProposal,
    registry: ActionHandlerRegistry,
    *,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> ActionExecutionResult:
    """Execute one approved proposal through its registered handler."""
    if proposal.status is not ActionStatus.APPROVED:
        return _boundary_failure(
            proposal,
            code="invalid_proposal_status",
            message=(
                "Only approved proposals may enter the action-execution boundary."
            ),
            field="status",
        )

    handler = registry.get(proposal.action)

    if handler is None:
        return _boundary_failure(
            proposal,
            code="unknown_action",
            message=(f"No action handler is registered for '{proposal.action}'."),
            field="action",
        )

    start_timestamp = started_at if started_at is not None else utc_now()

    timestamp_issue = _validate_timestamp(
        proposal,
        start_timestamp,
        field="started_at",
    )

    if timestamp_issue is not None:
        return _boundary_failure_from_issue(
            proposal,
            timestamp_issue,
        )

    if completed_at is not None:
        timestamp_issue = _validate_timestamp(
            proposal,
            completed_at,
            field="completed_at",
        )

        if timestamp_issue is not None:
            return _boundary_failure_from_issue(
                proposal,
                timestamp_issue,
            )

        if completed_at < start_timestamp:
            return _boundary_failure(
                proposal,
                code="invalid_timestamp_order",
                message=("completed_at must not occur before started_at."),
                field="completed_at",
            )

    start_result = transition_proposal(
        proposal,
        ActionStatus.EXECUTING,
        reason="Action execution started.",
        transitioned_at=start_timestamp,
    )

    if not start_result.success:
        return ActionExecutionResult(
            success=False,
            proposal=proposal,
            execution=None,
            start_transition=None,
            completion_transition=None,
            issues=tuple(
                ActionExecutionIssue(
                    code="invalid_start_transition",
                    message=issue.message,
                    proposal_id=proposal.proposal_id,
                    field="status",
                )
                for issue in start_result.issues
            ),
        )

    if start_result.transition is None:
        raise ActionContractError(
            "Successful start transition did not contain a transition record."
        )

    executing_proposal = start_result.proposal

    try:
        output = handler(executing_proposal)
    except Exception as error:
        completion_timestamp = completed_at if completed_at is not None else utc_now()

        return _complete_failed_execution(
            proposal=executing_proposal,
            start_transition=start_result.transition,
            started_at=start_timestamp,
            completed_at=completion_timestamp,
            error=ExecutionError(
                code="handler_exception",
                message="The action handler raised an exception.",
                details={
                    "exception_type": type(error).__name__,
                },
            ),
        )

    completion_timestamp = completed_at if completed_at is not None else utc_now()

    if completion_timestamp < start_timestamp:
        return _complete_failed_execution(
            proposal=executing_proposal,
            start_transition=start_result.transition,
            started_at=start_timestamp,
            completed_at=start_timestamp,
            error=ExecutionError(
                code="invalid_timestamp_order",
                message=(
                    "The execution completion timestamp occurred "
                    "before the start timestamp."
                ),
            ),
        )

    if output is not None and not isinstance(output, Mapping):
        return _complete_failed_execution(
            proposal=executing_proposal,
            start_transition=start_result.transition,
            started_at=start_timestamp,
            completed_at=completion_timestamp,
            error=ExecutionError(
                code="invalid_handler_output",
                message=("The action handler returned unsupported output."),
            ),
        )

    try:
        execution_result = ExecutionResult(
            proposal_id=proposal.proposal_id,
            success=True,
            status=ActionStatus.SUCCEEDED,
            output=output,
            error=None,
            started_at=start_timestamp,
            completed_at=completion_timestamp,
        )
    except ActionContractError:
        return _complete_failed_execution(
            proposal=executing_proposal,
            start_transition=start_result.transition,
            started_at=start_timestamp,
            completed_at=completion_timestamp,
            error=ExecutionError(
                code="invalid_handler_output",
                message=("The action handler returned unsupported output."),
            ),
        )

    completion_result = transition_proposal(
        executing_proposal,
        ActionStatus.SUCCEEDED,
        reason="Action handler completed successfully.",
        transitioned_at=completion_timestamp,
    )

    if not completion_result.success:
        raise ActionContractError(
            "The successful execution completion transition failed."
        )

    if completion_result.transition is None:
        raise ActionContractError(
            "Successful completion transition did not contain a transition record."
        )

    return ActionExecutionResult(
        success=True,
        proposal=completion_result.proposal,
        execution=execution_result,
        start_transition=start_result.transition,
        completion_transition=completion_result.transition,
        issues=(),
    )


def _complete_failed_execution(
    *,
    proposal: ActionProposal,
    start_transition: ActionTransition,
    started_at: datetime,
    completed_at: datetime,
    error: ExecutionError,
) -> ActionExecutionResult:
    """Create a failed execution result and final failed proposal."""
    execution_result = ExecutionResult(
        proposal_id=proposal.proposal_id,
        success=False,
        status=ActionStatus.FAILED,
        output=None,
        error=error,
        started_at=started_at,
        completed_at=completed_at,
    )

    completion_result = transition_proposal(
        proposal,
        ActionStatus.FAILED,
        reason=error.message,
        transitioned_at=completed_at,
    )

    if not completion_result.success:
        raise ActionContractError("The failed execution completion transition failed.")

    if completion_result.transition is None:
        raise ActionContractError(
            "Failed completion transition did not contain a transition record."
        )

    return ActionExecutionResult(
        success=False,
        proposal=completion_result.proposal,
        execution=execution_result,
        start_transition=start_transition,
        completion_transition=completion_result.transition,
        issues=(),
    )


def _boundary_failure(
    proposal: ActionProposal,
    *,
    code: str,
    message: str,
    field: str | None = None,
) -> ActionExecutionResult:
    """Return a structured failure before handler invocation."""
    return _boundary_failure_from_issue(
        proposal,
        ActionExecutionIssue(
            code=code,
            message=message,
            proposal_id=proposal.proposal_id,
            field=field,
        ),
    )


def _boundary_failure_from_issue(
    proposal: ActionProposal,
    issue: ActionExecutionIssue,
) -> ActionExecutionResult:
    """Return a pre-execution result containing one issue."""
    return ActionExecutionResult(
        success=False,
        proposal=proposal,
        execution=None,
        start_transition=None,
        completion_transition=None,
        issues=(issue,),
    )


def _validate_timestamp(
    proposal: ActionProposal,
    timestamp: datetime,
    *,
    field: str,
) -> ActionExecutionIssue | None:
    """Return an issue when an execution timestamp is naive."""
    if timestamp.tzinfo is not None and timestamp.utcoffset() is not None:
        return None

    return ActionExecutionIssue(
        code="invalid_timestamp",
        message=f"{field} must be timezone-aware.",
        proposal_id=proposal.proposal_id,
        field=field,
    )
