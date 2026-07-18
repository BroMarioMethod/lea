"""Serialisation for LEA action-contract records."""

from collections.abc import Mapping
from datetime import datetime
from typing import cast

from lea.actions.enums import (
    ActionStatus,
    ConfirmationPolicy,
    RiskLevel,
)
from lea.actions.errors import ActionContractError
from lea.actions.models import ActionProposal
from lea.actions.validation import (
    SCHEMA_VERSION,
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
