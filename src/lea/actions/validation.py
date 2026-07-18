"""Deterministic validation for untrusted action proposal data."""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from lea.actions.enums import (
    ActionStatus,
    ConfirmationPolicy,
    RiskLevel,
)

ACTION_NAME_PATTERN = re.compile(r"^[a-z0-9_]+(?:\.[a-z0-9_]+)+$")

SCHEMA_VERSION = 1

REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "proposal_id",
        "action",
        "parameters",
        "status",
        "risk_level",
        "confirmation_policy",
        "source",
        "created_at",
        "reason",
    }
)

KNOWN_FIELDS = REQUIRED_FIELDS


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One deterministic problem found in proposal data."""

    code: str
    message: str
    field: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Immutable result of validating untrusted proposal data."""

    valid: bool
    issues: tuple[ValidationIssue, ...]

    def __post_init__(self) -> None:
        """Enforce consistency between validity and issue count."""
        if self.valid and self.issues:
            raise ValueError("A valid validation result must not contain issues.")

        if not self.valid and not self.issues:
            raise ValueError(
                "An invalid validation result must contain at least one issue."
            )


def validate_proposal_data(
    data: Mapping[str, object],
) -> ValidationResult:
    """Validate untrusted proposal data without mutating it."""
    issues: list[ValidationIssue] = []

    _validate_fields(data, issues)
    _validate_schema_version(data.get("schema_version"), issues)
    _validate_proposal_id(data.get("proposal_id"), issues)
    _validate_action(data.get("action"), issues)
    _validate_parameters(data.get("parameters"), issues)
    _validate_enum(
        data.get("status"),
        ActionStatus,
        "status",
        "invalid_status",
        issues,
    )
    _validate_enum(
        data.get("risk_level"),
        RiskLevel,
        "risk_level",
        "invalid_risk_level",
        issues,
    )
    _validate_enum(
        data.get("confirmation_policy"),
        ConfirmationPolicy,
        "confirmation_policy",
        "invalid_confirmation_policy",
        issues,
    )
    _validate_source(data.get("source"), issues)
    _validate_created_at(data.get("created_at"), issues)
    _validate_reason(data.get("reason"), issues)

    return ValidationResult(
        valid=not issues,
        issues=tuple(issues),
    )


def _validate_fields(
    data: Mapping[str, object],
    issues: list[ValidationIssue],
) -> None:
    """Validate required and unknown top-level fields."""
    missing_fields = sorted(REQUIRED_FIELDS - data.keys())

    for field in missing_fields:
        issues.append(
            ValidationIssue(
                code="missing_field",
                field=field,
                message=f"Required field '{field}' is missing.",
            )
        )

    unknown_fields = sorted(data.keys() - KNOWN_FIELDS)

    for field in unknown_fields:
        issues.append(
            ValidationIssue(
                code="unknown_field",
                field=field,
                message=f"Unknown field '{field}' is not permitted.",
            )
        )


def _validate_schema_version(
    value: object,
    issues: list[ValidationIssue],
) -> None:
    """Validate the proposal schema version."""
    if value is None:
        return

    if value != SCHEMA_VERSION:
        issues.append(
            ValidationIssue(
                code="unsupported_schema_version",
                field="schema_version",
                message=(f"schema_version must be {SCHEMA_VERSION}."),
            )
        )


def _validate_proposal_id(
    value: object,
    issues: list[ValidationIssue],
) -> None:
    """Validate canonical UUID proposal identifiers."""
    if value is None:
        return

    if not isinstance(value, str):
        issues.append(
            ValidationIssue(
                code="invalid_proposal_id",
                field="proposal_id",
                message="proposal_id must be a canonical UUID string.",
            )
        )
        return

    try:
        parsed_identifier = UUID(value)
    except ValueError:
        issues.append(
            ValidationIssue(
                code="invalid_proposal_id",
                field="proposal_id",
                message="proposal_id must be a valid UUID.",
            )
        )
        return

    if str(parsed_identifier) != value:
        issues.append(
            ValidationIssue(
                code="invalid_proposal_id",
                field="proposal_id",
                message=("proposal_id must use canonical lower-case UUID format."),
            )
        )


def _validate_action(
    value: object,
    issues: list[ValidationIssue],
) -> None:
    """Validate the namespaced action identifier."""
    if value is None:
        return

    if not isinstance(value, str):
        issues.append(
            ValidationIssue(
                code="invalid_action_name",
                field="action",
                message="action must be a string.",
            )
        )
        return

    if ACTION_NAME_PATTERN.fullmatch(value) is None:
        issues.append(
            ValidationIssue(
                code="invalid_action_name",
                field="action",
                message=(
                    "action must use a lower-case namespaced identifier "
                    "such as 'task.create'."
                ),
            )
        )


def _validate_parameters(
    value: object,
    issues: list[ValidationIssue],
) -> None:
    """Validate JSON-compatible action parameters."""
    if value is None:
        return

    if not isinstance(value, Mapping):
        issues.append(
            ValidationIssue(
                code="invalid_parameters",
                field="parameters",
                message="parameters must be a mapping.",
            )
        )
        return

    _validate_json_value(value, "parameters", issues)


def _validate_json_value(
    value: object,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    """Validate one nested JSON-compatible value."""
    if value is None or isinstance(value, (str, bool, int)):
        return

    if isinstance(value, float):
        if not math.isfinite(value):
            issues.append(
                ValidationIssue(
                    code="non_finite_number",
                    field=path,
                    message=f"{path} must not contain non-finite numbers.",
                )
            )
        return

    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(
                item,
                f"{path}[{index}]",
                issues,
            )
        return

    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                issues.append(
                    ValidationIssue(
                        code="invalid_mapping_key",
                        field=path,
                        message=(f"{path} must contain only string mapping keys."),
                    )
                )
                continue

            _validate_json_value(
                item,
                f"{path}.{key}",
                issues,
            )
        return

    issues.append(
        ValidationIssue(
            code="unsupported_parameter_value",
            field=path,
            message=(
                f"{path} contains an unsupported value of type {type(value).__name__}."
            ),
        )
    )


def _validate_enum(
    value: object,
    enum_type: type[ActionStatus] | type[RiskLevel] | type[ConfirmationPolicy],
    field: str,
    code: str,
    issues: list[ValidationIssue],
) -> None:
    """Validate one serialised enum value."""
    if value is None:
        return

    if not isinstance(value, str):
        issues.append(
            ValidationIssue(
                code=code,
                field=field,
                message=f"{field} must be a string.",
            )
        )
        return

    try:
        enum_type(value)
    except ValueError:
        supported = ", ".join(item.value for item in enum_type)
        issues.append(
            ValidationIssue(
                code=code,
                field=field,
                message=(f"{field} must be one of: {supported}."),
            )
        )


def _validate_source(
    value: object,
    issues: list[ValidationIssue],
) -> None:
    """Validate the proposal source."""
    if value is None:
        return

    if not isinstance(value, str) or not value.strip():
        issues.append(
            ValidationIssue(
                code="invalid_source",
                field="source",
                message="source must be a non-empty string.",
            )
        )


def _validate_created_at(
    value: object,
    issues: list[ValidationIssue],
) -> None:
    """Validate a timezone-aware ISO 8601 creation timestamp."""
    if value is None:
        return

    if not isinstance(value, str):
        issues.append(
            ValidationIssue(
                code="invalid_created_at",
                field="created_at",
                message="created_at must be an ISO 8601 string.",
            )
        )
        return

    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        issues.append(
            ValidationIssue(
                code="invalid_created_at",
                field="created_at",
                message="created_at must be a valid ISO 8601 timestamp.",
            )
        )
        return

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        issues.append(
            ValidationIssue(
                code="invalid_created_at",
                field="created_at",
                message="created_at must be timezone-aware.",
            )
        )


def _validate_reason(
    value: object,
    issues: list[ValidationIssue],
) -> None:
    """Validate the optional human-readable reason."""
    if value is None:
        return

    if not isinstance(value, str):
        issues.append(
            ValidationIssue(
                code="invalid_reason",
                field="reason",
                message="reason must be a string or null.",
            )
        )
