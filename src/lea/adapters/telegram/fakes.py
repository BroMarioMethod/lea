"""Deterministic fake Telegram transport for tests."""

from __future__ import annotations

from dataclasses import dataclass

from lea.adapters.telegram.contracts import (
    TelegramAnswerCallbackResult,
    TelegramEditMessageResult,
    TelegramFetchUpdatesResult,
    TelegramInlineKeyboard,
    TelegramSendMessageResult,
    TelegramTransport,
    validate_callback_arguments,
    validate_edit_arguments,
    validate_fetch_arguments,
    validate_send_arguments,
)


@dataclass(frozen=True, slots=True)
class TelegramFetchUpdatesCall:
    """One recorded fake fetch call."""

    offset: int | None
    limit: int
    timeout_seconds: int


@dataclass(frozen=True, slots=True)
class TelegramSendMessageCall:
    """One recorded fake message-send call."""

    chat_id: str
    text: str
    keyboard: TelegramInlineKeyboard | None


@dataclass(frozen=True, slots=True)
class TelegramAnswerCallbackCall:
    """One recorded fake callback-answer call."""

    callback_query_id: str
    text: str | None
    show_alert: bool


@dataclass(frozen=True, slots=True)
class TelegramEditMessageCall:
    """One recorded fake message-edit call."""

    chat_id: str
    message_id: int
    text: str
    keyboard: TelegramInlineKeyboard | None


class FakeTelegramTransport(TelegramTransport):
    """Queue-backed deterministic Telegram transport."""

    def __init__(self) -> None:
        """Create one empty fake transport."""
        self.fetch_results: list[TelegramFetchUpdatesResult] = []
        self.send_results: list[TelegramSendMessageResult] = []
        self.answer_results: list[TelegramAnswerCallbackResult] = []
        self.edit_results: list[TelegramEditMessageResult] = []

        self.fetch_calls: list[TelegramFetchUpdatesCall] = []
        self.send_calls: list[TelegramSendMessageCall] = []
        self.answer_calls: list[TelegramAnswerCallbackCall] = []
        self.edit_calls: list[TelegramEditMessageCall] = []

    def fetch_updates(
        self,
        *,
        offset: int | None,
        limit: int,
        timeout_seconds: int,
    ) -> TelegramFetchUpdatesResult:
        """Record one fetch and return the next queued result."""
        validate_fetch_arguments(
            offset=offset,
            limit=limit,
            timeout_seconds=timeout_seconds,
        )
        self.fetch_calls.append(
            TelegramFetchUpdatesCall(
                offset=offset,
                limit=limit,
                timeout_seconds=timeout_seconds,
            )
        )
        return self._pop(self.fetch_results, operation="fetch_updates")

    def send_message(
        self,
        *,
        chat_id: str,
        text: str,
        keyboard: TelegramInlineKeyboard | None = None,
    ) -> TelegramSendMessageResult:
        """Record one send and return the next queued result."""
        validate_send_arguments(chat_id=chat_id, text=text)
        self.send_calls.append(
            TelegramSendMessageCall(
                chat_id=chat_id,
                text=text,
                keyboard=keyboard,
            )
        )
        return self._pop(self.send_results, operation="send_message")

    def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> TelegramAnswerCallbackResult:
        """Record one callback answer and return the next queued result."""
        validate_callback_arguments(
            callback_query_id=callback_query_id,
            text=text,
        )
        self.answer_calls.append(
            TelegramAnswerCallbackCall(
                callback_query_id=callback_query_id,
                text=text,
                show_alert=show_alert,
            )
        )
        return self._pop(
            self.answer_results,
            operation="answer_callback_query",
        )

    def edit_message(
        self,
        *,
        chat_id: str,
        message_id: int,
        text: str,
        keyboard: TelegramInlineKeyboard | None = None,
    ) -> TelegramEditMessageResult:
        """Record one edit and return the next queued result."""
        validate_edit_arguments(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
        )
        self.edit_calls.append(
            TelegramEditMessageCall(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                keyboard=keyboard,
            )
        )
        return self._pop(self.edit_results, operation="edit_message")

    @staticmethod
    def _pop[Result](
        queue: list[Result],
        *,
        operation: str,
    ) -> Result:
        if not queue:
            raise RuntimeError(f"No fake Telegram result queued for {operation}.")

        return queue.pop(0)
