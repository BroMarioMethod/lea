"""Regression tests for Telegram help-command rendering."""

from datetime import UTC, datetime

from lea.adapters.telegram.formatting import format_telegram_response
from lea.channels import ChannelResponse, ChannelResponseOutcome

REQUEST_ID = "11111111-1111-4111-8111-111111111111"
NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def test_help_commands_are_visible_without_weakening_path_redaction() -> None:
    response = ChannelResponse(
        request_id=REQUEST_ID,
        outcome=ChannelResponseOutcome.SUCCEEDED,
        message="Supported commands.",
        responded_at=NOW,
        data={
            "commands": [
                "/help",
                "/task_show <task-uuid>",
            ],
            "location": "/etc/lea/lea.toml",
        },
    )

    result = format_telegram_response(response)

    assert result.success is True
    assert result.formatted is not None
    assert "  - /help" in result.formatted.text
    assert "  - /task_show <task-uuid>" in result.formatted.text
    assert "location: [redacted]" in result.formatted.text
