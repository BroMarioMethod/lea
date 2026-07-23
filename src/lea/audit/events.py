"""Immutable audit-event contracts for LEA workflows."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast
from uuid import UUID, uuid4

from lea.actions.errors import ActionContractError
from lea.actions.values import freeze_parameters

LEGACY_AUDIT_SCHEMA_VERSION = 1
AUDIT_SCHEMA_VERSION = 2

AUDIT_EVENT_FIELDS_V1 = frozenset(
    {
        "schema_version",
        "event_id",
        "proposal_id",
        "event_type",
        "occurred_at",
        "payload",
    }
)
AUDIT_EVENT_FIELDS_V2 = frozenset(
    {
        "schema_version",
        "event_id",
        "subject_type",
        "subject_id",
        "event_type",
        "occurred_at",
        "payload",
    }
)
AUDIT_EVENT_FIELDS = AUDIT_EVENT_FIELDS_V1 | AUDIT_EVENT_FIELDS_V2


class AuditSubjectType(StrEnum):
    """Canonical subjects that may own an audit event."""

    PROPOSAL = "proposal"
    KNOWLEDGE_DOCUMENT = "knowledge_document"
    KNOWLEDGE_REPOSITORY = "knowledge_repository"


class AuditEventType(StrEnum):
    """Canonical event types for LEA workflows."""

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

    event_type: AuditEventType
    occurred_at: datetime
    payload: Mapping[str, object]
    event_id: str = field(default_factory=generate_event_id)
    proposal_id: str | None = None
    subject_type: AuditSubjectType | None = None
    subject_id: str | None = None
    schema_version: int | None = None

    def __post_init__(self) -> None:
        """Validate and normalise audit-event data."""
        _validate_uuid(self.event_id, field_name="event_id")
        schema_version = self.schema_version
        if schema_version is None:
            schema_version = (
                LEGACY_AUDIT_SCHEMA_VERSION
                if self.proposal_id is not None
                else AUDIT_SCHEMA_VERSION
            )

        if schema_version == LEGACY_AUDIT_SCHEMA_VERSION:
            if self.proposal_id is None:
                raise ActionContractError("Schema 1 audit events require proposal_id.")
            if self.subject_type is not None or self.subject_id is not None:
                raise ActionContractError(
                    "Schema 1 audit events must not contain subject fields."
                )
            _validate_uuid(self.proposal_id, field_name="proposal_id")
        elif schema_version == AUDIT_SCHEMA_VERSION:
            if self.proposal_id is not None:
                raise ActionContractError(
                    "Schema 2 audit events must not contain proposal_id."
                )
            if self.subject_type is None or self.subject_id is None:
                raise ActionContractError(
                    "Schema 2 audit events require subject_type and subject_id."
                )
            _validate_uuid(self.subject_id, field_name="subject_id")
        else:
            raise ActionContractError("Unsupported audit schema version.")

        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ActionContractError("occurred_at must be timezone-aware.")

        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "occurred_at", self.occurred_at.astimezone(UTC))
        object.__setattr__(self, "payload", freeze_parameters(self.payload))

    def to_dict(self) -> Mapping[str, object]:
        """Return a deterministic JSON-compatible representation."""
        from lea.audit.serialisation import audit_event_to_dict

        return audit_event_to_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "AuditEvent":
        """Construct an audit event from untrusted serialised data."""
        from lea.audit.serialisation import audit_event_from_dict

        return audit_event_from_dict(data)


def validate_audit_event_data(data: Mapping[str, object]) -> None:
    """Validate the top-level shape of serialised audit-event data."""
    schema_version = data.get("schema_version")
    if schema_version == LEGACY_AUDIT_SCHEMA_VERSION:
        expected_fields = AUDIT_EVENT_FIELDS_V1
    elif schema_version == AUDIT_SCHEMA_VERSION:
        expected_fields = AUDIT_EVENT_FIELDS_V2
    else:
        raise ActionContractError("Unsupported audit schema version.")

    supplied_fields = set(data)
    missing_fields = expected_fields - supplied_fields
    if missing_fields:
        missing = ", ".join(sorted(missing_fields))
        raise ActionContractError(
            f"Audit event data is missing required fields: {missing}."
        )
    unknown_fields = supplied_fields - expected_fields
    if unknown_fields:
        unknown = ", ".join(sorted(unknown_fields))
        raise ActionContractError(
            f"Audit event data contains unknown fields: {unknown}."
        )

    string_fields = ["event_id", "event_type", "occurred_at"]
    if schema_version == LEGACY_AUDIT_SCHEMA_VERSION:
        string_fields.append("proposal_id")
    else:
        string_fields.extend(("subject_type", "subject_id"))
    for field_name in string_fields:
        if not isinstance(data[field_name], str):
            raise ActionContractError(f"{field_name} must be a string.")
    if not isinstance(data["payload"], Mapping):
        raise ActionContractError("payload must be a mapping.")


def _validate_uuid(value: str, *, field_name: str) -> None:
    """Validate a canonical lower-case UUID string."""
    try:
        parsed_identifier = UUID(value)
    except (TypeError, ValueError) as error:
        raise ActionContractError(f"{field_name} must be a valid UUID.") from error
    if str(parsed_identifier) != value:
        raise ActionContractError(
            f"{field_name} must use canonical lower-case UUID format."
        )


def cast_payload(value: object) -> Mapping[str, object]:
    """Return a payload already validated as a mapping."""
    return cast(Mapping[str, object], value)
