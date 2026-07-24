"""Strict parsing for raw Telegram updates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from lea.adapters.telegram.contracts import TelegramUpdate


class TelegramUpdateKind(StrEnum):
    """Supported parsed Telegram update kinds."""

    PRIVATE_COMMAND = "private_command"
    CALLBACK_QUERY = "callback_query"


@dataclass(frozen=True, slots=True)
class TelegramParsedMessage:
    """One validated private Telegram command message."""

    update_id: int
    message_id: int
    user_id: str
    chat_id: str
    text: str
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None

    def __post_init__(self) -> None:
        """Validate canonical parsed message fields."""
        _validate_positive_integer(self.update_id, field_name="update_id")
        _validate_positive_integer(self.message_id, field_name="message_id")
        _validate_decimal_identifier(self.user_id, field_name="user_id")
        _validate_decimal_identifier(self.chat_id, field_name="chat_id")
        _validate_command_text(self.text)

        for field_name, value in (
            ("first_name", self.first_name),
            ("last_name", self.last_name),
            ("username", self.username),
        ):
            if value is not None and not value.strip():
                raise ValueError(f"{field_name} must be non-empty when provided.")


@dataclass(frozen=True, slots=True)
class TelegramParsedCallback:
    """One validated Telegram callback query."""

    update_id: int
    callback_query_id: str
    user_id: str
    chat_id: str
    message_id: int
    data: str
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None

    def __post_init__(self) -> None:
        """Validate canonical parsed callback fields."""
        _validate_positive_integer(self.update_id, field_name="update_id")
        _require_text(
            self.callback_query_id,
            field_name="callback_query_id",
        )
        _validate_decimal_identifier(self.user_id, field_name="user_id")
        _validate_decimal_identifier(self.chat_id, field_name="chat_id")
        _validate_positive_integer(self.message_id, field_name="message_id")
        _require_text(self.data, field_name="data")

        for field_name, value in (
            ("first_name", self.first_name),
            ("last_name", self.last_name),
            ("username", self.username),
        ):
            if value is not None and not value.strip():
                raise ValueError(f"{field_name} must be non-empty when provided.")


@dataclass(frozen=True, slots=True)
class TelegramUpdateParseIssue:
    """One deterministic Telegram update parsing problem."""

    code: str
    message: str
    field: str | None = None

    def __post_init__(self) -> None:
        """Validate safe issue fields."""
        _require_text(self.code, field_name="code")
        _require_text(self.message, field_name="message")

        if self.field is not None:
            _require_text(self.field, field_name="field")


@dataclass(frozen=True, slots=True)
class TelegramUpdateParseResult:
    """Immutable result of parsing one Telegram update."""

    success: bool
    kind: TelegramUpdateKind | None
    message: TelegramParsedMessage | None
    callback: TelegramParsedCallback | None
    issues: tuple[TelegramUpdateParseIssue, ...]

    def __post_init__(self) -> None:
        """Enforce parse-result consistency."""
        if self.success:
            if self.kind is None:
                raise ValueError(
                    "A successful Telegram parse result must contain a kind."
                )

            if self.issues:
                raise ValueError(
                    "A successful Telegram parse result must not contain issues."
                )

            if self.kind is TelegramUpdateKind.PRIVATE_COMMAND:
                if self.message is None or self.callback is not None:
                    raise ValueError(
                        "A private-command result must contain only a message."
                    )
                return

            if self.kind is TelegramUpdateKind.CALLBACK_QUERY:
                if self.callback is None or self.message is not None:
                    raise ValueError("A callback result must contain only a callback.")
                return

            raise ValueError("Unsupported Telegram update kind.")

        if self.kind is not None:
            raise ValueError("A failed Telegram parse result must not contain a kind.")

        if self.message is not None or self.callback is not None:
            raise ValueError(
                "A failed Telegram parse result must not contain parsed data."
            )

        if not self.issues:
            raise ValueError(
                "A failed Telegram parse result must contain at least one issue."
            )


def parse_telegram_update(
    update: TelegramUpdate,
) -> TelegramUpdateParseResult:
    """Parse one raw Telegram update without authorisation or routing."""
    payload = update.payload
    supported_fields = tuple(
        field for field in ("message", "callback_query") if field in payload
    )

    if len(supported_fields) > 1:
        return _failure(
            code="telegram_update_ambiguous",
            message=(
                "The Telegram update contains more than one supported "
                "top-level update type."
            ),
        )

    if not supported_fields:
        return _failure(
            code="telegram_update_unsupported",
            message="The Telegram update type is not supported.",
        )

    field = supported_fields[0]
    raw_value = payload[field]

    if not isinstance(raw_value, Mapping):
        return _failure(
            code="telegram_update_invalid_shape",
            message=f"Telegram update field '{field}' must be an object.",
            field=field,
        )

    if field == "message":
        return _parse_message(
            update.update_id,
            cast(Mapping[str, object], raw_value),
        )

    return _parse_callback(
        update.update_id,
        cast(Mapping[str, object], raw_value),
    )


def _parse_message(
    update_id: int,
    data: Mapping[str, object],
) -> TelegramUpdateParseResult:
    message_id = _parse_positive_integer(
        data.get("message_id"),
        field="message.message_id",
    )
    if isinstance(message_id, TelegramUpdateParseIssue):
        return _issue_failure(message_id)

    user = _parse_user(data.get("from"), field="message.from")
    if isinstance(user, TelegramUpdateParseIssue):
        return _issue_failure(user)

    chat = _parse_private_chat(data.get("chat"), field="message.chat")
    if isinstance(chat, TelegramUpdateParseIssue):
        return _issue_failure(chat)

    text = data.get("text")

    if not isinstance(text, str):
        return _failure(
            code="telegram_message_unsupported",
            message="Only private text commands are supported.",
            field="message.text",
        )

    if not text.startswith("/"):
        return _failure(
            code="telegram_message_not_command",
            message="Only explicit Telegram commands are supported.",
            field="message.text",
        )

    if not text.strip():
        return _failure(
            code="telegram_message_invalid_command",
            message="Telegram command text must be non-empty.",
            field="message.text",
        )

    user_id = user["id"]
    assert user_id is not None

    try:
        parsed = TelegramParsedMessage(
            update_id=update_id,
            message_id=message_id,
            user_id=user_id,
            chat_id=chat,
            text=text,
            first_name=user["first_name"],
            last_name=user["last_name"],
            username=user["username"],
        )
    except (TypeError, ValueError) as error:
        return _failure(
            code="telegram_message_invalid",
            message=str(error),
        )

    return TelegramUpdateParseResult(
        success=True,
        kind=TelegramUpdateKind.PRIVATE_COMMAND,
        message=parsed,
        callback=None,
        issues=(),
    )


def _parse_callback(
    update_id: int,
    data: Mapping[str, object],
) -> TelegramUpdateParseResult:
    callback_query_id = data.get("id")

    if not isinstance(callback_query_id, str) or not callback_query_id.strip():
        return _failure(
            code="telegram_callback_invalid",
            message="Telegram callback query id must be a non-empty string.",
            field="callback_query.id",
        )

    user = _parse_user(data.get("from"), field="callback_query.from")
    if isinstance(user, TelegramUpdateParseIssue):
        return _issue_failure(user)

    raw_message = data.get("message")

    if not isinstance(raw_message, Mapping):
        return _failure(
            code="telegram_callback_message_missing",
            message=(
                "Telegram callback queries must reference a private-chat message."
            ),
            field="callback_query.message",
        )

    message = cast(Mapping[str, object], raw_message)
    message_id = _parse_positive_integer(
        message.get("message_id"),
        field="callback_query.message.message_id",
    )
    if isinstance(message_id, TelegramUpdateParseIssue):
        return _issue_failure(message_id)

    chat = _parse_private_chat(
        message.get("chat"),
        field="callback_query.message.chat",
    )
    if isinstance(chat, TelegramUpdateParseIssue):
        return _issue_failure(chat)

    callback_data = data.get("data")

    if not isinstance(callback_data, str) or not callback_data:
        return _failure(
            code="telegram_callback_data_missing",
            message="Telegram callback data must be a non-empty string.",
            field="callback_query.data",
        )

    user_id = user["id"]
    assert user_id is not None

    try:
        parsed = TelegramParsedCallback(
            update_id=update_id,
            callback_query_id=callback_query_id,
            user_id=user_id,
            chat_id=chat,
            message_id=message_id,
            data=callback_data,
            first_name=user["first_name"],
            last_name=user["last_name"],
            username=user["username"],
        )
    except (TypeError, ValueError) as error:
        return _failure(
            code="telegram_callback_invalid",
            message=str(error),
        )

    return TelegramUpdateParseResult(
        success=True,
        kind=TelegramUpdateKind.CALLBACK_QUERY,
        message=None,
        callback=parsed,
        issues=(),
    )


def _parse_user(
    value: object,
    *,
    field: str,
) -> dict[str, str | None] | TelegramUpdateParseIssue:
    if not isinstance(value, Mapping):
        return TelegramUpdateParseIssue(
            code="telegram_user_invalid",
            message=f"{field} must be an object.",
            field=field,
        )

    user = cast(Mapping[str, object], value)
    user_id = _parse_identifier(user.get("id"), field=f"{field}.id")

    if isinstance(user_id, TelegramUpdateParseIssue):
        return user_id

    first_name = _parse_optional_text(
        user.get("first_name"),
        field=f"{field}.first_name",
    )
    if isinstance(first_name, TelegramUpdateParseIssue):
        return first_name

    last_name = _parse_optional_text(
        user.get("last_name"),
        field=f"{field}.last_name",
    )
    if isinstance(last_name, TelegramUpdateParseIssue):
        return last_name

    username = _parse_optional_text(
        user.get("username"),
        field=f"{field}.username",
    )
    if isinstance(username, TelegramUpdateParseIssue):
        return username

    return {
        "id": user_id,
        "first_name": first_name,
        "last_name": last_name,
        "username": username,
    }


def _parse_private_chat(
    value: object,
    *,
    field: str,
) -> str | TelegramUpdateParseIssue:
    if not isinstance(value, Mapping):
        return TelegramUpdateParseIssue(
            code="telegram_chat_invalid",
            message=f"{field} must be an object.",
            field=field,
        )

    chat = cast(Mapping[str, object], value)
    chat_type = chat.get("type")

    if chat_type != "private":
        return TelegramUpdateParseIssue(
            code="telegram_chat_not_private",
            message="Only private Telegram chats are supported.",
            field=f"{field}.type",
        )

    return _parse_identifier(chat.get("id"), field=f"{field}.id")


def _parse_identifier(
    value: object,
    *,
    field: str,
) -> str | TelegramUpdateParseIssue:
    if isinstance(value, bool):
        valid = False
    elif isinstance(value, int):
        valid = value > 0
    elif isinstance(value, str):
        valid = (
            value.isascii()
            and value.isdecimal()
            and not value.startswith("0")
            and int(value) > 0
        )
    else:
        valid = False

    if not valid:
        return TelegramUpdateParseIssue(
            code="telegram_identifier_invalid",
            message=f"{field} must be a canonical positive decimal identifier.",
            field=field,
        )

    return str(value)


def _parse_positive_integer(
    value: object,
    *,
    field: str,
) -> int | TelegramUpdateParseIssue:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return TelegramUpdateParseIssue(
            code="telegram_integer_invalid",
            message=f"{field} must be a positive integer.",
            field=field,
        )

    return value


def _parse_optional_text(
    value: object,
    *,
    field: str,
) -> str | None | TelegramUpdateParseIssue:
    if value is None:
        return None

    if not isinstance(value, str) or not value.strip():
        return TelegramUpdateParseIssue(
            code="telegram_text_invalid",
            message=f"{field} must be a non-empty string when provided.",
            field=field,
        )

    return value


def _validate_command_text(value: str) -> None:
    if not isinstance(value, str):
        raise TypeError("text must be a string.")

    if not value.startswith("/") or not value.strip():
        raise ValueError("text must contain an explicit Telegram command.")


def _validate_positive_integer(value: int, *, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer.")

    if value < 1:
        raise ValueError(f"{field_name} must be greater than zero.")


def _validate_decimal_identifier(value: str, *, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isdecimal()
        or value.startswith("0")
        or int(value) < 1
    ):
        raise ValueError(f"{field_name} must use a canonical positive decimal string.")


def _require_text(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")

    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty.")


def _issue_failure(
    issue: TelegramUpdateParseIssue,
) -> TelegramUpdateParseResult:
    return TelegramUpdateParseResult(
        success=False,
        kind=None,
        message=None,
        callback=None,
        issues=(issue,),
    )


def _failure(
    *,
    code: str,
    message: str,
    field: str | None = None,
) -> TelegramUpdateParseResult:
    return _issue_failure(
        TelegramUpdateParseIssue(
            code=code,
            message=message,
            field=field,
        )
    )
