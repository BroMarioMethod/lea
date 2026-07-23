"""Serialisation for LEA audit events."""

from collections.abc import Mapping
from datetime import datetime
from typing import cast

from lea.actions.errors import ActionContractError
from lea.actions.serialisation import JsonValue, to_json_value
from lea.actions.values import FrozenJsonValue
from lea.audit.events import (
    AUDIT_SCHEMA_VERSION,
    LEGACY_AUDIT_SCHEMA_VERSION,
    AuditEvent,
    AuditEventType,
    AuditSubjectType,
    cast_payload,
    validate_audit_event_data,
)


def audit_event_to_dict(event: AuditEvent) -> dict[str, JsonValue]:
    """Convert an audit event to deterministic JSON-compatible data."""
    frozen_payload = cast(Mapping[str, FrozenJsonValue], event.payload)
    payload = {key: to_json_value(value) for key, value in frozen_payload.items()}
    common: dict[str, JsonValue] = {
        "schema_version": cast(int, event.schema_version),
        "event_id": event.event_id,
        "event_type": event.event_type.value,
        "occurred_at": event.occurred_at.isoformat(),
        "payload": payload,
    }
    if event.schema_version == LEGACY_AUDIT_SCHEMA_VERSION:
        assert event.proposal_id is not None
        common["proposal_id"] = event.proposal_id
        return common
    assert event.schema_version == AUDIT_SCHEMA_VERSION
    assert event.subject_type is not None
    assert event.subject_id is not None
    common["subject_type"] = event.subject_type.value
    common["subject_id"] = event.subject_id
    return common


def audit_event_from_dict(data: Mapping[str, object]) -> AuditEvent:
    """Construct an audit event from validated untrusted data."""
    validate_audit_event_data(data)
    try:
        timestamp = datetime.fromisoformat(cast(str, data["occurred_at"]))
    except ValueError as error:
        raise ActionContractError("occurred_at must use ISO 8601 format.") from error
    try:
        event_type = AuditEventType(cast(str, data["event_type"]))
    except ValueError as error:
        raise ActionContractError("event_type is not supported.") from error

    schema_version = cast(int, data["schema_version"])
    if schema_version == LEGACY_AUDIT_SCHEMA_VERSION:
        return AuditEvent(
            event_id=cast(str, data["event_id"]),
            proposal_id=cast(str, data["proposal_id"]),
            event_type=event_type,
            occurred_at=timestamp,
            payload=cast_payload(data["payload"]),
            schema_version=schema_version,
        )

    try:
        subject_type = AuditSubjectType(cast(str, data["subject_type"]))
    except ValueError as error:
        raise ActionContractError("subject_type is not supported.") from error
    return AuditEvent(
        event_id=cast(str, data["event_id"]),
        subject_type=subject_type,
        subject_id=cast(str, data["subject_id"]),
        event_type=event_type,
        occurred_at=timestamp,
        payload=cast_payload(data["payload"]),
        schema_version=schema_version,
    )
