"""Tests for immutable LEA audit-event contracts."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from lea.actions import ActionContractError
from lea.audit import (
    LEGACY_AUDIT_SCHEMA_VERSION,
    AuditEvent,
    AuditEventType,
)

EVENT_ID = "11111111-1111-4111-8111-111111111111"
PROPOSAL_ID = "22222222-2222-4222-8222-222222222222"
OCCURRED_AT = datetime(2026, 7, 20, 18, 0, tzinfo=UTC)


def create_event() -> AuditEvent:
    """Create a deterministic audit event."""
    return AuditEvent(
        event_id=EVENT_ID,
        proposal_id=PROPOSAL_ID,
        event_type=AuditEventType.PROPOSAL_CREATED,
        occurred_at=OCCURRED_AT,
        payload={
            "proposal": {
                "action": "task.create",
                "parameters": {
                    "description": "Call John",
                    "tags": ["client", "follow-up"],
                },
            }
        },
    )


def test_canonical_event_type_values() -> None:
    """The event enum should expose the accepted canonical values."""
    assert {item.value for item in AuditEventType} == {
        "proposal_created",
        "validation_completed",
        "transition_completed",
        "transition_rejected",
        "confirmation_evaluated",
        "confirmation_recorded",
        "confirmation_policy_applied",
        "confirmation_decision_applied",
        "execution_completed",
        "execution_boundary_rejected",
    }


def test_event_is_immutable() -> None:
    """Audit events should not permit field reassignment."""
    event = create_event()

    with pytest.raises(FrozenInstanceError):
        event.event_id = PROPOSAL_ID  # type: ignore[misc]


def test_payload_is_deeply_immutable() -> None:
    """Nested audit payload values should be frozen."""
    payload = {
        "items": ["one", "two"],
    }

    event = AuditEvent(
        event_id=EVENT_ID,
        proposal_id=PROPOSAL_ID,
        event_type=AuditEventType.VALIDATION_COMPLETED,
        occurred_at=OCCURRED_AT,
        payload=payload,
    )

    payload["items"].append("three")

    assert event.payload == {
        "items": ("one", "two"),
    }


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("event_id", "not-a-uuid"),
        ("proposal_id", "not-a-uuid"),
        (
            "event_id",
            "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
        ),
    ],
)
def test_invalid_identifiers_are_rejected(
    field_name: str,
    value: str,
) -> None:
    """Identifiers should be canonical lower-case UUID strings."""
    arguments = {
        "event_id": EVENT_ID,
        "proposal_id": PROPOSAL_ID,
    }
    arguments[field_name] = value

    with pytest.raises(ActionContractError):
        AuditEvent(
            event_id=arguments["event_id"],
            proposal_id=arguments["proposal_id"],
            event_type=AuditEventType.PROPOSAL_CREATED,
            occurred_at=OCCURRED_AT,
            payload={},
        )


def test_naive_timestamp_is_rejected() -> None:
    """Audit timestamps should always be timezone-aware."""
    with pytest.raises(
        ActionContractError,
        match="timezone-aware",
    ):
        AuditEvent(
            event_id=EVENT_ID,
            proposal_id=PROPOSAL_ID,
            event_type=AuditEventType.PROPOSAL_CREATED,
            occurred_at=datetime(2026, 7, 20, 18, 0),
            payload={},
        )


def test_timestamp_is_canonicalised_to_utc() -> None:
    """Aware non-UTC timestamps should store the same instant in UTC."""
    local_timestamp = datetime(
        2026,
        7,
        20,
        20,
        0,
        tzinfo=timezone(timedelta(hours=2)),
    )

    event = AuditEvent(
        event_id=EVENT_ID,
        proposal_id=PROPOSAL_ID,
        event_type=AuditEventType.PROPOSAL_CREATED,
        occurred_at=local_timestamp,
        payload={},
    )

    assert event.occurred_at == OCCURRED_AT
    assert event.occurred_at.tzinfo is UTC


def test_event_serialisation_is_deterministic() -> None:
    """Audit events should serialise using the canonical shape."""
    event = create_event()

    assert event.to_dict() == {
        "schema_version": LEGACY_AUDIT_SCHEMA_VERSION,
        "event_id": EVENT_ID,
        "proposal_id": PROPOSAL_ID,
        "event_type": "proposal_created",
        "occurred_at": "2026-07-20T18:00:00+00:00",
        "payload": {
            "proposal": {
                "action": "task.create",
                "parameters": {
                    "description": "Call John",
                    "tags": ["client", "follow-up"],
                },
            }
        },
    }


def test_event_round_trip() -> None:
    """Serialised audit events should reconstruct deterministically."""
    original = create_event()

    reconstructed = AuditEvent.from_dict(original.to_dict())

    assert reconstructed == original


def test_unknown_fields_are_rejected() -> None:
    """Unrecognised top-level fields should fail closed."""
    data = dict(create_event().to_dict())
    data["unexpected"] = True

    with pytest.raises(
        ActionContractError,
        match="unknown fields",
    ):
        AuditEvent.from_dict(data)


def test_missing_fields_are_rejected() -> None:
    """Required top-level fields must be present."""
    data = dict(create_event().to_dict())
    del data["payload"]

    with pytest.raises(
        ActionContractError,
        match="missing required fields",
    ):
        AuditEvent.from_dict(data)


def test_unsupported_schema_version_is_rejected() -> None:
    """Unknown audit schema versions should fail explicitly."""
    data = dict(create_event().to_dict())
    data["schema_version"] = 99

    with pytest.raises(
        ActionContractError,
        match="Unsupported audit schema version",
    ):
        AuditEvent.from_dict(data)


def test_unknown_event_type_is_rejected() -> None:
    """Unknown event-type strings should fail explicitly."""
    data = dict(create_event().to_dict())
    data["event_type"] = "unknown_event"

    with pytest.raises(
        ActionContractError,
        match="event_type is not supported",
    ):
        AuditEvent.from_dict(data)
