"""Safe deterministic formatting for Telegram channel responses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, TypeGuard

from lea.adapters.telegram.contracts import (
    TELEGRAM_MAX_MESSAGE_TEXT_LENGTH,
    TelegramInlineKeyboard,
)
from lea.adapters.telegram.controls import build_telegram_controls
from lea.channels import ChannelResponse, ChannelResponseOutcome

_TRUNCATION_MARKER: Final = "\n\n[Response truncated]"
_REDACTED: Final = "[redacted]"
_SENSITIVE_KEY_PARTS: Final = (
    "exception",
    "file",
    "password",
    "path",
    "secret",
    "stack",
    "token",
    "trace",
)

_OUTCOME_HEADINGS: Final = {
    ChannelResponseOutcome.SUCCEEDED: "Succeeded",
    ChannelResponseOutcome.REJECTED: "Rejected",
    ChannelResponseOutcome.NOT_AUTHORISED: "Not authorised",
    ChannelResponseOutcome.VALIDATION_FAILED: "Validation failed",
    ChannelResponseOutcome.NOT_FOUND: "Not found",
    ChannelResponseOutcome.CONFLICT: "Conflict",
    ChannelResponseOutcome.APPLICATION_FAILED: "Application failed",
    ChannelResponseOutcome.TEMPORARILY_UNAVAILABLE: "Temporarily unavailable",
}


@dataclass(frozen=True, slots=True)
class TelegramFormattedResponse:
    """One Telegram-safe plain-text response and optional keyboard."""

    text: str
    keyboard: TelegramInlineKeyboard | None

    def __post_init__(self) -> None:
        """Validate bounded formatted output."""
        if not self.text.strip():
            raise ValueError("Telegram formatted response text must be non-empty.")

        if len(self.text) > TELEGRAM_MAX_MESSAGE_TEXT_LENGTH:
            raise ValueError(
                "Telegram formatted response text exceeds the message limit."
            )


@dataclass(frozen=True, slots=True)
class TelegramResponseFormattingIssue:
    """One deterministic Telegram response-formatting problem."""

    code: str
    message: str
    field: str | None = None

    def __post_init__(self) -> None:
        """Validate safe formatting issue fields."""
        if not self.code.strip():
            raise ValueError("Telegram formatting issue code must be non-empty.")

        if not self.message.strip():
            raise ValueError("Telegram formatting issue message must be non-empty.")

        if self.field is not None and not self.field.strip():
            raise ValueError(
                "Telegram formatting issue field must be non-empty when provided."
            )


@dataclass(frozen=True, slots=True)
class TelegramResponseFormattingResult:
    """Immutable result of formatting one channel response."""

    success: bool
    formatted: TelegramFormattedResponse | None
    issues: tuple[TelegramResponseFormattingIssue, ...]

    def __post_init__(self) -> None:
        """Enforce formatting-result consistency."""
        if self.success:
            if self.formatted is None:
                raise ValueError(
                    "A successful Telegram formatting result must contain output."
                )

            if self.issues:
                raise ValueError(
                    "A successful Telegram formatting result must not contain issues."
                )
            return

        if self.formatted is not None:
            raise ValueError(
                "A failed Telegram formatting result must not contain output."
            )

        if not self.issues:
            raise ValueError(
                "A failed Telegram formatting result must contain at least one issue."
            )


def format_telegram_response(
    response: ChannelResponse,
) -> TelegramResponseFormattingResult:
    """Format one channel response as bounded Telegram-safe plain text."""
    keyboard: TelegramInlineKeyboard | None = None

    if response.controls:
        controls = build_telegram_controls(response.controls)

        if not controls.success or controls.keyboard is None:
            first = controls.issues[0]
            return _failure(
                code="telegram_response_controls_invalid",
                message=(
                    "The channel response contains controls that cannot be "
                    "rendered safely for Telegram."
                ),
                field=first.field or "controls",
            )

        keyboard = controls.keyboard

    lines = [
        _OUTCOME_HEADINGS[response.outcome],
        "",
        _normalise_text(response.message),
    ]

    if response.issue is not None:
        lines.extend(
            [
                "",
                "Issue:",
                f"  Code: {_normalise_text(response.issue.code)}",
                f"  Message: {_normalise_text(response.issue.message)}",
            ]
        )

        if response.issue.field is not None:
            lines.append(f"  Field: {_normalise_text(response.issue.field)}")

    if response.data:
        lines.extend(["", "Details:"])
        lines.extend(_render_mapping(response.data, indent=2))

    text = _truncate("\n".join(lines).rstrip())

    return TelegramResponseFormattingResult(
        success=True,
        formatted=TelegramFormattedResponse(
            text=text,
            keyboard=keyboard,
        ),
        issues=(),
    )


def _render_mapping(
    value: Mapping[str, object],
    *,
    indent: int,
) -> list[str]:
    lines: list[str] = []
    prefix = " " * indent

    for key in sorted(value):
        rendered_key = _normalise_text(key)

        if _is_sensitive_key(key):
            lines.append(f"{prefix}{rendered_key}: {_REDACTED}")
            continue

        item = value[key]

        if isinstance(item, Mapping):
            lines.append(f"{prefix}{rendered_key}:")
            lines.extend(_render_mapping(item, indent=indent + 2))
            continue

        if _is_sequence(item):
            lines.append(f"{prefix}{rendered_key}:")

            if key == "commands":
                lines.extend(
                    _render_command_sequence(
                        item,
                        indent=indent + 2,
                    )
                )
            else:
                lines.extend(_render_sequence(item, indent=indent + 2))

            continue

        lines.append(f"{prefix}{rendered_key}: {_render_scalar(item)}")

    return lines


def _render_command_sequence(
    value: Sequence[object],
    *,
    indent: int,
) -> list[str]:
    """Render one trusted deterministic command list."""
    prefix = " " * indent
    lines: list[str] = []

    for item in value:
        if isinstance(item, str):
            lines.append(f"{prefix}- {_normalise_text(item)}")
        else:
            lines.append(f"{prefix}- {_REDACTED}")

    if not lines:
        lines.append(f"{prefix}(none)")

    return lines


def _render_sequence(
    value: Sequence[object],
    *,
    indent: int,
) -> list[str]:
    prefix = " " * indent
    lines: list[str] = []

    for item in value:
        if isinstance(item, Mapping):
            lines.append(f"{prefix}-")
            lines.extend(_render_mapping(item, indent=indent + 2))
            continue

        if _is_sequence(item):
            lines.append(f"{prefix}-")
            lines.extend(_render_sequence(item, indent=indent + 2))
            continue

        lines.append(f"{prefix}- {_render_scalar(item)}")

    if not lines:
        lines.append(f"{prefix}(none)")

    return lines


def _render_scalar(value: object) -> str:
    if value is None:
        return "not available"

    if value is True:
        return "yes"

    if value is False:
        return "no"

    if isinstance(value, str):
        return _safe_string(value)

    if isinstance(value, (int, float)):
        return str(value)

    return _REDACTED


def _safe_string(value: str) -> str:
    normalised = _normalise_text(value)

    if _looks_like_path(normalised):
        return _REDACTED

    return normalised


def _normalise_text(value: str) -> str:
    return " ".join(value.replace("\x00", "").split())


def _looks_like_path(value: str) -> bool:
    if value.startswith(("/", "\\\\")):
        return True

    return (
        len(value) >= 3
        and value[0].isalpha()
        and value[1] == ":"
        and value[2] in {"\\", "/"}
    )


def _is_sensitive_key(value: str) -> bool:
    folded = value.casefold()
    return any(part in folded for part in _SENSITIVE_KEY_PARTS)


def _is_sequence(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    )


def _truncate(value: str) -> str:
    if len(value) <= TELEGRAM_MAX_MESSAGE_TEXT_LENGTH:
        return value

    available = TELEGRAM_MAX_MESSAGE_TEXT_LENGTH - len(_TRUNCATION_MARKER)
    return value[:available].rstrip() + _TRUNCATION_MARKER


def _failure(
    *,
    code: str,
    message: str,
    field: str | None = None,
) -> TelegramResponseFormattingResult:
    return TelegramResponseFormattingResult(
        success=False,
        formatted=None,
        issues=(
            TelegramResponseFormattingIssue(
                code=code,
                message=message,
                field=field,
            ),
        ),
    )
