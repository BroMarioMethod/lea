"""Concrete Telegram Bot API transport using the Python standard library."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from lea.adapters.telegram.contracts import (
    TelegramAnswerCallbackResult,
    TelegramEditMessageResult,
    TelegramFetchUpdatesResult,
    TelegramInlineKeyboard,
    TelegramSendMessageResult,
    TelegramSentMessage,
    TelegramTransport,
    TelegramTransportIssue,
    TelegramUpdate,
    validate_callback_arguments,
    validate_edit_arguments,
    validate_fetch_arguments,
    validate_send_arguments,
)

_TELEGRAM_API_BASE = "https://api.telegram.org"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class TelegramHttpResponse(Protocol):
    """Minimal HTTP response boundary used by the Bot API transport."""

    def read(self, amount: int = -1) -> bytes:
        """Read response bytes."""
        ...

    def __enter__(self) -> TelegramHttpResponse:
        """Enter the response context."""
        ...

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> object:
        """Exit the response context."""
        ...


TelegramUrlOpener = Callable[..., TelegramHttpResponse]
"""Injected URL opener compatible with urllib.request.urlopen."""


@dataclass(frozen=True, slots=True)
class TelegramBotApiConfig:
    """Validated concrete Telegram Bot API transport configuration."""

    token: str
    api_base: str = _TELEGRAM_API_BASE
    request_timeout_seconds: int = 60
    maximum_response_bytes: int = _MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        """Validate non-secret transport settings."""
        if not self.token.strip():
            raise ValueError("Telegram Bot API token must be non-empty.")

        if not self.api_base.startswith("https://") or self.api_base.endswith("/"):
            raise ValueError(
                "Telegram Bot API base must use HTTPS and omit a trailing slash."
            )

        _positive_integer(
            self.request_timeout_seconds,
            field_name="request_timeout_seconds",
        )
        _positive_integer(
            self.maximum_response_bytes,
            field_name="maximum_response_bytes",
        )


class TelegramBotApiTransport(TelegramTransport):
    """Telegram Bot API implementation with bounded JSON responses."""

    def __init__(
        self,
        config: TelegramBotApiConfig,
        *,
        opener: TelegramUrlOpener = urlopen,
    ) -> None:
        """Construct one transport without performing network access."""
        self._config = config
        self._opener = opener

    def get_bot(
        self,
    ) -> Mapping[str, object] | TelegramTransportIssue:
        """Fetch the current bot identity through Telegram getMe."""
        result = self._call("getMe", {})

        if isinstance(result, TelegramTransportIssue):
            return result

        if not isinstance(result, Mapping):
            return _issue(
                "telegram_api_result_invalid",
                "Telegram returned an invalid bot identity result.",
                "get_me",
            )

        return cast(Mapping[str, object], result)

    def fetch_updates(
        self,
        *,
        offset: int | None,
        limit: int,
        timeout_seconds: int,
    ) -> TelegramFetchUpdatesResult:
        """Fetch one ordered long-poll batch."""
        validate_fetch_arguments(
            offset=offset,
            limit=limit,
            timeout_seconds=timeout_seconds,
        )
        parameters: dict[str, object] = {
            "allowed_updates": ["message", "callback_query"],
            "limit": limit,
            "timeout": timeout_seconds,
        }
        if offset is not None:
            parameters["offset"] = offset

        result = self._call("getUpdates", parameters)

        if isinstance(result, TelegramTransportIssue):
            return TelegramFetchUpdatesResult(False, (), (result,))

        if not isinstance(result, list):
            return TelegramFetchUpdatesResult(
                False,
                (),
                (
                    _issue(
                        "telegram_api_result_invalid",
                        "Telegram returned an invalid update result.",
                        "fetch_updates",
                    ),
                ),
            )

        updates: list[TelegramUpdate] = []

        try:
            for item in result:
                if not isinstance(item, Mapping):
                    raise ValueError
                data = cast(Mapping[str, object], item)
                update_id = data.get("update_id")
                if (
                    isinstance(update_id, bool)
                    or not isinstance(update_id, int)
                    or update_id < 1
                ):
                    raise ValueError
                updates.append(
                    TelegramUpdate(
                        update_id=update_id,
                        payload={
                            key: value
                            for key, value in data.items()
                            if key != "update_id"
                        },
                    )
                )
        except (TypeError, ValueError):
            return TelegramFetchUpdatesResult(
                False,
                (),
                (
                    _issue(
                        "telegram_api_update_invalid",
                        "Telegram returned a malformed update.",
                        "fetch_updates",
                    ),
                ),
            )

        return TelegramFetchUpdatesResult(True, tuple(updates), ())

    def send_message(
        self,
        *,
        chat_id: str,
        text: str,
        keyboard: TelegramInlineKeyboard | None = None,
    ) -> TelegramSendMessageResult:
        """Send one Telegram text message."""
        validate_send_arguments(chat_id=chat_id, text=text)
        parameters: dict[str, object] = {
            "chat_id": chat_id,
            "text": text,
        }
        if keyboard is not None:
            parameters["reply_markup"] = _keyboard_payload(keyboard)

        result = self._call("sendMessage", parameters)

        if isinstance(result, TelegramTransportIssue):
            return TelegramSendMessageResult(False, None, (result,))

        message = _sent_message(result, operation="send_message")
        if isinstance(message, TelegramTransportIssue):
            return TelegramSendMessageResult(False, None, (message,))

        return TelegramSendMessageResult(True, message, ())

    def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> TelegramAnswerCallbackResult:
        """Answer one callback query."""
        validate_callback_arguments(
            callback_query_id=callback_query_id,
            text=text,
        )
        parameters: dict[str, object] = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert,
        }
        if text is not None:
            parameters["text"] = text

        result = self._call("answerCallbackQuery", parameters)

        if isinstance(result, TelegramTransportIssue):
            return TelegramAnswerCallbackResult(False, (result,))

        if result is not True:
            return TelegramAnswerCallbackResult(
                False,
                (
                    _issue(
                        "telegram_api_result_invalid",
                        "Telegram returned an invalid callback result.",
                        "answer_callback_query",
                    ),
                ),
            )

        return TelegramAnswerCallbackResult(True, ())

    def edit_message(
        self,
        *,
        chat_id: str,
        message_id: int,
        text: str,
        keyboard: TelegramInlineKeyboard | None = None,
    ) -> TelegramEditMessageResult:
        """Edit one Telegram text message."""
        validate_edit_arguments(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
        )
        parameters: dict[str, object] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if keyboard is not None:
            parameters["reply_markup"] = _keyboard_payload(keyboard)

        result = self._call("editMessageText", parameters)

        if isinstance(result, TelegramTransportIssue):
            return TelegramEditMessageResult(False, None, (result,))

        message = _sent_message(result, operation="edit_message")
        if isinstance(message, TelegramTransportIssue):
            return TelegramEditMessageResult(False, None, (message,))

        return TelegramEditMessageResult(True, message, ())

    def _call(
        self,
        method: str,
        parameters: Mapping[str, object],
    ) -> object | TelegramTransportIssue:
        operation = _operation(method)
        encoded = urlencode(
            {
                key: (
                    json.dumps(value, separators=(",", ":"), ensure_ascii=False)
                    if isinstance(value, (dict, list))
                    else str(value).lower()
                    if isinstance(value, bool)
                    else str(value)
                )
                for key, value in parameters.items()
            }
        ).encode("utf-8")
        request = Request(
            f"{self._config.api_base}/bot{self._config.token}/{method}",
            data=encoded,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )

        try:
            with self._opener(
                request,
                timeout=self._config.request_timeout_seconds,
            ) as response:
                raw = response.read(self._config.maximum_response_bytes + 1)
        except HTTPError:
            return _issue(
                "telegram_http_error",
                "Telegram returned an HTTP error.",
                operation,
            )
        except (TimeoutError, URLError, OSError):
            return _issue(
                "telegram_network_error",
                "Telegram could not be reached.",
                operation,
            )
        except Exception:
            return _issue(
                "telegram_transport_failed",
                "The Telegram transport request failed.",
                operation,
            )

        if len(raw) > self._config.maximum_response_bytes:
            return _issue(
                "telegram_response_too_large",
                "Telegram returned an oversized response.",
                operation,
            )

        try:
            decoded = raw.decode("utf-8")
            payload = json.loads(decoded)
        except (UnicodeError, json.JSONDecodeError):
            return _issue(
                "telegram_response_invalid_json",
                "Telegram returned an invalid JSON response.",
                operation,
            )

        if not isinstance(payload, Mapping):
            return _issue(
                "telegram_response_invalid_shape",
                "Telegram returned an invalid response shape.",
                operation,
            )

        data = cast(Mapping[str, object], payload)
        ok = data.get("ok")

        if ok is not True:
            return _issue(
                "telegram_api_rejected",
                "Telegram rejected the Bot API request.",
                operation,
            )

        if "result" not in data:
            return _issue(
                "telegram_response_result_missing",
                "Telegram returned no Bot API result.",
                operation,
            )

        return data["result"]


def telegram_bot_api_transport(token: str) -> TelegramTransport:
    """Construct the default concrete Telegram Bot API transport."""
    return TelegramBotApiTransport(TelegramBotApiConfig(token=token))


def _keyboard_payload(keyboard: TelegramInlineKeyboard) -> dict[str, object]:
    return {
        "inline_keyboard": [
            [
                {
                    "text": button.text,
                    "callback_data": button.callback_data,
                }
                for button in row
            ]
            for row in keyboard.rows
        ]
    }


def _sent_message(
    value: object,
    *,
    operation: str,
) -> TelegramSentMessage | TelegramTransportIssue:
    if not isinstance(value, Mapping):
        return _issue(
            "telegram_api_message_invalid",
            "Telegram returned an invalid message result.",
            operation,
        )

    data = cast(Mapping[str, object], value)
    message_id = data.get("message_id")
    chat = data.get("chat")

    if (
        isinstance(message_id, bool)
        or not isinstance(message_id, int)
        or message_id < 1
        or not isinstance(chat, Mapping)
    ):
        return _issue(
            "telegram_api_message_invalid",
            "Telegram returned a malformed message result.",
            operation,
        )

    chat_id = cast(Mapping[str, object], chat).get("id")

    if isinstance(chat_id, bool) or not isinstance(chat_id, int) or chat_id < 1:
        return _issue(
            "telegram_api_message_invalid",
            "Telegram returned a malformed chat identifier.",
            operation,
        )

    return TelegramSentMessage(
        chat_id=str(chat_id),
        message_id=message_id,
    )


def _operation(method: str) -> str:
    return {
        "getUpdates": "fetch_updates",
        "sendMessage": "send_message",
        "answerCallbackQuery": "answer_callback_query",
        "editMessageText": "edit_message",
    }.get(method, "telegram_api")


def _issue(
    code: str,
    message: str,
    operation: str,
) -> TelegramTransportIssue:
    return TelegramTransportIssue(
        code=code,
        message=message,
        operation=operation,
    )


def _positive_integer(value: int, *, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer.")
