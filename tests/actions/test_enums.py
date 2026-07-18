"""Tests for action-contract enumerations."""

from lea.actions import (
    ActionStatus,
    ConfirmationPolicy,
    RiskLevel,
)


def test_action_status_values_are_stable_strings() -> None:
    """Action lifecycle states should expose serialisable values."""
    assert ActionStatus.PROPOSED.value == "proposed"
    assert ActionStatus.AWAITING_CONFIRMATION.value == "awaiting_confirmation"
    assert ActionStatus.SUCCEEDED.value == "succeeded"


def test_risk_level_values_are_stable_strings() -> None:
    """Risk levels should expose serialisable values."""
    assert RiskLevel.LOW.value == "low"
    assert RiskLevel.MEDIUM.value == "medium"
    assert RiskLevel.CRITICAL.value == "critical"


def test_confirmation_policy_values_are_stable_strings() -> None:
    """Confirmation policies should expose serialisable values."""
    assert ConfirmationPolicy.NEVER.value == "never"
    assert ConfirmationPolicy.WHEN_REQUIRED.value == "when_required"
    assert ConfirmationPolicy.ALWAYS.value == "always"
