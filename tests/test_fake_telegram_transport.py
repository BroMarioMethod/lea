"""Tests for the deterministic fake Telegram transport."""

import pytest

from lea.adapters.telegram import (
    FakeTelegramTransport,
    TelegramAnswerCallbackResult,
    TelegramEditMessageResult,
    TelegramFetchUpdatesResult,
    TelegramInlineButton,
    TelegramInlineKeyboard,
    TelegramSendMessageResult,
    TelegramSentMessage,
    TelegramUpdate,
)


def _keyboard() -> TelegramInlineKeyboard:
    return TelegramInlineKeyboard(
        rows=(
            (
                TelegramInlineButton(
                    text="Approve",
                    callback_data="approve:1",
                ),
            ),
        )
    )


def test_fake_fetch_records_call_and_returns_queued_result() -> None:
    fake = FakeTelegramTransport()
    queued = TelegramFetchUpdatesResult(
        success=True,
        updates=(TelegramUpdate(update_id=4, payload={}),),
        issues=(),
    )
    fake.fetch_results.append(queued)

    result = fake.fetch_updates(offset=4, limit=50, timeout_seconds=30)

    assert result is queued
    assert fake.fetch_calls[0].offset == 4
    assert fake.fetch_calls[0].limit == 50
    assert fake.fetch_calls[0].timeout_seconds == 30


def test_fake_send_records_keyboard() -> None:
    fake = FakeTelegramTransport()
    queued = TelegramSendMessageResult(
        success=True,
        message=TelegramSentMessage(
            chat_id="123456789",
            message_id=8,
        ),
        issues=(),
    )
    fake.send_results.append(queued)
    keyboard = _keyboard()

    result = fake.send_message(
        chat_id="123456789",
        text="Confirm?",
        keyboard=keyboard,
    )

    assert result is queued
    assert fake.send_calls[0].keyboard is keyboard


def test_fake_callback_records_alert_flag() -> None:
    fake = FakeTelegramTransport()
    queued = TelegramAnswerCallbackResult(success=True, issues=())
    fake.answer_results.append(queued)

    result = fake.answer_callback_query(
        callback_query_id="callback-1",
        text="Done",
        show_alert=True,
    )

    assert result is queued
    assert fake.answer_calls[0].show_alert is True


def test_fake_edit_records_message_identity() -> None:
    fake = FakeTelegramTransport()
    queued = TelegramEditMessageResult(
        success=True,
        message=TelegramSentMessage(
            chat_id="123456789",
            message_id=8,
        ),
        issues=(),
    )
    fake.edit_results.append(queued)

    result = fake.edit_message(
        chat_id="123456789",
        message_id=8,
        text="Approved",
        keyboard=None,
    )

    assert result is queued
    assert fake.edit_calls[0].message_id == 8


def test_fake_requires_queued_result() -> None:
    fake = FakeTelegramTransport()

    with pytest.raises(RuntimeError, match="No fake Telegram result queued"):
        fake.fetch_updates(offset=None, limit=100, timeout_seconds=30)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"offset": -1, "limit": 100, "timeout_seconds": 30}, "offset"),
        ({"offset": None, "limit": 0, "timeout_seconds": 30}, "limit"),
        ({"offset": None, "limit": 101, "timeout_seconds": 30}, "limit"),
        ({"offset": None, "limit": 100, "timeout_seconds": 0}, "timeout"),
    ],
)
def test_fake_fetch_validates_arguments(
    kwargs: dict[str, object],
    message: str,
) -> None:
    fake = FakeTelegramTransport()

    with pytest.raises((TypeError, ValueError), match=message):
        fake.fetch_updates(**kwargs)  # type: ignore[arg-type]


def test_fake_send_rejects_oversized_text() -> None:
    fake = FakeTelegramTransport()

    with pytest.raises(ValueError, match="4096"):
        fake.send_message(
            chat_id="123456789",
            text="x" * 4097,
        )
