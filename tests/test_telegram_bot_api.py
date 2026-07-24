"""Tests for the concrete Telegram Bot API transport."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import cast
from urllib.request import Request

from lea.adapters.telegram.bot_api import (
    TelegramBotApiConfig,
    TelegramBotApiTransport,
    telegram_bot_api_transport,
)
from lea.adapters.telegram.contracts import (
    TelegramInlineButton,
    TelegramInlineKeyboard,
    TelegramTransport,
)


@dataclass
class FakeResponse:
    """Context-managed fake URL response."""

    payload: bytes

    def read(self, amount: int = -1) -> bytes:
        return self.payload if amount < 0 else self.payload[:amount]

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        return None


@dataclass
class FakeOpener:
    """Capture one request and return queued JSON payloads."""

    payloads: list[bytes]
    requests: list[Request] = field(default_factory=list)
    timeouts: list[int] = field(default_factory=list)

    def __call__(self, request: Request, *, timeout: int) -> FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        return FakeResponse(self.payloads.pop(0))


def _payload(result: object, *, ok: bool = True) -> bytes:
    return json.dumps({"ok": ok, "result": result}).encode("utf-8")


def _transport(opener: FakeOpener) -> TelegramBotApiTransport:
    return TelegramBotApiTransport(
        TelegramBotApiConfig(
            token="123456:abcdefghijklmnopqrstuvwxyz",
            request_timeout_seconds=45,
        ),
        opener=opener,
    )


def test_fetch_updates_maps_ordered_results() -> None:
    opener = FakeOpener(
        [
            _payload(
                [
                    {"update_id": 43, "message": {"message_id": 2}},
                    {"update_id": 42, "callback_query": {"id": "x"}},
                ]
            )
        ]
    )
    transport = _transport(opener)

    result = transport.fetch_updates(offset=42, limit=10, timeout_seconds=30)

    assert result.success is True
    assert tuple(update.update_id for update in result.updates) == (42, 43)
    assert opener.timeouts == [45]
    assert opener.requests[0].full_url.endswith("/getUpdates")
    assert b"offset=42" in cast(bytes, opener.requests[0].data)


def test_send_message_serialises_inline_keyboard() -> None:
    opener = FakeOpener(
        [
            _payload(
                {
                    "message_id": 99,
                    "chat": {"id": 123456789},
                }
            )
        ]
    )
    transport = _transport(opener)
    keyboard = TelegramInlineKeyboard(
        rows=(
            (
                TelegramInlineButton(
                    text="Approve",
                    callback_data="proposal.approve:123",
                ),
            ),
        )
    )

    result = transport.send_message(
        chat_id="123456789",
        text="Hello",
        keyboard=keyboard,
    )

    assert result.success is True
    assert result.message is not None
    assert result.message.message_id == 99
    data = cast(bytes, opener.requests[0].data)
    assert b"reply_markup=" in data
    assert opener.requests[0].full_url.endswith("/sendMessage")


def test_edit_message_maps_sent_message() -> None:
    opener = FakeOpener(
        [
            _payload(
                {
                    "message_id": 77,
                    "chat": {"id": 123456789},
                }
            )
        ]
    )

    result = _transport(opener).edit_message(
        chat_id="123456789",
        message_id=77,
        text="Updated",
    )

    assert result.success is True
    assert result.message is not None
    assert result.message.chat_id == "123456789"


def test_answer_callback_requires_true_result() -> None:
    opener = FakeOpener([_payload(True)])

    result = _transport(opener).answer_callback_query(callback_query_id="callback-1")

    assert result.success is True


def test_api_rejection_is_redacted() -> None:
    opener = FakeOpener(
        [
            json.dumps(
                {
                    "ok": False,
                    "description": "Bad token 123456:secret",
                }
            ).encode("utf-8")
        ]
    )

    result = _transport(opener).fetch_updates(
        offset=None,
        limit=10,
        timeout_seconds=30,
    )

    assert result.success is False
    assert result.issues[0].code == "telegram_api_rejected"
    assert "secret" not in result.issues[0].message


def test_oversized_response_is_rejected() -> None:
    opener = FakeOpener([b"x" * 65])
    transport = TelegramBotApiTransport(
        TelegramBotApiConfig(
            token="123456:abcdefghijklmnopqrstuvwxyz",
            maximum_response_bytes=64,
        ),
        opener=opener,
    )

    result = transport.fetch_updates(
        offset=None,
        limit=10,
        timeout_seconds=30,
    )

    assert result.success is False
    assert result.issues[0].code == "telegram_response_too_large"


def test_invalid_json_is_rejected() -> None:
    opener = FakeOpener([b"not-json"])

    result = _transport(opener).fetch_updates(
        offset=None,
        limit=10,
        timeout_seconds=30,
    )

    assert result.success is False
    assert result.issues[0].code == "telegram_response_invalid_json"


def test_default_factory_returns_transport_protocol() -> None:
    transport = telegram_bot_api_transport("123456:abcdefghijklmnopqrstuvwxyz")

    assert isinstance(transport, TelegramTransport)
