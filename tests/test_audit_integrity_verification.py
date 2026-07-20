"""Tests for deterministic LEA audit-integrity verification."""

from datetime import UTC, datetime
from typing import cast

from lea.audit import (
    AuditEvent,
    AuditEventType,
    AuditIntegrityVerificationResult,
    IntegrityEnvelope,
    create_integrity_envelope,
    verify_integrity_chain,
)

EVENT_ID_1 = "11111111-1111-4111-8111-111111111111"
EVENT_ID_2 = "22222222-2222-4222-8222-222222222222"
EVENT_ID_3 = "33333333-3333-4333-8333-333333333333"

PROPOSAL_ID = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"

OCCURRED_AT_1 = datetime(2026, 7, 20, 18, 0, tzinfo=UTC)
OCCURRED_AT_2 = datetime(2026, 7, 20, 18, 5, tzinfo=UTC)
OCCURRED_AT_3 = datetime(2026, 7, 20, 18, 10, tzinfo=UTC)


def create_event(
    event_id: str,
    occurred_at: datetime,
    *,
    message: str,
) -> AuditEvent:
    """Create one deterministic audit event."""
    return AuditEvent(
        event_id=event_id,
        proposal_id=PROPOSAL_ID,
        event_type=AuditEventType.PROPOSAL_CREATED,
        occurred_at=occurred_at,
        payload={"message": message},
    )


def create_chain() -> tuple[IntegrityEnvelope, ...]:
    """Create a deterministic three-envelope integrity chain."""
    first = create_integrity_envelope(
        create_event(
            EVENT_ID_1,
            OCCURRED_AT_1,
            message="First event",
        ),
        previous_event_hash=None,
    )

    second = create_integrity_envelope(
        create_event(
            EVENT_ID_2,
            OCCURRED_AT_2,
            message="Second event",
        ),
        previous_event_hash=first.event_hash,
    )

    third = create_integrity_envelope(
        create_event(
            EVENT_ID_3,
            OCCURRED_AT_3,
            message="Third event",
        ),
        previous_event_hash=second.event_hash,
    )

    return first, second, third


def test_empty_chain_is_valid() -> None:
    """An empty chain should verify successfully."""
    result = verify_integrity_chain(())

    assert result == AuditIntegrityVerificationResult(
        valid=True,
        checked_events=0,
        last_valid_line=None,
        final_event_hash=None,
        issues=(),
    )


def test_single_genesis_envelope_is_valid() -> None:
    """One correctly hashed genesis envelope should verify."""
    first = create_chain()[0]

    result = verify_integrity_chain((first,))

    assert result.valid is True
    assert result.checked_events == 1
    assert result.last_valid_line == 1
    assert result.final_event_hash == first.event_hash
    assert result.issues == ()


def test_complete_chain_is_valid() -> None:
    """A correctly linked chain should verify completely."""
    chain = create_chain()

    result = verify_integrity_chain(chain)

    assert result.valid is True
    assert result.checked_events == 3
    assert result.last_valid_line == 3
    assert result.final_event_hash == chain[-1].event_hash
    assert result.issues == ()


def test_verification_uses_supplied_physical_order() -> None:
    """Reordering valid envelopes should break their chain links."""
    first, second, third = create_chain()

    result = verify_integrity_chain(
        (
            first,
            third,
            second,
        )
    )

    assert result.valid is False
    assert result.checked_events == 1
    assert result.last_valid_line == 1
    assert result.final_event_hash == first.event_hash
    assert result.issues[0].code == "chain_link_mismatch"
    assert result.issues[0].line_number == 2
    assert result.issues[0].event_id == EVENT_ID_3


def test_non_null_genesis_link_is_rejected() -> None:
    """The first envelope must not link to another hash."""
    first = create_chain()[0]
    invalid = IntegrityEnvelope(
        event=first.event,
        integrity_version=first.integrity_version,
        hash_algorithm=first.hash_algorithm,
        previous_event_hash="a" * 64,
        event_hash=first.event_hash,
    )

    result = verify_integrity_chain((invalid,))

    assert result.valid is False
    assert result.checked_events == 0
    assert result.last_valid_line is None
    assert result.final_event_hash is None
    assert result.issues[0].code == "invalid_genesis_link"
    assert result.issues[0].line_number == 1


def test_broken_previous_hash_is_detected() -> None:
    """A mismatched previous hash should fail at that envelope."""
    first, second, third = create_chain()

    broken_second = IntegrityEnvelope(
        event=second.event,
        integrity_version=second.integrity_version,
        hash_algorithm=second.hash_algorithm,
        previous_event_hash="a" * 64,
        event_hash=second.event_hash,
    )

    result = verify_integrity_chain(
        (
            first,
            broken_second,
            third,
        )
    )

    assert result.valid is False
    assert result.checked_events == 1
    assert result.last_valid_line == 1
    assert result.final_event_hash == first.event_hash
    assert result.issues[0].code == "chain_link_mismatch"
    assert result.issues[0].line_number == 2
    assert result.issues[0].event_id == EVENT_ID_2


def test_edited_event_payload_is_detected() -> None:
    """Changing event data without recalculating its hash should fail."""
    first, second, third = create_chain()

    edited_event = AuditEvent(
        event_id=second.event.event_id,
        proposal_id=second.event.proposal_id,
        event_type=second.event.event_type,
        occurred_at=second.event.occurred_at,
        payload={"message": "Edited second event"},
    )

    edited_second = IntegrityEnvelope(
        event=edited_event,
        integrity_version=second.integrity_version,
        hash_algorithm=second.hash_algorithm,
        previous_event_hash=second.previous_event_hash,
        event_hash=second.event_hash,
    )

    result = verify_integrity_chain(
        (
            first,
            edited_second,
            third,
        )
    )

    assert result.valid is False
    assert result.checked_events == 1
    assert result.last_valid_line == 1
    assert result.final_event_hash == first.event_hash
    assert result.issues[0].code == "event_hash_mismatch"
    assert result.issues[0].line_number == 2
    assert result.issues[0].event_id == EVENT_ID_2


def test_edited_event_hash_is_detected() -> None:
    """Replacing an event hash should fail canonical recalculation."""
    first = create_chain()[0]

    altered = IntegrityEnvelope(
        event=first.event,
        integrity_version=first.integrity_version,
        hash_algorithm=first.hash_algorithm,
        previous_event_hash=None,
        event_hash="a" * 64,
    )

    result = verify_integrity_chain((altered,))

    assert result.valid is False
    assert result.checked_events == 0
    assert result.last_valid_line is None
    assert result.final_event_hash is None
    assert result.issues[0].code == "event_hash_mismatch"
    assert result.issues[0].line_number == 1


def test_removed_middle_event_is_detected() -> None:
    """Removing a middle envelope should break the next chain link."""
    first, _, third = create_chain()

    result = verify_integrity_chain(
        (
            first,
            third,
        )
    )

    assert result.valid is False
    assert result.checked_events == 1
    assert result.issues[0].code == "chain_link_mismatch"
    assert result.issues[0].line_number == 2


def test_inserted_event_is_detected() -> None:
    """Inserting an unrelated envelope should break chain continuity."""
    first, second, third = create_chain()

    inserted = create_integrity_envelope(
        create_event(
            "44444444-4444-4444-8444-444444444444",
            OCCURRED_AT_2,
            message="Inserted event",
        ),
        previous_event_hash=first.event_hash,
    )

    result = verify_integrity_chain(
        (
            first,
            inserted,
            second,
            third,
        )
    )

    assert result.valid is False
    assert result.checked_events == 2
    assert result.last_valid_line == 2
    assert result.final_event_hash == inserted.event_hash
    assert result.issues[0].code == "chain_link_mismatch"
    assert result.issues[0].line_number == 3


def test_timestamp_order_does_not_affect_verification() -> None:
    """The chain protects append order rather than chronological order."""
    first = create_integrity_envelope(
        create_event(
            EVENT_ID_1,
            OCCURRED_AT_3,
            message="Later timestamp first",
        ),
        previous_event_hash=None,
    )
    second = create_integrity_envelope(
        create_event(
            EVENT_ID_2,
            OCCURRED_AT_1,
            message="Earlier timestamp second",
        ),
        previous_event_hash=first.event_hash,
    )

    result = verify_integrity_chain(
        (
            first,
            second,
        )
    )

    assert result.valid is True
    assert result.checked_events == 2


def test_verifier_does_not_mutate_envelopes() -> None:
    """Verification should leave supplied immutable data unchanged."""
    chain = create_chain()
    original = cast(
        tuple[dict[str, object], ...],
        tuple(envelope.to_dict() for envelope in chain),
    )

    verify_integrity_chain(chain)

    assert tuple(envelope.to_dict() for envelope in chain) == original
