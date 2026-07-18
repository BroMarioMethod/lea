"""Enumerations used by the LEA action contract."""

from enum import StrEnum


class ActionStatus(StrEnum):
    """Lifecycle state of an action proposal."""

    PROPOSED = "proposed"
    VALIDATED = "validated"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RiskLevel(StrEnum):
    """Potential impact of executing an action."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConfirmationPolicy(StrEnum):
    """Interactive confirmation requirement for an action."""

    NEVER = "never"
    WHEN_REQUIRED = "when_required"
    ALWAYS = "always"
