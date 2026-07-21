"""Timezone-safe presentation helpers for LEA runtime values."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def localise_utc_timestamp(
    timestamp: datetime,
    *,
    display_timezone: str,
) -> datetime:
    """Convert one canonical UTC timestamp for local presentation."""
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware.")

    if timestamp.utcoffset() != UTC.utcoffset(timestamp):
        raise ValueError("timestamp must represent a canonical UTC value.")

    if not display_timezone.strip():
        raise ValueError(
            "display_timezone must be a non-empty IANA timezone identifier."
        )

    try:
        timezone = ZoneInfo(display_timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError(
            "display_timezone must be a recognised IANA timezone."
        ) from error

    return timestamp.astimezone(timezone)
