"""Tests for deterministic LEA audit-integrity contracts."""

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from hashlib import sha256

import pytest

from lea.actions import ActionContractError
from lea.audit import (
    HASH_ALGORITHM,
    INTEGRITY_VERSION,
    AuditEvent,
    AuditEventType,
    AuditIntegrityIssue,
    AuditIntegrityVerificationResult,
    IntegrityEnvelope,
    calculate_event_hash,
    canonical_integrity_bytes,
    canonical_integrity_input,
    create_integrity_envelope,
)

EVENT_ID = "11111111-1111-4111-8111-111111111111"
PROPOSAL_ID = "22222222-2222-4222-8222-222222222222"
OCCURRED_AT = datetime(2026, 7, 20, 18, 0, tzinfo=UTC)

PREVIOUS_HASH = "a" * 64


def create_event() -> AuditEvent:
    """Create a deterministic audit event."""
    return AuditEvent(
        event_id=EVENT_ID,
        proposal_id=PROPOSAL_ID,
        event_type=AuditEventType.PROPOSAL_CREATED,
        occurred_at=OCCURRED_AT,
        payload={
            "message": "Created £10 invoice",
            "items": ["one", "two"],
        },
    )


def test_integrity_constants_are_canonical() -> None:
    """The first integrity version should use SHA-256."""
    assert INTEGRITY_VERSION == 1
    assert HASH_ALGORITHM == "sha256"


def test_canonical_integrity_input_shape() -> None:
    """Hash input should contain exactly the specified fields."""
    event = create_event()

    assert canonical_integrity_input(
        event,
        previous_event_hash=None,
    ) == {
        "event": event.to_dict(),
        "integrity_version": 1,
        "hash_algorithm": "sha256",
        "previous_event_hash": None,
    }


def test_canonical_integrity_bytes_are_deterministic() -> None:
    """Hash input should use compact sorted UTF-8 JSON."""
    event = create_event()
    expected_data = {
        "event": event.to_dict(),
        "integrity_version": 1,
        "hash_algorithm": "sha256",
        "previous_event_hash": PREVIOUS_HASH,
    }
    expected = json.dumps(
        expected_data,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    assert (
        canonical_integrity_bytes(
            event,
            previous_event_hash=PREVIOUS_HASH,
        )
        == expected
    )


def test_hash_input_does_not_ascii_escape_unicode() -> None:
    """Canonical UTF-8 input should preserve Unicode characters."""
    encoded = canonical_integrity_bytes(
        create_event(),
        previous_event_hash=None,
    )

    assert "£10".encode() in encoded
    assert b"\\u00a3" not in encoded


def test_event_hash_matches_direct_sha256_calculation() -> None:
    """The event hash should cover the canonical input bytes."""
    event = create_event()
    canonical_bytes = canonical_integrity_bytes(
        event,
        previous_event_hash=PREVIOUS_HASH,
    )

    assert (
        calculate_event_hash(
            event,
            previous_event_hash=PREVIOUS_HASH,
        )
        == sha256(canonical_bytes).hexdigest()
    )


def test_same_input_produces_same_hash() -> None:
    """Repeated calculations should be deterministic."""
    event = create_event()

    first = calculate_event_hash(
        event,
        previous_event_hash=PREVIOUS_HASH,
    )
    second = calculate_event_hash(
        event,
        previous_event_hash=PREVIOUS_HASH,
    )

    assert first == second


def test_previous_hash_changes_event_hash() -> None:
    """The previous chain link must affect the calculated hash."""
    event = create_event()

    genesis_hash = calculate_event_hash(
        event,
        previous_event_hash=None,
    )
    chained_hash = calculate_event_hash(
        event,
        previous_event_hash=PREVIOUS_HASH,
    )

    assert genesis_hash != chained_hash


def test_genesis_envelope() -> None:
    """The first envelope should use no previous event hash."""
    event = create_event()

    envelope = create_integrity_envelope(
        event,
        previous_event_hash=None,
    )

    assert envelope.event is event
    assert envelope.previous_event_hash is None
    assert envelope.event_hash == calculate_event_hash(
        event,
        previous_event_hash=None,
    )


def test_chained_envelope() -> None:
    """A non-genesis envelope should retain the previous hash."""
    event = create_event()

    envelope = create_integrity_envelope(
        event,
        previous_event_hash=PREVIOUS_HASH,
    )

    assert envelope.previous_event_hash == PREVIOUS_HASH
    assert envelope.event_hash == calculate_event_hash(
        event,
        previous_event_hash=PREVIOUS_HASH,
    )


def test_integrity_envelope_is_immutable() -> None:
    """Integrity envelopes should not permit field reassignment."""
    envelope = create_integrity_envelope(
        create_event(),
        previous_event_hash=None,
    )

    with pytest.raises(FrozenInstanceError):
        envelope.event_hash = PREVIOUS_HASH  # type: ignore[misc]


def test_integrity_envelope_round_trip() -> None:
    """Envelope dictionary serialisation should round trip."""
    original = create_integrity_envelope(
        create_event(),
        previous_event_hash=PREVIOUS_HASH,
    )

    reconstructed = IntegrityEnvelope.from_dict(original.to_dict())

    assert reconstructed == original


def test_unknown_envelope_fields_are_rejected() -> None:
    """Unknown top-level envelope fields should fail closed."""
    envelope = create_integrity_envelope(
        create_event(),
        previous_event_hash=None,
    )
    data = dict(envelope.to_dict())
    data["unexpected"] = True

    with pytest.raises(
        ActionContractError,
        match="unknown fields",
    ):
        IntegrityEnvelope.from_dict(data)


def test_missing_envelope_fields_are_rejected() -> None:
    """Every canonical envelope field should be required."""
    envelope = create_integrity_envelope(
        create_event(),
        previous_event_hash=None,
    )
    data = dict(envelope.to_dict())
    del data["event_hash"]

    with pytest.raises(
        ActionContractError,
        match="missing required fields",
    ):
        IntegrityEnvelope.from_dict(data)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "a" * 63,
        "a" * 65,
        "A" * 64,
        "g" * 64,
    ],
)
def test_invalid_event_hashes_are_rejected(
    value: str,
) -> None:
    """Event hashes should use canonical lower-case SHA-256 hex."""
    with pytest.raises(
        ActionContractError,
        match="64-character lower-case",
    ):
        IntegrityEnvelope(
            event=create_event(),
            integrity_version=INTEGRITY_VERSION,
            hash_algorithm=HASH_ALGORITHM,
            previous_event_hash=None,
            event_hash=value,
        )


def test_unsupported_integrity_version_is_rejected() -> None:
    """Unknown integrity versions should fail explicitly."""
    with pytest.raises(
        ActionContractError,
        match="Unsupported audit integrity version",
    ):
        IntegrityEnvelope(
            event=create_event(),
            integrity_version=2,
            hash_algorithm=HASH_ALGORITHM,
            previous_event_hash=None,
            event_hash="a" * 64,
        )


def test_unsupported_hash_algorithm_is_rejected() -> None:
    """Unknown hash algorithms should fail explicitly."""
    with pytest.raises(
        ActionContractError,
        match="Unsupported audit hash algorithm",
    ):
        IntegrityEnvelope(
            event=create_event(),
            integrity_version=INTEGRITY_VERSION,
            hash_algorithm="sha512",
            previous_event_hash=None,
            event_hash="a" * 64,
        )


def test_integrity_issue_is_immutable() -> None:
    """Verification issues should be immutable."""
    issue = AuditIntegrityIssue(
        code="event_hash_mismatch",
        message="The event hash does not match.",
        line_number=2,
        event_id=EVENT_ID,
    )

    with pytest.raises(FrozenInstanceError):
        issue.code = "changed"  # type: ignore[misc]


def test_valid_verification_result() -> None:
    """A valid result should contain no issues."""
    result = AuditIntegrityVerificationResult(
        valid=True,
        checked_events=1,
        last_valid_line=1,
        final_event_hash="a" * 64,
        issues=(),
    )

    assert result.valid is True
    assert result.issues == ()


def test_empty_chain_verification_result() -> None:
    """An empty integrity chain should be valid."""
    result = AuditIntegrityVerificationResult(
        valid=True,
        checked_events=0,
        last_valid_line=None,
        final_event_hash=None,
        issues=(),
    )

    assert result.checked_events == 0


def test_invalid_verification_result_requires_issue() -> None:
    """Invalid results must explain the detected failure."""
    with pytest.raises(
        ActionContractError,
        match="must contain at least one issue",
    ):
        AuditIntegrityVerificationResult(
            valid=False,
            checked_events=0,
            last_valid_line=None,
            final_event_hash=None,
            issues=(),
        )


def test_valid_verification_result_rejects_issues() -> None:
    """Valid results must not contain verification issues."""
    issue = AuditIntegrityIssue(
        code="event_hash_mismatch",
        message="The event hash does not match.",
    )

    with pytest.raises(
        ActionContractError,
        match="must not contain issues",
    ):
        AuditIntegrityVerificationResult(
            valid=True,
            checked_events=0,
            last_valid_line=None,
            final_event_hash=None,
            issues=(issue,),
        )
