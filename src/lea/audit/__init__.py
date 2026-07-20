from lea.audit.errors import AuditStoreError
from lea.audit.events import (
    AUDIT_SCHEMA_VERSION,
    AuditEvent,
    AuditEventType,
    generate_event_id,
)
from lea.audit.factories import (
    audit_action_execution,
    audit_confirmation_decision_application,
    audit_confirmation_evaluation,
    audit_confirmation_policy_application,
    audit_confirmation_record,
    audit_proposal_created,
    audit_transition_result,
    audit_validation_completed,
)
from lea.audit.integrity import (
    HASH_ALGORITHM,
    INTEGRITY_VERSION,
    AuditIntegrityIssue,
    AuditIntegrityVerificationResult,
    IntegrityEnvelope,
    calculate_event_hash,
    canonical_integrity_bytes,
    canonical_integrity_input,
    create_integrity_envelope,
    integrity_envelope_from_dict,
    integrity_envelope_to_dict,
    validate_sha256_hash,
)
from lea.audit.integrity_store import IntegrityJsonlAuditStore
from lea.audit.serialisation import (
    audit_event_from_dict,
    audit_event_to_dict,
)
from lea.audit.store import JsonlAuditStore
from lea.audit.verification import verify_integrity_chain

__all__ = [
    "AUDIT_SCHEMA_VERSION",
    "HASH_ALGORITHM",
    "INTEGRITY_VERSION",
    "AuditEvent",
    "AuditEventType",
    "AuditIntegrityIssue",
    "AuditIntegrityVerificationResult",
    "AuditStoreError",
    "IntegrityEnvelope",
    "IntegrityJsonlAuditStore",
    "JsonlAuditStore",
    "audit_action_execution",
    "audit_confirmation_decision_application",
    "audit_confirmation_evaluation",
    "audit_confirmation_policy_application",
    "audit_confirmation_record",
    "audit_event_from_dict",
    "audit_event_to_dict",
    "audit_proposal_created",
    "audit_transition_result",
    "audit_validation_completed",
    "calculate_event_hash",
    "canonical_integrity_bytes",
    "canonical_integrity_input",
    "create_integrity_envelope",
    "generate_event_id",
    "integrity_envelope_from_dict",
    "integrity_envelope_to_dict",
    "validate_sha256_hash",
    "verify_integrity_chain",
]
