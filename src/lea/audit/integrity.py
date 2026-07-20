"""Deterministic integrity contracts for LEA audit events."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import cast

from lea.actions.errors import ActionContractError
from lea.actions.serialisation import JsonValue
from lea.audit.events import AuditEvent

INTEGRITY_VERSION = 1
HASH_ALGORITHM = "sha256"

SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")

INTEGRITY_ENVELOPE_FIELDS = frozenset(
    {
        "event",
        "integrity_version",
        "hash_algorithm",
        "previous_event_hash",
        "event_hash",
    }
)


@dataclass(frozen=True, slots=True)
class IntegrityEnvelope:
    """Immutable integrity metadata wrapping one canonical audit event."""

    event: AuditEvent
    previous_event_hash: str | None
    event_hash: str
    integrity_version: int = INTEGRITY_VERSION
    hash_algorithm: str = HASH_ALGORITHM

    def __post_init__(self) -> None:
        """Validate canonical integrity-envelope fields."""
        if self.integrity_version != INTEGRITY_VERSION:
            raise ActionContractError("Unsupported audit integrity version.")

        if self.hash_algorithm != HASH_ALGORITHM:
            raise ActionContractError("Unsupported audit hash algorithm.")

        if self.previous_event_hash is not None:
            validate_sha256_hash(
                self.previous_event_hash,
                field_name="previous_event_hash",
            )

        validate_sha256_hash(
            self.event_hash,
            field_name="event_hash",
        )

    def to_dict(self) -> dict[str, JsonValue]:
        """Return a deterministic JSON-compatible envelope."""
        return integrity_envelope_to_dict(self)

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, object],
    ) -> "IntegrityEnvelope":
        """Construct an envelope from untrusted serialised data."""
        return integrity_envelope_from_dict(data)


@dataclass(frozen=True, slots=True)
class AuditIntegrityIssue:
    """Immutable description of one integrity-verification problem."""

    code: str
    message: str
    line_number: int | None = None
    event_id: str | None = None

    def __post_init__(self) -> None:
        """Validate integrity-issue fields."""
        if not self.code.strip():
            raise ActionContractError(
                "Integrity issue code must be a non-empty string."
            )

        if not self.message.strip():
            raise ActionContractError(
                "Integrity issue message must be a non-empty string."
            )

        if self.line_number is not None and self.line_number < 1:
            raise ActionContractError("Integrity issue line_number must be positive.")

        if self.event_id is not None and not self.event_id.strip():
            raise ActionContractError(
                "Integrity issue event_id must be non-empty when provided."
            )


@dataclass(frozen=True, slots=True)
class AuditIntegrityVerificationResult:
    """Immutable result of verifying one audit integrity chain."""

    valid: bool
    checked_events: int
    last_valid_line: int | None
    final_event_hash: str | None
    issues: tuple[AuditIntegrityIssue, ...]

    def __post_init__(self) -> None:
        """Enforce verification-result invariants."""
        if self.checked_events < 0:
            raise ActionContractError("checked_events must not be negative.")

        if self.last_valid_line is not None and self.last_valid_line < 1:
            raise ActionContractError("last_valid_line must be positive when provided.")

        if self.final_event_hash is not None:
            validate_sha256_hash(
                self.final_event_hash,
                field_name="final_event_hash",
            )

        if self.valid:
            if self.issues:
                raise ActionContractError(
                    "A valid integrity result must not contain issues."
                )

            return

        if not self.issues:
            raise ActionContractError(
                "An invalid integrity result must contain at least one issue."
            )


def validate_sha256_hash(
    value: str,
    *,
    field_name: str,
) -> None:
    """Validate a canonical lower-case SHA-256 hexadecimal string."""
    if SHA256_HEX_PATTERN.fullmatch(value) is None:
        raise ActionContractError(
            f"{field_name} must be a 64-character lower-case "
            "SHA-256 hexadecimal string."
        )


def _event_to_json_dict(
    event: AuditEvent,
) -> dict[str, JsonValue]:
    """Return canonical audit-event data with its JSON value type."""
    return cast(
        dict[str, JsonValue],
        event.to_dict(),
    )


def canonical_integrity_input(
    event: AuditEvent,
    *,
    previous_event_hash: str | None,
    integrity_version: int = INTEGRITY_VERSION,
    hash_algorithm: str = HASH_ALGORITHM,
) -> dict[str, JsonValue]:
    """Return the canonical dictionary used as SHA-256 input."""
    if integrity_version != INTEGRITY_VERSION:
        raise ActionContractError("Unsupported audit integrity version.")

    if hash_algorithm != HASH_ALGORITHM:
        raise ActionContractError("Unsupported audit hash algorithm.")

    if previous_event_hash is not None:
        validate_sha256_hash(
            previous_event_hash,
            field_name="previous_event_hash",
        )

    return {
        "event": _event_to_json_dict(event),
        "integrity_version": integrity_version,
        "hash_algorithm": hash_algorithm,
        "previous_event_hash": previous_event_hash,
    }


def canonical_integrity_bytes(
    event: AuditEvent,
    *,
    previous_event_hash: str | None,
    integrity_version: int = INTEGRITY_VERSION,
    hash_algorithm: str = HASH_ALGORITHM,
) -> bytes:
    """Encode deterministic canonical integrity input as UTF-8."""
    canonical_data = canonical_integrity_input(
        event,
        previous_event_hash=previous_event_hash,
        integrity_version=integrity_version,
        hash_algorithm=hash_algorithm,
    )

    encoded = json.dumps(
        canonical_data,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    return encoded.encode("utf-8")


def calculate_event_hash(
    event: AuditEvent,
    *,
    previous_event_hash: str | None,
    integrity_version: int = INTEGRITY_VERSION,
    hash_algorithm: str = HASH_ALGORITHM,
) -> str:
    """Calculate the deterministic hash for one chained audit event."""
    canonical_bytes = canonical_integrity_bytes(
        event,
        previous_event_hash=previous_event_hash,
        integrity_version=integrity_version,
        hash_algorithm=hash_algorithm,
    )

    return sha256(canonical_bytes).hexdigest()


def create_integrity_envelope(
    event: AuditEvent,
    *,
    previous_event_hash: str | None,
) -> IntegrityEnvelope:
    """Create one deterministic integrity envelope."""
    event_hash = calculate_event_hash(
        event,
        previous_event_hash=previous_event_hash,
    )

    return IntegrityEnvelope(
        event=event,
        integrity_version=INTEGRITY_VERSION,
        hash_algorithm=HASH_ALGORITHM,
        previous_event_hash=previous_event_hash,
        event_hash=event_hash,
    )


def integrity_envelope_to_dict(
    envelope: IntegrityEnvelope,
) -> dict[str, JsonValue]:
    """Convert an integrity envelope to canonical JSON-compatible data."""
    return {
        "event": _event_to_json_dict(envelope.event),
        "integrity_version": envelope.integrity_version,
        "hash_algorithm": envelope.hash_algorithm,
        "previous_event_hash": envelope.previous_event_hash,
        "event_hash": envelope.event_hash,
    }


def integrity_envelope_from_dict(
    data: Mapping[str, object],
) -> IntegrityEnvelope:
    """Construct an integrity envelope from untrusted data."""
    supplied_fields = set(data)

    missing_fields = INTEGRITY_ENVELOPE_FIELDS - supplied_fields
    if missing_fields:
        missing = ", ".join(sorted(missing_fields))
        raise ActionContractError(
            f"Integrity envelope is missing required fields: {missing}."
        )

    unknown_fields = supplied_fields - INTEGRITY_ENVELOPE_FIELDS
    if unknown_fields:
        unknown = ", ".join(sorted(unknown_fields))
        raise ActionContractError(
            f"Integrity envelope contains unknown fields: {unknown}."
        )

    event_data = data["event"]
    if not isinstance(event_data, Mapping):
        raise ActionContractError("Integrity envelope event must be a mapping.")

    integrity_version = data["integrity_version"]
    if not isinstance(integrity_version, int):
        raise ActionContractError("integrity_version must be an integer.")

    hash_algorithm = data["hash_algorithm"]
    if not isinstance(hash_algorithm, str):
        raise ActionContractError("hash_algorithm must be a string.")

    previous_event_hash = data["previous_event_hash"]
    if previous_event_hash is not None and not isinstance(previous_event_hash, str):
        raise ActionContractError("previous_event_hash must be a string or null.")

    event_hash = data["event_hash"]
    if not isinstance(event_hash, str):
        raise ActionContractError("event_hash must be a string.")

    return IntegrityEnvelope(
        event=AuditEvent.from_dict(cast(Mapping[str, object], event_data)),
        integrity_version=integrity_version,
        hash_algorithm=hash_algorithm,
        previous_event_hash=previous_event_hash,
        event_hash=event_hash,
    )
