"""Tests for strict Telegram update parsing."""

from dataclasses import FrozenInstanceError

import pytest

from lea.adapters.telegram import (
    TelegramParsedCallback,
    TelegramParsedMessage,
    TelegramUpdate,
    TelegramUpdateKind,
    TelegramUpdateParseIssue,
    TelegramUpdateParseResult,
    parse_telegram_update,
)


def _message_update(
    *,
    text: object = "/status",
    chat_type: str = "private",
    user_id: object = 123456789,
    chat_id: object = 123456789,
) -> TelegramUpdate:
    return TelegramUpdate(
        update_id=10,
        payload={
            "message": {
                "message_id": 7,
                "from": {
                    "id": user_id,
                    "first_name": "Owner",
                    "last_name": "Example",
                    "username": "owner_example",
                },
                "chat": {
                    "id": chat_id,
                    "type": chat_type,
                },
                "text": text,
            }
        },
    )


def _callback_update(
    *,
    data: object = "proposal.approve:abc",
    chat_type: str = "private",
) -> TelegramUpdate:
    return TelegramUpdate(
        update_id=11,
        payload={
            "callback_query": {
                "id": "callback-1",
                "from": {
                    "id": 123456789,
                    "first_name": "Owner",
                },
                "message": {
                    "message_id": 8,
                    "chat": {
                        "id": 123456789,
                        "type": chat_type,
                    },
                },
                "data": data,
            }
        },
    )


def test_private_command_message_is_parsed() -> None:
    result = parse_telegram_update(_message_update())

    assert result.success is True
    assert result.kind is TelegramUpdateKind.PRIVATE_COMMAND
    assert result.message is not None
    assert result.callback is None
    assert result.message.user_id == "123456789"
    assert result.message.chat_id == "123456789"
    assert result.message.text == "/status"
    assert result.message.username == "owner_example"


def test_callback_query_is_parsed() -> None:
    result = parse_telegram_update(_callback_update())

    assert result.success is True
    assert result.kind is TelegramUpdateKind.CALLBACK_QUERY
    assert result.callback is not None
    assert result.message is None
    assert result.callback.callback_query_id == "callback-1"
    assert result.callback.message_id == 8


@pytest.mark.parametrize("chat_type", ["group", "supergroup", "channel"])
def test_non_private_message_is_rejected(chat_type: str) -> None:
    result = parse_telegram_update(_message_update(chat_type=chat_type))

    assert result.success is False
    assert result.issues[0].code == "telegram_chat_not_private"


@pytest.mark.parametrize("chat_type", ["group", "supergroup", "channel"])
def test_non_private_callback_is_rejected(chat_type: str) -> None:
    result = parse_telegram_update(_callback_update(chat_type=chat_type))

    assert result.success is False
    assert result.issues[0].code == "telegram_chat_not_private"


def test_ordinary_text_is_not_a_command() -> None:
    result = parse_telegram_update(_message_update(text="hello"))

    assert result.success is False
    assert result.issues[0].code == "telegram_message_not_command"


def test_media_only_message_is_rejected() -> None:
    update = _message_update()
    payload = {
        "message": {
            "message_id": 7,
            "from": {"id": 123456789},
            "chat": {"id": 123456789, "type": "private"},
            "photo": [{"file_id": "photo"}],
        }
    }

    result = parse_telegram_update(
        TelegramUpdate(update_id=update.update_id, payload=payload)
    )

    assert result.success is False
    assert result.issues[0].code == "telegram_message_unsupported"


def test_unsupported_update_type_is_rejected() -> None:
    result = parse_telegram_update(
        TelegramUpdate(
            update_id=12,
            payload={"edited_message": {}},
        )
    )

    assert result.success is False
    assert result.issues[0].code == "telegram_update_unsupported"


def test_ambiguous_supported_update_is_rejected() -> None:
    result = parse_telegram_update(
        TelegramUpdate(
            update_id=12,
            payload={
                "message": {},
                "callback_query": {},
            },
        )
    )

    assert result.success is False
    assert result.issues[0].code == "telegram_update_ambiguous"


@pytest.mark.parametrize("value", [0, -1, True, "01", "user"])
def test_invalid_message_user_identifier_is_rejected(value: object) -> None:
    result = parse_telegram_update(_message_update(user_id=value))

    assert result.success is False
    assert result.issues[0].code == "telegram_identifier_invalid"


@pytest.mark.parametrize("value", [0, -1, True, "01", "chat"])
def test_invalid_message_chat_identifier_is_rejected(value: object) -> None:
    result = parse_telegram_update(_message_update(chat_id=value))

    assert result.success is False
    assert result.issues[0].code == "telegram_identifier_invalid"


def test_callback_without_message_is_rejected() -> None:
    result = parse_telegram_update(
        TelegramUpdate(
            update_id=12,
            payload={
                "callback_query": {
                    "id": "callback-1",
                    "from": {"id": 123456789},
                    "data": "approve",
                }
            },
        )
    )

    assert result.success is False
    assert result.issues[0].code == "telegram_callback_message_missing"


def test_callback_without_data_is_rejected() -> None:
    result = parse_telegram_update(_callback_update(data=None))

    assert result.success is False
    assert result.issues[0].code == "telegram_callback_data_missing"


def test_usernames_do_not_affect_numeric_identity() -> None:
    update = TelegramUpdate(
        update_id=13,
        payload={
            "message": {
                "message_id": 7,
                "from": {
                    "id": 123456789,
                    "username": "different_name",
                },
                "chat": {
                    "id": 123456789,
                    "type": "private",
                    "username": "ignored_chat_name",
                },
                "text": "/status",
            }
        },
    )

    result = parse_telegram_update(update)

    assert result.success is True
    assert result.message is not None
    assert result.message.user_id == "123456789"
    assert result.message.chat_id == "123456789"
    assert result.message.username == "different_name"


def test_parse_result_consistency() -> None:
    issue = TelegramUpdateParseIssue(
        code="invalid",
        message="Invalid update.",
    )

    with pytest.raises(ValueError, match="must contain a kind"):
        TelegramUpdateParseResult(
            success=True,
            kind=None,
            message=TelegramParsedMessage(
                update_id=1,
                message_id=1,
                user_id="1",
                chat_id="1",
                text="/status",
            ),
            callback=None,
            issues=(),
        )

    with pytest.raises(ValueError, match="must not contain parsed data"):
        TelegramUpdateParseResult(
            success=False,
            kind=None,
            message=TelegramParsedMessage(
                update_id=1,
                message_id=1,
                user_id="1",
                chat_id="1",
                text="/status",
            ),
            callback=None,
            issues=(issue,),
        )


@pytest.mark.parametrize(
    ("factory", "field_name"),
    [
        (
            lambda: TelegramParsedMessage(
                update_id=1,
                message_id=1,
                user_id="1",
                chat_id="1",
                text="/status",
            ),
            "text",
        ),
        (
            lambda: TelegramParsedCallback(
                update_id=1,
                callback_query_id="callback",
                user_id="1",
                chat_id="1",
                message_id=1,
                data="approve",
            ),
            "data",
        ),
        (
            lambda: TelegramUpdateParseIssue(
                code="invalid",
                message="Invalid update.",
            ),
            "code",
        ),
    ],
)
def test_parser_contracts_are_immutable(
    factory: object,
    field_name: str,
) -> None:
    value = factory()  # type: ignore[operator]

    with pytest.raises(FrozenInstanceError):
        setattr(value, field_name, "changed")
