"""Telegram adapter public transport contracts."""

from lea.adapters.telegram.contracts import (
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
    TelegramTransport,
    TelegramTransportIssue,
    TelegramUpdate,
)
from lea.adapters.telegram.fakes import (
    FakeTelegramTransport,
    TelegramAnswerCallbackCall,
    TelegramEditMessageCall,
    TelegramFetchUpdatesCall,
    TelegramSendMessageCall,
)
from lea.adapters.telegram.parser import (
    TelegramParsedCallback,
    TelegramParsedMessage,
    TelegramUpdateKind,
    TelegramUpdateParseIssue,
    TelegramUpdateParseResult,
    parse_telegram_update,
)

__all__ = [
    "TELEGRAM_MAX_CALLBACK_DATA_BYTES",
    "TELEGRAM_MAX_FETCH_LIMIT",
    "TELEGRAM_MAX_MESSAGE_TEXT_LENGTH",
    "FakeTelegramTransport",
    "TelegramAnswerCallbackCall",
    "TelegramAnswerCallbackResult",
    "TelegramEditMessageCall",
    "TelegramEditMessageResult",
    "TelegramFetchUpdatesCall",
    "TelegramFetchUpdatesResult",
    "TelegramInlineButton",
    "TelegramInlineKeyboard",
    "TelegramParsedCallback",
    "TelegramParsedMessage",
    "TelegramSendMessageCall",
    "TelegramSendMessageResult",
    "TelegramSentMessage",
    "TelegramTransport",
    "TelegramTransportIssue",
    "TelegramUpdate",
    "TelegramUpdateKind",
    "TelegramUpdateParseIssue",
    "TelegramUpdateParseResult",
    "parse_telegram_update",
]
