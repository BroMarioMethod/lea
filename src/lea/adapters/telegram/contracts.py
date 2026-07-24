"""Immutable Telegram transport contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from lea.actions.errors import ActionContractError
from lea.actions.values import freeze_parameters

TELEGRAM_MAX_CALLBACK_DATA_BYTES = 64
TELEGRAM_MAX_MESSAGE_TEXT_LENGTH = 4096
TELEGRAM_MAX_FETCH_LIMIT = 100


@dataclass(frozen=True, slots=True)
class TelegramTransportIssue:
    """One deterministic Telegram transport failure."""

    code: str
    message: str
    operation: str

    def __post_init__(self) -> None:
        """Validate safe transport issue fields."""
        for field_name, value in (
            ("code", self.code),
            ("message", self.message),
            ("operation", self.operation),
        ):
            if not value.strip():
                raise ValueError(
                    f"Telegram transport issue {field_name} must be non-empty."
                )


@dataclass(frozen=True, slots=True)
class TelegramUpdate:
    """One raw Telegram update with deeply frozen payload."""

    update_id: int
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        """Validate update identifier and freeze the raw payload."""
        _validate_positive_integer(self.update_id, field_name="update_id")

        try:
            frozen = freeze_parameters(self.payload)
        except ActionContractError as error:
            raise ValueError(
                "Telegram update payload must contain JSON-compatible values."
            ) from error

        object.__setattr__(self, "payload", frozen)


@dataclass(frozen=True, slots=True)
class TelegramSentMessage:
    """One message record returned by Telegram."""

    chat_id: str
    message_id: int

    def __post_init__(self) -> None:
        """Validate message identity."""
        _validate_decimal_identifier(self.chat_id, field_name="chat_id")
        _validate_positive_integer(self.message_id, field_name="message_id")


@dataclass(frozen=True, slots=True)
class TelegramInlineButton:
    """One Telegram inline-keyboard callback button."""

    text: str
    callback_data: str

    def __post_init__(self) -> None:
        """Validate bounded button text and callback data."""
        if not self.text.strip():
            raise ValueError("Telegram button text must be non-empty.")

        if not self.callback_data:
            raise ValueError("Telegram callback_data must be non-empty.")

        if len(self.callback_data.encode("utf-8")) > TELEGRAM_MAX_CALLBACK_DATA_BYTES:
            raise ValueError(
                "Telegram callback_data must not exceed "
                f"{TELEGRAM_MAX_CALLBACK_DATA_BYTES} UTF-8 bytes."
            )


@dataclass(frozen=True, slots=True)
class TelegramInlineKeyboard:
    """One immutable Telegram inline keyboard."""

    rows: tuple[tuple[TelegramInlineButton, ...], ...]

    def __post_init__(self) -> None:
        """Validate non-empty rows and deeply canonicalise the keyboard."""
        canonical_rows = tuple(tuple(row) for row in self.rows)

        if not canonical_rows:
            raise ValueError("Telegram inline keyboard must contain at least one row.")

        if any(not row for row in canonical_rows):
            raise ValueError("Telegram inline keyboard rows must not be empty.")

        object.__setattr__(self, "rows", canonical_rows)


@dataclass(frozen=True, slots=True)
class TelegramFetchUpdatesResult:
    """Result of fetching Telegram updates."""

    success: bool
    updates: tuple[TelegramUpdate, ...]
    issues: tuple[TelegramTransportIssue, ...]

    def __post_init__(self) -> None:
        """Enforce fetch result consistency and ordering."""
        if self.success:
            if self.issues:
                raise ValueError("A successful Telegram fetch must not contain issues.")

            ordered = tuple(sorted(self.updates, key=lambda item: item.update_id))

            if len({item.update_id for item in ordered}) != len(ordered):
                raise ValueError(
                    "Telegram fetch results must not contain duplicate update IDs."
                )

            object.__setattr__(self, "updates", ordered)
            return

        if self.updates:
            raise ValueError("A failed Telegram fetch must not contain updates.")

        if not self.issues:
            raise ValueError("A failed Telegram fetch must contain at least one issue.")


@dataclass(frozen=True, slots=True)
class TelegramSendMessageResult:
    """Result of sending one Telegram message."""

    success: bool
    message: TelegramSentMessage | None
    issues: tuple[TelegramTransportIssue, ...]

    def __post_init__(self) -> None:
        """Enforce send result consistency."""
        _validate_optional_value_result(
            success=self.success,
            value=self.message,
            issues=self.issues,
            operation="send_message",
        )


@dataclass(frozen=True, slots=True)
class TelegramAnswerCallbackResult:
    """Result of answering one Telegram callback query."""

    success: bool
    issues: tuple[TelegramTransportIssue, ...]

    def __post_init__(self) -> None:
        """Enforce callback result consistency."""
        _validate_issue_only_result(
            success=self.success,
            issues=self.issues,
            operation="answer_callback_query",
        )


@dataclass(frozen=True, slots=True)
class TelegramEditMessageResult:
    """Result of editing one Telegram message."""

    success: bool
    message: TelegramSentMessage | None
    issues: tuple[TelegramTransportIssue, ...]

    def __post_init__(self) -> None:
        """Enforce edit result consistency."""
        _validate_optional_value_result(
            success=self.success,
            value=self.message,
            issues=self.issues,
            operation="edit_message",
        )


@runtime_checkable
class TelegramTransport(Protocol):
    """Transport boundary for Telegram Bot API operations."""

    def fetch_updates(
        self,
        *,
        offset: int | None,
        limit: int,
        timeout_seconds: int,
    ) -> TelegramFetchUpdatesResult:
        """Fetch one ordered batch of raw Telegram updates."""
        ...

    def send_message(
        self,
        *,
        chat_id: str,
        text: str,
        keyboard: TelegramInlineKeyboard | None = None,
    ) -> TelegramSendMessageResult:
        """Send one text message with optional inline controls."""
        ...

    def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> TelegramAnswerCallbackResult:
        """Answer one Telegram callback query."""
        ...

    def edit_message(
        self,
        *,
        chat_id: str,
        message_id: int,
        text: str,
        keyboard: TelegramInlineKeyboard | None = None,
    ) -> TelegramEditMessageResult:
        """Edit one previously sent Telegram message."""
        ...


def validate_fetch_arguments(
    *,
    offset: int | None,
    limit: int,
    timeout_seconds: int,
) -> None:
    """Validate bounded long-poll arguments."""
    if offset is not None and offset < 0:
        raise ValueError("Telegram update offset must not be negative.")

    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("Telegram fetch limit must be an integer.")

    if not 1 <= limit <= TELEGRAM_MAX_FETCH_LIMIT:
        raise ValueError(
            f"Telegram fetch limit must be between 1 and {TELEGRAM_MAX_FETCH_LIMIT}."
        )

    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
        raise TypeError("Telegram polling timeout must be an integer.")

    if timeout_seconds <= 0:
        raise ValueError("Telegram polling timeout must be greater than zero.")


def validate_send_arguments(
    *,
    chat_id: str,
    text: str,
) -> None:
    """Validate bounded Telegram text-message arguments."""
    _validate_decimal_identifier(chat_id, field_name="chat_id")

    if not text:
        raise ValueError("Telegram message text must be non-empty.")

    if len(text) > TELEGRAM_MAX_MESSAGE_TEXT_LENGTH:
        raise ValueError(
            "Telegram message text must not exceed "
            f"{TELEGRAM_MAX_MESSAGE_TEXT_LENGTH} characters."
        )


def validate_callback_arguments(
    *,
    callback_query_id: str,
    text: str | None,
) -> None:
    """Validate callback-answer arguments."""
    if not callback_query_id.strip():
        raise ValueError("Telegram callback_query_id must be non-empty.")

    if text is not None and not text.strip():
        raise ValueError(
            "Telegram callback answer text must be non-empty when provided."
        )


def validate_edit_arguments(
    *,
    chat_id: str,
    message_id: int,
    text: str,
) -> None:
    """Validate Telegram message-edit arguments."""
    validate_send_arguments(chat_id=chat_id, text=text)
    _validate_positive_integer(message_id, field_name="message_id")


def _validate_optional_value_result(
    *,
    success: bool,
    value: object | None,
    issues: tuple[TelegramTransportIssue, ...],
    operation: str,
) -> None:
    if success:
        if value is None:
            raise ValueError(
                f"A successful Telegram {operation} result must contain a value."
            )
        if issues:
            raise ValueError(
                f"A successful Telegram {operation} result must not contain issues."
            )
        return

    if value is not None:
        raise ValueError(
            f"A failed Telegram {operation} result must not contain a value."
        )

    if not issues:
        raise ValueError(
            f"A failed Telegram {operation} result must contain at least one issue."
        )


def _validate_issue_only_result(
    *,
    success: bool,
    issues: tuple[TelegramTransportIssue, ...],
    operation: str,
) -> None:
    if success and issues:
        raise ValueError(
            f"A successful Telegram {operation} result must not contain issues."
        )

    if not success and not issues:
        raise ValueError(
            f"A failed Telegram {operation} result must contain at least one issue."
        )


def _validate_positive_integer(value: int, *, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer.")

    if value < 1:
        raise ValueError(f"{field_name} must be greater than zero.")


def _validate_decimal_identifier(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")

    if (
        not value.isascii()
        or not value.isdecimal()
        or value.startswith("0")
        or int(value) < 1
    ):
        raise ValueError(f"{field_name} must use a canonical positive decimal string.")
