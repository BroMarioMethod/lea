"""Tests for deterministic proposal-data validation."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from lea.actions import (
    ValidationIssue,
    ValidationResult,
    validate_proposal_data,
)

VALID_PROPOSAL_DATA: dict[str, object] = {
    "schema_version": 1,
    "proposal_id": "4b10f26d-0c54-4f3d-a14c-bce8a743116f",
    "action": "task.create",
    "parameters": {
        "description": "Call John",
        "tags": ["client", "follow_up"],
    },
    "status": "proposed",
    "risk_level": "medium",
    "confirmation_policy": "when_required",
    "source": "user",
    "created_at": datetime(
        2026,
        7,
        18,
        20,
        0,
        tzinfo=UTC,
    ).isoformat(),
    "reason": "The user requested a follow-up task.",
}


def test_valid_data_returns_valid_result() -> None:
    """Valid proposal data should produce no validation issues."""
    result = validate_proposal_data(VALID_PROPOSAL_DATA)

    assert result.valid is True
    assert result.issues == ()


def test_validation_collects_multiple_issues() -> None:
    """Independent proposal-data problems should be collected together."""
    data = dict(VALID_PROPOSAL_DATA)
    data.update(
        {
            "schema_version": 99,
            "proposal_id": "not-a-uuid",
            "action": "Task Create",
            "source": "   ",
            "created_at": "2026-07-18T20:00:00",
            "risk_level": "extreme",
        }
    )

    result = validate_proposal_data(data)
    codes = {issue.code for issue in result.issues}

    assert result.valid is False
    assert {
        "unsupported_schema_version",
        "invalid_proposal_id",
        "invalid_action_name",
        "invalid_source",
        "invalid_created_at",
        "invalid_risk_level",
    }.issubset(codes)


def test_validation_reports_missing_fields() -> None:
    """Missing required fields should be reported."""
    result = validate_proposal_data({})

    assert result.valid is False
    assert any(
        issue.code == "missing_field" and issue.field == "action"
        for issue in result.issues
    )


def test_validation_reports_unknown_fields() -> None:
    """Unknown top-level fields should be rejected."""
    data = dict(VALID_PROPOSAL_DATA)
    data["acton"] = "task.create"

    result = validate_proposal_data(data)

    assert any(
        issue.code == "unknown_field" and issue.field == "acton"
        for issue in result.issues
    )


def test_validation_rejects_non_finite_nested_number() -> None:
    """Nested non-finite numbers should be reported."""
    data = deepcopy(VALID_PROPOSAL_DATA)
    parameters = data["parameters"]
    assert isinstance(parameters, dict)
    parameters["score"] = float("nan")

    result = validate_proposal_data(data)

    assert any(
        issue.code == "non_finite_number" and issue.field == "parameters.score"
        for issue in result.issues
    )


def test_validation_rejects_unsupported_nested_value() -> None:
    """Nested unsupported parameter values should be reported."""
    data = deepcopy(VALID_PROPOSAL_DATA)
    parameters = data["parameters"]
    assert isinstance(parameters, dict)
    parameters["payload"] = b"bytes"

    result = validate_proposal_data(data)

    assert any(
        issue.code == "unsupported_parameter_value"
        and issue.field == "parameters.payload"
        for issue in result.issues
    )


def test_validation_does_not_mutate_input() -> None:
    """Validation should not modify supplied proposal data."""
    data = deepcopy(VALID_PROPOSAL_DATA)
    original = deepcopy(data)

    validate_proposal_data(data)

    assert data == original


def test_valid_result_rejects_issues() -> None:
    """A valid result must not contain validation issues."""
    issue = ValidationIssue(
        code="example",
        message="Example issue.",
    )

    with pytest.raises(
        ValueError,
        match="must not contain issues",
    ):
        ValidationResult(
            valid=True,
            issues=(issue,),
        )


def test_invalid_result_requires_issues() -> None:
    """An invalid result must contain at least one issue."""
    with pytest.raises(
        ValueError,
        match="must contain at least one issue",
    ):
        ValidationResult(
            valid=False,
            issues=(),
        )


def test_validation_issue_is_immutable() -> None:
    """Validation issues should be immutable records."""
    issue = ValidationIssue(
        code="example",
        message="Example issue.",
    )

    with pytest.raises(AttributeError):
        issue.code = "changed"  # type: ignore[misc]
