"""Tests for immutable Telegram transport contracts."""

from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest

from lea.adapters.telegram import (
    TELEGRAM_MAX_CALLBACK_DATA_BYTES,
    TELEGRAM_MAX_FETCH_LIMIT,
    TELEGRAM_MAX_MESSAGE_TEXT_LENGTH,
    TelegramAnswerCallbackResult,
    TelegramEditMessageResult,
    TelegramFetchUpdatesResult,
    TelegramInlineButton,
    TelegramInlineKeyboard,
    TelegramSendMessageResult,
    TelegramSentMessage,
    TelegramTransportIssue,
    TelegramUpdate,
)


def _issue(operation: str = "fetch_updates") -> TelegramTransportIssue:
    return TelegramTransportIssue(
        code="telegram_unavailable",
        message="Telegram is temporarily unavailable.",
        operation=operation,
    )


def _update(update_id: int = 1) -> TelegramUpdate:
    return TelegramUpdate(
        update_id=update_id,
        payload={"message": {"text": "/status"}},
    )


def _message() -> TelegramSentMessage:
    return TelegramSentMessage(chat_id="123456789", message_id=7)


def test_limits_match_supported_boundaries() -> None:
    assert TELEGRAM_MAX_CALLBACK_DATA_BYTES == 64
    assert TELEGRAM_MAX_FETCH_LIMIT == 100
    assert TELEGRAM_MAX_MESSAGE_TEXT_LENGTH == 4096


def test_update_payload_is_deeply_frozen() -> None:
    update = _update()

    assert isinstance(update.payload, MappingProxyType)
    assert isinstance(update.payload["message"], MappingProxyType)

    with pytest.raises(TypeError):
        update.payload["message"] = None  # type: ignore[index]


def test_update_rejects_non_json_payload() -> None:
    with pytest.raises(ValueError, match="JSON-compatible"):
        TelegramUpdate(update_id=1, payload={"invalid": object()})


@pytest.mark.parametrize("value", [0, -1])
def test_update_id_must_be_positive(value: int) -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        TelegramUpdate(update_id=value, payload={})


def test_keyboard_is_immutable_and_canonical() -> None:
    button = TelegramInlineButton(text="Approve", callback_data="approve:1")
    keyboard = TelegramInlineKeyboard(rows=[[button]])  # type: ignore[arg-type]

    assert keyboard.rows == ((button,),)

    with pytest.raises(FrozenInstanceError):
        keyboard.rows = ()  # type: ignore[misc]


def test_callback_data_is_bounded_by_utf8_bytes() -> None:
    with pytest.raises(ValueError, match="64 UTF-8 bytes"):
        TelegramInlineButton(
            text="Approve",
            callback_data="é" * 33,
        )


def test_fetch_result_orders_updates() -> None:
    result = TelegramFetchUpdatesResult(
        success=True,
        updates=(_update(3), _update(1), _update(2)),
        issues=(),
    )

    assert tuple(item.update_id for item in result.updates) == (1, 2, 3)


def test_fetch_result_rejects_duplicate_update_ids() -> None:
    with pytest.raises(ValueError, match="duplicate update IDs"):
        TelegramFetchUpdatesResult(
            success=True,
            updates=(_update(1), _update(1)),
            issues=(),
        )


def test_failed_fetch_requires_issue() -> None:
    with pytest.raises(ValueError, match="at least one issue"):
        TelegramFetchUpdatesResult(success=False, updates=(), issues=())


def test_send_result_consistency() -> None:
    result = TelegramSendMessageResult(
        success=True,
        message=_message(),
        issues=(),
    )

    assert result.message == _message()

    with pytest.raises(ValueError, match="must contain a value"):
        TelegramSendMessageResult(
            success=True,
            message=None,
            issues=(),
        )


def test_edit_result_consistency() -> None:
    with pytest.raises(ValueError, match="must not contain a value"):
        TelegramEditMessageResult(
            success=False,
            message=_message(),
            issues=(_issue("edit_message"),),
        )


def test_callback_result_consistency() -> None:
    with pytest.raises(ValueError, match="must not contain issues"):
        TelegramAnswerCallbackResult(
            success=True,
            issues=(_issue("answer_callback_query"),),
        )


@pytest.mark.parametrize(
    ("factory", "field_name"),
    [
        (_issue, "code"),
        (_update, "update_id"),
        (_message, "message_id"),
        (
            lambda: TelegramInlineButton(
                text="Approve",
                callback_data="approve:1",
            ),
            "text",
        ),
    ],
)
def test_contracts_are_immutable(
    factory: object,
    field_name: str,
) -> None:
    value = factory()  # type: ignore[operator]

    with pytest.raises(FrozenInstanceError):
        setattr(value, field_name, "changed")
