"""Tests for the production Telegram onboarding client."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Self
from urllib.request import Request

from lea.adapters.telegram import (
    TelegramBotApiConfig,
    TelegramBotApiTransport,
    TelegramFetchUpdatesResult,
    TelegramTransportIssue,
    TelegramUpdate,
)
from lea.installers.release_candidate import (
    BotApiTelegramOnboardingClient,
)

TOKEN = "123456789:abcdefghijklmnopqrstuvwxyz_ABCDEFG"


class Response:
    """Minimal context-managed HTTP response."""

    def __init__(self, payload: object) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self, amount: int = -1) -> bytes:
        return self._payload[:amount] if amount >= 0 else self._payload

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        return None


class FakeOnboardingTransport:
    """Deterministic getMe and update-fetch transport."""

    def __init__(
        self,
        *,
        bot: Mapping[str, object] | TelegramTransportIssue,
        fetched: TelegramFetchUpdatesResult | None = None,
    ) -> None:
        self.bot = bot
        self.fetched = fetched or TelegramFetchUpdatesResult(
            success=True,
            updates=(),
            issues=(),
        )
        self.fetch_calls: list[tuple[int | None, int, int]] = []

    def get_bot(
        self,
    ) -> Mapping[str, object] | TelegramTransportIssue:
        return self.bot

    def fetch_updates(
        self,
        *,
        offset: int | None,
        limit: int,
        timeout_seconds: int,
    ) -> TelegramFetchUpdatesResult:
        self.fetch_calls.append(
            (
                offset,
                limit,
                timeout_seconds,
            )
        )
        return self.fetched


def _bot_payload() -> Mapping[str, object]:
    return {
        "id": 987654321,
        "is_bot": True,
        "first_name": "LEA",
        "last_name": "Assistant",
        "username": "lea_test_bot",
    }


def test_bot_api_transport_get_bot_uses_get_me() -> None:
    urls: list[str] = []

    def open_request(request: Request, *, timeout: int) -> Response:
        urls.append(request.full_url)
        assert timeout == 60
        return Response(
            {
                "ok": True,
                "result": _bot_payload(),
            }
        )

    transport = TelegramBotApiTransport(
        TelegramBotApiConfig(token=TOKEN),
        opener=open_request,
    )

    result = transport.get_bot()

    assert result == _bot_payload()
    assert urls == [f"https://api.telegram.org/bot{TOKEN}/getMe"]


def test_client_parses_bot_identity_without_retaining_token() -> None:
    tokens: list[str] = []
    transport = FakeOnboardingTransport(bot=_bot_payload())

    def factory(token: str) -> FakeOnboardingTransport:
        tokens.append(token)
        return transport

    client = BotApiTelegramOnboardingClient(factory)
    result = client.validate_bot_token(TOKEN)

    assert result.success is True
    assert result.bot is not None
    assert result.bot.bot_id == "987654321"
    assert result.bot.username == "lea_test_bot"
    assert result.bot.display_name == "LEA Assistant"
    assert tokens == [TOKEN]
    assert TOKEN not in repr(client)
    assert TOKEN not in repr(result)


def test_client_rejects_non_bot_or_malformed_identity() -> None:
    client = BotApiTelegramOnboardingClient(
        lambda _token: FakeOnboardingTransport(
            bot={
                "id": 987654321,
                "is_bot": False,
                "first_name": "Not a bot",
                "username": "lea_test_bot",
            }
        )
    )

    result = client.validate_bot_token(TOKEN)

    assert result.success is False
    assert result.issues[0].code == "telegram_get_me_invalid"
    assert TOKEN not in result.issues[0].message


def test_transport_issue_is_replaced_with_token_safe_failure() -> None:
    client = BotApiTelegramOnboardingClient(
        lambda _token: FakeOnboardingTransport(
            bot=TelegramTransportIssue(
                code=f"failure-{TOKEN}",
                message=f"failed token={TOKEN}",
                operation="get_me",
            )
        )
    )

    result = client.validate_bot_token(TOKEN)

    assert result.success is False
    assert result.issues[0].code == "telegram_get_me_failed"
    assert TOKEN not in result.issues[0].code
    assert TOKEN not in result.issues[0].message


def test_fetch_updates_delegates_exact_arguments() -> None:
    update = TelegramUpdate(
        update_id=42,
        payload={
            "message": {
                "message_id": 7,
                "from": {
                    "id": 123456789,
                    "first_name": "Marius",
                },
                "chat": {
                    "id": 123456789,
                    "type": "private",
                },
                "text": "/start",
            }
        },
    )
    fetched = TelegramFetchUpdatesResult(
        success=True,
        updates=(update,),
        issues=(),
    )
    tokens: list[str] = []
    transport = FakeOnboardingTransport(
        bot=_bot_payload(),
        fetched=fetched,
    )

    def factory(token: str) -> FakeOnboardingTransport:
        tokens.append(token)
        return transport

    client = BotApiTelegramOnboardingClient(factory)
    result = client.fetch_updates(
        TOKEN,
        offset=40,
        limit=100,
        timeout_seconds=30,
    )

    assert result == fetched
    assert transport.fetch_calls == [(40, 100, 30)]
    assert tokens == [TOKEN]


def test_transport_construction_failure_is_redacted() -> None:
    def fail(token: str) -> FakeOnboardingTransport:
        raise RuntimeError(f"failed token={token}")

    client = BotApiTelegramOnboardingClient(fail)

    validation = client.validate_bot_token(TOKEN)
    fetched = client.fetch_updates(
        TOKEN,
        offset=None,
        limit=100,
        timeout_seconds=30,
    )

    assert validation.success is False
    assert fetched.success is False
    assert TOKEN not in validation.issues[0].message
    assert TOKEN not in fetched.issues[0].message
