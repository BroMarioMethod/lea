"""Serialisation for LEA audit events."""

from collections.abc import Mapping
from datetime import datetime
from typing import cast

from lea.actions.errors import ActionContractError
from lea.actions.serialisation import JsonValue, to_json_value
from lea.actions.values import FrozenJsonValue
from lea.audit.events import (
    AUDIT_SCHEMA_VERSION,
    AuditEvent,
    AuditEventType,
    cast_payload,
    validate_audit_event_data,
)


def audit_event_to_dict(
    event: AuditEvent,
) -> dict[str, JsonValue]:
    """Convert an audit event to deterministic JSON-compatible data."""
    frozen_payload = cast(
        Mapping[str, FrozenJsonValue],
        event.payload,
    )

    payload = {key: to_json_value(value) for key, value in frozen_payload.items()}

    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "event_id": event.event_id,
        "proposal_id": event.proposal_id,
        "event_type": event.event_type.value,
        "occurred_at": event.occurred_at.isoformat(),
        "payload": payload,
    }


def audit_event_from_dict(
    data: Mapping[str, object],
) -> AuditEvent:
    """Construct an audit event from validated untrusted data."""
    validate_audit_event_data(data)

    occurred_at = cast(str, data["occurred_at"])

    try:
        timestamp = datetime.fromisoformat(occurred_at)
    except ValueError as error:
        raise ActionContractError("occurred_at must use ISO 8601 format.") from error

    try:
        event_type = AuditEventType(cast(str, data["event_type"]))
    except ValueError as error:
        raise ActionContractError("event_type is not supported.") from error

    return AuditEvent(
        event_id=cast(str, data["event_id"]),
        proposal_id=cast(str, data["proposal_id"]),
        event_type=event_type,
        occurred_at=timestamp,
        payload=cast_payload(data["payload"]),
    )
