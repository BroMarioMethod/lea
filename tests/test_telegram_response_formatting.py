"""Tests for safe deterministic Telegram response formatting."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from lea.adapters.telegram import (
    TELEGRAM_MAX_MESSAGE_TEXT_LENGTH,
    TelegramFormattedResponse,
    TelegramResponseFormattingIssue,
    TelegramResponseFormattingResult,
    format_telegram_response,
)
from lea.channels import (
    ChannelControl,
    ChannelControlType,
    ChannelIssue,
    ChannelResponse,
    ChannelResponseOutcome,
)

REQUEST_ID = "11111111-1111-4111-8111-111111111111"
CONTROL_ID = "22222222-2222-4222-8222-222222222222"
PROPOSAL_ID = "33333333-3333-4333-8333-333333333333"
NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


def _response(
    *,
    outcome: ChannelResponseOutcome = ChannelResponseOutcome.SUCCEEDED,
    message: str = "Operation completed.",
    data: dict[str, object] | None = None,
    controls: tuple[ChannelControl, ...] = (),
    issue: ChannelIssue | None = None,
) -> ChannelResponse:
    return ChannelResponse(
        request_id=REQUEST_ID,
        outcome=outcome,
        message=message,
        responded_at=NOW,
        data=data,
        controls=controls,
        issue=issue,
    )


def _approve_control() -> ChannelControl:
    return ChannelControl(
        control_id=CONTROL_ID,
        label="Approve",
        control_type=ChannelControlType.ACTION,
        action="proposal.approve",
        parameters={"proposal_id": PROPOSAL_ID},
        required_capability="Proposals.Confirm",
    )


@pytest.mark.parametrize(
    ("outcome", "heading"),
    [
        (ChannelResponseOutcome.SUCCEEDED, "Succeeded"),
        (ChannelResponseOutcome.REJECTED, "Rejected"),
        (ChannelResponseOutcome.NOT_AUTHORISED, "Not authorised"),
        (ChannelResponseOutcome.VALIDATION_FAILED, "Validation failed"),
        (ChannelResponseOutcome.NOT_FOUND, "Not found"),
        (ChannelResponseOutcome.CONFLICT, "Conflict"),
        (ChannelResponseOutcome.APPLICATION_FAILED, "Application failed"),
        (
            ChannelResponseOutcome.TEMPORARILY_UNAVAILABLE,
            "Temporarily unavailable",
        ),
    ],
)
def test_outcome_heading_is_stable(
    outcome: ChannelResponseOutcome,
    heading: str,
) -> None:
    issue = (
        None
        if outcome is ChannelResponseOutcome.SUCCEEDED
        else ChannelIssue(code="failed", message="The operation failed.")
    )

    result = format_telegram_response(_response(outcome=outcome, issue=issue))

    assert result.success is True
    assert result.formatted is not None
    assert result.formatted.text.startswith(f"{heading}\n")


def test_formatter_uses_plain_text_without_markup() -> None:
    result = format_telegram_response(
        _response(message="Use *literal* <tags> and _underscores_.")
    )

    assert result.formatted is not None
    assert "*literal*" in result.formatted.text
    assert "<tags>" in result.formatted.text
    assert "_underscores_" in result.formatted.text


def test_structured_data_uses_sorted_stable_lines() -> None:
    result = format_telegram_response(
        _response(
            data={
                "zeta": 2,
                "alpha": {
                    "enabled": True,
                    "items": ["one", "two"],
                },
            }
        )
    )

    assert result.formatted is not None
    text = result.formatted.text
    assert text.index("  alpha:") < text.index("  zeta: 2")
    assert "    enabled: yes" in text
    assert "      - one" in text
    assert "      - two" in text


def test_issue_is_rendered_from_safe_channel_issue_fields() -> None:
    result = format_telegram_response(
        _response(
            outcome=ChannelResponseOutcome.VALIDATION_FAILED,
            message="The request was not valid.",
            issue=ChannelIssue(
                code="invalid_field",
                message="A required value is missing.",
                field="description",
            ),
        )
    )

    assert result.formatted is not None
    assert "Issue:" in result.formatted.text
    assert "Code: invalid_field" in result.formatted.text
    assert "Message: A required value is missing." in result.formatted.text
    assert "Field: description" in result.formatted.text


def test_keyboard_is_built_from_channel_controls() -> None:
    result = format_telegram_response(_response(controls=(_approve_control(),)))

    assert result.success is True
    assert result.formatted is not None
    assert result.formatted.keyboard is not None
    assert (
        result.formatted.keyboard.rows[0][0].callback_data
        == f"proposal.approve:{PROPOSAL_ID}"
    )


def test_keyboard_is_omitted_without_controls() -> None:
    result = format_telegram_response(_response())

    assert result.formatted is not None
    assert result.formatted.keyboard is None


def test_invalid_controls_fail_without_partial_output() -> None:
    invalid = ChannelControl(
        control_id=CONTROL_ID,
        label="Execute",
        control_type=ChannelControlType.ACTION,
        action="proposal.execute",
        parameters={"proposal_id": PROPOSAL_ID},
        required_capability="Proposals.Execute.LowRisk",
    )

    result = format_telegram_response(_response(controls=(invalid,)))

    assert result.success is False
    assert result.formatted is None
    assert result.issues[0].code == "telegram_response_controls_invalid"


def test_sensitive_keys_and_paths_are_redacted() -> None:
    result = format_telegram_response(
        _response(
            data={
                "token": "secret-value",
                "config_path": "/etc/lea/lea.toml",
                "ordinary": "/opt/lea/private.txt",
                "safe": "available",
            }
        )
    )

    assert result.formatted is not None
    text = result.formatted.text
    assert "secret-value" not in text
    assert "/etc/lea/lea.toml" not in text
    assert "/opt/lea/private.txt" not in text
    assert "safe: available" in text
    assert text.count("[redacted]") == 3


def test_multiline_values_are_collapsed_to_one_safe_line() -> None:
    result = format_telegram_response(
        _response(
            message="First line\nSecond line",
            data={"value": "one\n two\tthree"},
        )
    )

    assert result.formatted is not None
    assert "First line Second line" in result.formatted.text
    assert "value: one two three" in result.formatted.text


def test_oversized_output_is_truncated_to_telegram_limit() -> None:
    result = format_telegram_response(
        _response(
            message="A" * 4096,
            data={"extra": "B" * 100},
        )
    )

    assert result.formatted is not None
    assert len(result.formatted.text) == TELEGRAM_MAX_MESSAGE_TEXT_LENGTH
    assert result.formatted.text.endswith("[Response truncated]")


def test_result_contracts_enforce_consistency() -> None:
    issue = TelegramResponseFormattingIssue(
        code="invalid",
        message="Invalid response.",
    )

    with pytest.raises(ValueError, match="must contain output"):
        TelegramResponseFormattingResult(
            success=True,
            formatted=None,
            issues=(),
        )

    with pytest.raises(ValueError, match="at least one issue"):
        TelegramResponseFormattingResult(
            success=False,
            formatted=None,
            issues=(),
        )

    with pytest.raises(ValueError, match="must not contain output"):
        TelegramResponseFormattingResult(
            success=False,
            formatted=TelegramFormattedResponse(
                text="Done.",
                keyboard=None,
            ),
            issues=(issue,),
        )


@pytest.mark.parametrize(
    ("factory", "field_name"),
    [
        (
            lambda: TelegramFormattedResponse(
                text="Done.",
                keyboard=None,
            ),
            "text",
        ),
        (
            lambda: TelegramResponseFormattingIssue(
                code="invalid",
                message="Invalid response.",
            ),
            "code",
        ),
    ],
)
def test_formatting_contracts_are_immutable(
    factory: object,
    field_name: str,
) -> None:
    value = factory()  # type: ignore[operator]

    with pytest.raises(FrozenInstanceError):
        setattr(value, field_name, "changed")
