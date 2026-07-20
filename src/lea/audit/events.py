"""Immutable audit-event contracts for LEA workflows."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast
from uuid import UUID, uuid4

from lea.actions.errors import ActionContractError
from lea.actions.values import freeze_parameters

AUDIT_SCHEMA_VERSION = 1

AUDIT_EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "event_id",
        "proposal_id",
        "event_type",
        "occurred_at",
        "payload",
    }
)


class AuditEventType(StrEnum):
    """Canonical event types for the LEA action workflow."""

    PROPOSAL_CREATED = "proposal_created"
    VALIDATION_COMPLETED = "validation_completed"
    TRANSITION_COMPLETED = "transition_completed"
    TRANSITION_REJECTED = "transition_rejected"
    CONFIRMATION_EVALUATED = "confirmation_evaluated"
    CONFIRMATION_RECORDED = "confirmation_recorded"
    CONFIRMATION_POLICY_APPLIED = "confirmation_policy_applied"
    CONFIRMATION_DECISION_APPLIED = "confirmation_decision_applied"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_BOUNDARY_REJECTED = "execution_boundary_rejected"


def generate_event_id() -> str:
    """Generate a canonical lower-case UUID event identifier."""
    return str(uuid4())


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Immutable record of one observed workflow event."""

    proposal_id: str
    event_type: AuditEventType
    occurred_at: datetime
    payload: Mapping[str, object]
    event_id: str = field(default_factory=generate_event_id)

    def __post_init__(self) -> None:
        """Validate and normalise audit-event data."""
        _validate_uuid(self.event_id, field_name="event_id")
        _validate_uuid(self.proposal_id, field_name="proposal_id")

        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ActionContractError("occurred_at must be timezone-aware.")

        canonical_timestamp = self.occurred_at.astimezone(UTC)
        frozen_payload = freeze_parameters(self.payload)

        object.__setattr__(
            self,
            "occurred_at",
            canonical_timestamp,
        )
        object.__setattr__(
            self,
            "payload",
            frozen_payload,
        )

    def to_dict(self) -> Mapping[str, object]:
        """Return a deterministic JSON-compatible representation."""
        from lea.audit.serialisation import audit_event_to_dict

        return audit_event_to_dict(self)

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, object],
    ) -> "AuditEvent":
        """Construct an audit event from untrusted serialised data."""
        from lea.audit.serialisation import audit_event_from_dict

        return audit_event_from_dict(data)


def validate_audit_event_data(
    data: Mapping[str, object],
) -> None:
    """Validate the top-level shape of serialised audit-event data."""
    supplied_fields = set(data)

    missing_fields = AUDIT_EVENT_FIELDS - supplied_fields
    if missing_fields:
        missing = ", ".join(sorted(missing_fields))
        raise ActionContractError(
            f"Audit event data is missing required fields: {missing}."
        )

    unknown_fields = supplied_fields - AUDIT_EVENT_FIELDS
    if unknown_fields:
        unknown = ", ".join(sorted(unknown_fields))
        raise ActionContractError(
            f"Audit event data contains unknown fields: {unknown}."
        )

    schema_version = data["schema_version"]
    if schema_version != AUDIT_SCHEMA_VERSION:
        raise ActionContractError("Unsupported audit schema version.")

    for field_name in ("event_id", "proposal_id", "event_type", "occurred_at"):
        if not isinstance(data[field_name], str):
            raise ActionContractError(f"{field_name} must be a string.")

    if not isinstance(data["payload"], Mapping):
        raise ActionContractError("payload must be a mapping.")


def _validate_uuid(
    value: str,
    *,
    field_name: str,
) -> None:
    """Validate a canonical lower-case UUID string."""
    try:
        parsed_identifier = UUID(value)
    except ValueError as error:
        raise ActionContractError(f"{field_name} must be a valid UUID.") from error

    if str(parsed_identifier) != value:
        raise ActionContractError(
            f"{field_name} must use canonical lower-case UUID format."
        )


def cast_payload(
    value: object,
) -> Mapping[str, object]:
    """Return a payload already validated as a mapping."""
    return cast(Mapping[str, object], value)
