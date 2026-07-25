"""Production Telegram Bot API client for guided onboarding."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from lea.adapters.telegram import (
    TelegramFetchUpdatesResult,
    TelegramTransportIssue,
)
from lea.adapters.telegram.bot_api import (
    TelegramBotApiConfig,
    TelegramBotApiTransport,
)
from lea.installers.release_candidate.telegram_onboarding import (
    TelegramBotIdentity,
    TelegramBotValidationResult,
    TelegramOnboardingIssue,
)


class TelegramOnboardingTransport(Protocol):
    """Minimal Bot API transport required during guided onboarding."""

    def get_bot(
        self,
    ) -> Mapping[str, object] | TelegramTransportIssue:
        """Fetch the current bot identity through Telegram getMe."""
        ...

    def fetch_updates(
        self,
        *,
        offset: int | None,
        limit: int,
        timeout_seconds: int,
    ) -> TelegramFetchUpdatesResult:
        """Fetch one bounded update batch."""
        ...


TelegramOnboardingTransportFactory = Callable[
    [str],
    TelegramOnboardingTransport,
]


class BotApiTelegramOnboardingClient:
    """Token-scoped onboarding client backed by the bounded Bot API transport."""

    def __init__(
        self,
        transport_factory: TelegramOnboardingTransportFactory | None = None,
    ) -> None:
        """Construct the client without retaining a Telegram bot token."""
        self._transport_factory = transport_factory or _create_bot_api_transport

    def validate_bot_token(
        self,
        token: str,
    ) -> TelegramBotValidationResult:
        """Validate one token through Telegram getMe."""
        try:
            result = self._transport_factory(token).get_bot()
        except Exception:
            return _bot_failure(
                code="telegram_get_me_failed",
                message="Telegram bot identity validation failed.",
            )

        if isinstance(result, TelegramTransportIssue):
            return _bot_failure(
                code="telegram_get_me_failed",
                message="Telegram bot identity validation failed.",
            )

        bot = _parse_bot_identity(result)
        if bot is None:
            return _bot_failure(
                code="telegram_get_me_invalid",
                message="Telegram returned an invalid bot identity.",
            )

        return TelegramBotValidationResult(
            success=True,
            bot=bot,
            issues=(),
        )

    def fetch_updates(
        self,
        token: str,
        *,
        offset: int | None,
        limit: int,
        timeout_seconds: int,
    ) -> TelegramFetchUpdatesResult:
        """Fetch updates without retaining the supplied token."""
        try:
            transport = self._transport_factory(token)
            return transport.fetch_updates(
                offset=offset,
                limit=limit,
                timeout_seconds=timeout_seconds,
            )
        except Exception:
            return TelegramFetchUpdatesResult(
                success=False,
                updates=(),
                issues=(
                    TelegramTransportIssue(
                        code="telegram_onboarding_transport_failed",
                        message=(
                            "Telegram updates could not be fetched during onboarding."
                        ),
                        operation="fetch_updates",
                    ),
                ),
            )


def _create_bot_api_transport(
    token: str,
) -> TelegramBotApiTransport:
    return TelegramBotApiTransport(TelegramBotApiConfig(token=token))


def _parse_bot_identity(
    data: Mapping[str, object],
) -> TelegramBotIdentity | None:
    if data.get("is_bot") is not True:
        return None

    bot_id = _identifier(data.get("id"))
    username = data.get("username")
    first_name = data.get("first_name")
    last_name = data.get("last_name")

    if (
        bot_id is None
        or not isinstance(username, str)
        or not username.strip()
        or username.startswith("@")
        or not isinstance(first_name, str)
        or not first_name.strip()
    ):
        return None

    display_parts = [first_name.strip()]
    if isinstance(last_name, str) and last_name.strip():
        display_parts.append(last_name.strip())

    try:
        return TelegramBotIdentity(
            bot_id=bot_id,
            username=username.strip(),
            display_name=" ".join(display_parts),
        )
    except (TypeError, ValueError):
        return None


def _identifier(value: object) -> str | None:
    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        return None

    if (
        not text.isascii()
        or not text.isdecimal()
        or text.startswith("0")
        or int(text) < 1
    ):
        return None

    return text


def _bot_failure(
    *,
    code: str,
    message: str,
) -> TelegramBotValidationResult:
    return TelegramBotValidationResult(
        success=False,
        bot=None,
        issues=(
            TelegramOnboardingIssue(
                code=code,
                message=message,
                operation="get_me",
            ),
        ),
    )
