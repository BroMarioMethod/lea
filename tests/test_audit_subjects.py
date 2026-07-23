"""Tests for backwards-compatible generic audit subjects."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from lea.audit import (
    AUDIT_SCHEMA_VERSION,
    LEGACY_AUDIT_SCHEMA_VERSION,
    AuditEvent,
    AuditEventType,
    AuditSubjectType,
    JsonlAuditStore,
    canonical_integrity_bytes,
)

EVENT_ID = "11111111-1111-4111-8111-111111111111"
SUBJECT_ID = "22222222-2222-4222-8222-222222222222"
OCCURRED_AT = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)


def test_legacy_constructor_retains_schema_one_shape() -> None:
    event = AuditEvent(
        event_id=EVENT_ID,
        proposal_id=SUBJECT_ID,
        event_type=AuditEventType.PROPOSAL_CREATED,
        occurred_at=OCCURRED_AT,
        payload={"result": "created"},
    )
    assert event.schema_version == LEGACY_AUDIT_SCHEMA_VERSION
    assert event.to_dict()["proposal_id"] == SUBJECT_ID
    assert "subject_id" not in event.to_dict()


def test_schema_two_uses_generic_subject_shape() -> None:
    event = AuditEvent(
        event_id=EVENT_ID,
        subject_type=AuditSubjectType.KNOWLEDGE_DOCUMENT,
        subject_id=SUBJECT_ID,
        event_type=AuditEventType.VALIDATION_COMPLETED,
        occurred_at=OCCURRED_AT,
        payload={"operation": "read", "success": True},
    )
    assert event.schema_version == AUDIT_SCHEMA_VERSION
    assert event.to_dict()["subject_type"] == "knowledge_document"
    assert event.to_dict()["subject_id"] == SUBJECT_ID


def test_schema_one_round_trip_preserves_exact_hash_input() -> None:
    data = {
        "schema_version": 1,
        "event_id": EVENT_ID,
        "proposal_id": SUBJECT_ID,
        "event_type": "proposal_created",
        "occurred_at": "2026-07-23T10:00:00+00:00",
        "payload": {"message": "Legacy event"},
    }
    event = AuditEvent.from_dict(data)
    expected = json.dumps(
        {
            "event": data,
            "integrity_version": 1,
            "hash_algorithm": "sha256",
            "previous_event_hash": None,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    actual = canonical_integrity_bytes(event, previous_event_hash=None)
    assert actual == expected
    assert sha256(actual).hexdigest() == sha256(expected).hexdigest()


def test_schema_two_round_trip_is_deterministic() -> None:
    original = AuditEvent(
        event_id=EVENT_ID,
        subject_type=AuditSubjectType.KNOWLEDGE_REPOSITORY,
        subject_id=SUBJECT_ID,
        event_type=AuditEventType.VALIDATION_COMPLETED,
        occurred_at=OCCURRED_AT,
        payload={"operation": "inspect", "success": False},
    )
    assert AuditEvent.from_dict(original.to_dict()) == original


def test_store_reads_mixed_schema_versions(tmp_path: Path) -> None:
    store = JsonlAuditStore(tmp_path / "audit.jsonl")
    legacy = AuditEvent(
        event_id=EVENT_ID,
        proposal_id=SUBJECT_ID,
        event_type=AuditEventType.PROPOSAL_CREATED,
        occurred_at=OCCURRED_AT,
        payload={},
    )
    generic = AuditEvent(
        event_id="33333333-3333-4333-8333-333333333333",
        subject_type=AuditSubjectType.KNOWLEDGE_DOCUMENT,
        subject_id=SUBJECT_ID,
        event_type=AuditEventType.VALIDATION_COMPLETED,
        occurred_at=OCCURRED_AT,
        payload={},
    )
    store.append(legacy)
    store.append(generic)
    assert store.read_all() == (legacy, generic)
    assert store.read_for_subject(
        AuditSubjectType.KNOWLEDGE_DOCUMENT,
        SUBJECT_ID,
    ) == (generic,)
