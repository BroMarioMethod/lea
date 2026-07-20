"""Deterministic verification of LEA audit-integrity chains."""

from collections.abc import Sequence

from lea.audit.integrity import (
    AuditIntegrityIssue,
    AuditIntegrityVerificationResult,
    IntegrityEnvelope,
    calculate_event_hash,
)


def verify_integrity_chain(
    envelopes: Sequence[IntegrityEnvelope],
) -> AuditIntegrityVerificationResult:
    """Verify envelopes in their supplied physical order."""
    if not envelopes:
        return AuditIntegrityVerificationResult(
            valid=True,
            checked_events=0,
            last_valid_line=None,
            final_event_hash=None,
            issues=(),
        )

    previous_event_hash: str | None = None
    checked_events = 0
    last_valid_line: int | None = None

    for line_number, envelope in enumerate(envelopes, start=1):
        issue = _verify_envelope(
            envelope,
            expected_previous_hash=previous_event_hash,
            line_number=line_number,
        )

        if issue is not None:
            return AuditIntegrityVerificationResult(
                valid=False,
                checked_events=checked_events,
                last_valid_line=last_valid_line,
                final_event_hash=previous_event_hash,
                issues=(issue,),
            )

        checked_events += 1
        last_valid_line = line_number
        previous_event_hash = envelope.event_hash

    return AuditIntegrityVerificationResult(
        valid=True,
        checked_events=checked_events,
        last_valid_line=last_valid_line,
        final_event_hash=previous_event_hash,
        issues=(),
    )


def _verify_envelope(
    envelope: IntegrityEnvelope,
    *,
    expected_previous_hash: str | None,
    line_number: int,
) -> AuditIntegrityIssue | None:
    """Return the first integrity issue found for one envelope."""
    if line_number == 1 and envelope.previous_event_hash is not None:
        return AuditIntegrityIssue(
            code="invalid_genesis_link",
            message=(
                "The first integrity envelope must use a null previous_event_hash."
            ),
            line_number=line_number,
            event_id=envelope.event.event_id,
        )

    if envelope.previous_event_hash != expected_previous_hash:
        return AuditIntegrityIssue(
            code="chain_link_mismatch",
            message=(
                "The envelope previous_event_hash does not match "
                "the preceding event_hash."
            ),
            line_number=line_number,
            event_id=envelope.event.event_id,
        )

    calculated_hash = calculate_event_hash(
        envelope.event,
        previous_event_hash=envelope.previous_event_hash,
        integrity_version=envelope.integrity_version,
        hash_algorithm=envelope.hash_algorithm,
    )

    if envelope.event_hash != calculated_hash:
        return AuditIntegrityIssue(
            code="event_hash_mismatch",
            message=(
                "The stored event_hash does not match the canonical "
                "audit-event contents."
            ),
            line_number=line_number,
            event_id=envelope.event.event_id,
        )

    return None
