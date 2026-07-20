"""Serialisation for LEA action-contract records."""

from collections.abc import Mapping
from datetime import datetime
from typing import cast

from lea.actions.confirmation import (
    ConfirmationDecisionApplicationResult,
    ConfirmationEvaluation,
    ConfirmationEvaluationResult,
    ConfirmationIssue,
    ConfirmationPolicyApplicationResult,
    ConfirmationRecord,
    ConfirmationRecordResult,
)
from lea.actions.enums import (
    ActionStatus,
    ConfirmationPolicy,
    RiskLevel,
)
from lea.actions.errors import ActionContractError
from lea.actions.models import (
    ActionProposal,
    ExecutionError,
    ExecutionResult,
)
from lea.actions.transitions import (
    ActionTransition,
    TransitionIssue,
    TransitionResult,
)
from lea.actions.validation import (
    SCHEMA_VERSION,
    ValidationIssue,
    ValidationResult,
    validate_proposal_data,
)
from lea.actions.values import FrozenJsonValue

type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)


def to_json_value(value: FrozenJsonValue) -> JsonValue:
    """Convert an immutable contract value into JSON-compatible data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, tuple):
        return [to_json_value(item) for item in value]

    return {key: to_json_value(item) for key, item in value.items()}


def proposal_to_dict(
    proposal: ActionProposal,
) -> dict[str, JsonValue]:
    """Convert an action proposal to a deterministic JSON-compatible mapping."""
    frozen_parameters = cast(
        Mapping[str, FrozenJsonValue],
        proposal.parameters,
    )

    parameters = {key: to_json_value(value) for key, value in frozen_parameters.items()}

    return {
        "schema_version": SCHEMA_VERSION,
        "proposal_id": proposal.proposal_id,
        "action": proposal.action,
        "parameters": parameters,
        "status": proposal.status.value,
        "risk_level": proposal.risk_level.value,
        "confirmation_policy": proposal.confirmation_policy.value,
        "source": proposal.source,
        "created_at": proposal.created_at.isoformat(),
        "reason": proposal.reason,
    }


def proposal_from_dict(
    data: Mapping[str, object],
) -> ActionProposal:
    """Construct an action proposal from validated untrusted data."""
    validation_result = validate_proposal_data(data)

    if not validation_result.valid:
        messages = "; ".join(issue.message for issue in validation_result.issues)
        raise ActionContractError(f"Invalid action proposal data: {messages}")

    parameters = data["parameters"]
    assert isinstance(parameters, Mapping)

    created_at = data["created_at"]
    assert isinstance(created_at, str)

    return ActionProposal(
        proposal_id=cast(str, data["proposal_id"]),
        action=cast(str, data["action"]),
        parameters=cast(Mapping[str, object], parameters),
        status=ActionStatus(cast(str, data["status"])),
        risk_level=RiskLevel(cast(str, data["risk_level"])),
        confirmation_policy=ConfirmationPolicy(cast(str, data["confirmation_policy"])),
        source=cast(str, data["source"]),
        created_at=datetime.fromisoformat(created_at),
        reason=cast(str | None, data["reason"]),
    )


def validation_issue_to_dict(
    issue: ValidationIssue,
) -> dict[str, JsonValue]:
    """Convert a validation issue to JSON-compatible data."""
    return {
        "code": issue.code,
        "message": issue.message,
        "field": issue.field,
    }


def validation_result_to_dict(
    result: ValidationResult,
) -> dict[str, JsonValue]:
    """Convert a validation result to JSON-compatible data."""
    return {
        "valid": result.valid,
        "issues": [validation_issue_to_dict(issue) for issue in result.issues],
    }


def execution_error_to_dict(
    error: ExecutionError,
) -> dict[str, JsonValue]:
    """Convert an execution error to JSON-compatible data."""
    details: dict[str, JsonValue] | None = None

    if error.details is not None:
        frozen_details = cast(
            Mapping[str, FrozenJsonValue],
            error.details,
        )
        details = {key: to_json_value(value) for key, value in frozen_details.items()}

    return {
        "code": error.code,
        "message": error.message,
        "details": details,
    }


def execution_result_to_dict(
    result: ExecutionResult,
) -> dict[str, JsonValue]:
    """Convert an execution result to JSON-compatible data."""
    output: dict[str, JsonValue] | None = None

    if result.output is not None:
        frozen_output = cast(
            Mapping[str, FrozenJsonValue],
            result.output,
        )
        output = {key: to_json_value(value) for key, value in frozen_output.items()}

    error = execution_error_to_dict(result.error) if result.error is not None else None

    return {
        "proposal_id": result.proposal_id,
        "success": result.success,
        "status": result.status.value,
        "output": output,
        "error": error,
        "started_at": result.started_at.isoformat(),
        "completed_at": result.completed_at.isoformat(),
    }


def action_transition_to_dict(
    transition: ActionTransition,
) -> dict[str, JsonValue]:
    """Convert an action transition to JSON-compatible data."""
    return {
        "proposal_id": transition.proposal_id,
        "from_status": transition.from_status.value,
        "to_status": transition.to_status.value,
        "transitioned_at": transition.transitioned_at.isoformat(),
        "reason": transition.reason,
    }


def transition_issue_to_dict(
    issue: TransitionIssue,
) -> dict[str, JsonValue]:
    """Convert a transition issue to JSON-compatible data."""
    return {
        "code": issue.code,
        "message": issue.message,
        "from_status": issue.from_status.value,
        "to_status": issue.to_status.value,
    }


def transition_result_to_dict(
    result: TransitionResult,
) -> dict[str, JsonValue]:
    """Convert a transition result to JSON-compatible data."""
    transition = (
        action_transition_to_dict(result.transition)
        if result.transition is not None
        else None
    )

    return {
        "success": result.success,
        "proposal": proposal_to_dict(result.proposal),
        "transition": transition,
        "issues": [transition_issue_to_dict(issue) for issue in result.issues],
    }


def confirmation_evaluation_to_dict(
    evaluation: ConfirmationEvaluation,
) -> dict[str, JsonValue]:
    """Convert a confirmation evaluation to JSON-compatible data."""
    return {
        "proposal_id": evaluation.proposal_id,
        "risk_level": evaluation.risk_level.value,
        "confirmation_policy": evaluation.confirmation_policy.value,
        "requirement": evaluation.requirement.value,
        "evaluated_at": evaluation.evaluated_at.isoformat(),
        "reason_code": evaluation.reason_code,
        "explanation": evaluation.explanation,
    }


def confirmation_issue_to_dict(
    issue: ConfirmationIssue,
) -> dict[str, JsonValue]:
    """Convert a confirmation issue to JSON-compatible data."""
    return {
        "code": issue.code,
        "message": issue.message,
        "proposal_id": issue.proposal_id,
        "field": issue.field,
    }


def confirmation_evaluation_result_to_dict(
    result: ConfirmationEvaluationResult,
) -> dict[str, JsonValue]:
    """Convert a confirmation evaluation result to JSON-compatible data."""
    evaluation = (
        confirmation_evaluation_to_dict(result.evaluation)
        if result.evaluation is not None
        else None
    )

    return {
        "success": result.success,
        "evaluation": evaluation,
        "issues": [confirmation_issue_to_dict(issue) for issue in result.issues],
    }


def confirmation_record_to_dict(
    record: ConfirmationRecord,
) -> dict[str, JsonValue]:
    """Convert a human confirmation record to JSON-compatible data."""
    return {
        "proposal_id": record.proposal_id,
        "decision": record.decision.value,
        "actor": record.actor,
        "decided_at": record.decided_at.isoformat(),
        "reason": record.reason,
    }


def confirmation_record_result_to_dict(
    result: ConfirmationRecordResult,
) -> dict[str, JsonValue]:
    """Convert a confirmation record result to JSON-compatible data."""
    record = (
        confirmation_record_to_dict(result.record)
        if result.record is not None
        else None
    )

    return {
        "success": result.success,
        "record": record,
        "issues": [confirmation_issue_to_dict(issue) for issue in result.issues],
    }


def confirmation_policy_application_result_to_dict(
    result: ConfirmationPolicyApplicationResult,
) -> dict[str, JsonValue]:
    """Convert a confirmation-policy application result."""
    evaluation = (
        confirmation_evaluation_to_dict(result.evaluation)
        if result.evaluation is not None
        else None
    )
    transition = (
        action_transition_to_dict(result.transition)
        if result.transition is not None
        else None
    )

    return {
        "success": result.success,
        "proposal": proposal_to_dict(result.proposal),
        "evaluation": evaluation,
        "transition": transition,
        "issues": [confirmation_issue_to_dict(issue) for issue in result.issues],
    }


def confirmation_decision_application_result_to_dict(
    result: ConfirmationDecisionApplicationResult,
) -> dict[str, JsonValue]:
    """Convert a confirmation-decision application result."""
    record = (
        confirmation_record_to_dict(result.record)
        if result.record is not None
        else None
    )
    transition = (
        action_transition_to_dict(result.transition)
        if result.transition is not None
        else None
    )

    return {
        "success": result.success,
        "proposal": proposal_to_dict(result.proposal),
        "record": record,
        "transition": transition,
        "issues": [confirmation_issue_to_dict(issue) for issue in result.issues],
    }
