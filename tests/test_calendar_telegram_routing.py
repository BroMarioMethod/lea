"""Tests for Telegram calendar read command definitions and help."""

from lea.adapters.telegram.routing import (
    _DEFAULT_COMMAND_DEFINITIONS,
    TelegramCommandDefinition,
)
from lea.channels.authorisation import ChannelCapability
from lea.channels.handlers import _SUPPORTED_EXPLICIT_COMMANDS


def _definition(command: str) -> TelegramCommandDefinition:
    """Return one exact Telegram command definition."""
    matches = tuple(
        definition
        for definition in _DEFAULT_COMMAND_DEFINITIONS
        if definition.telegram_command == command
    )

    assert len(matches) == 1
    return matches[0]


def test_calendar_read_telegram_commands_are_registered_once() -> None:
    """Telegram should expose the three completed calendar read commands."""
    commands = tuple(
        definition.telegram_command for definition in _DEFAULT_COMMAND_DEFINITIONS
    )

    assert commands.count("/calendars") == 1
    assert commands.count("/calendar_events") == 1
    assert commands.count("/calendar_show") == 1


def test_calendars_route_requires_calendar_read_without_arguments() -> None:
    """Calendar discovery should require only Calendar.Read."""
    definition = _definition("/calendars")

    assert definition.channel_command == "calendar.list_calendars"
    assert definition.required_capability is ChannelCapability.CALENDAR_READ
    assert definition.minimum_arguments == 0
    assert definition.maximum_arguments == 0


def test_calendar_events_route_accepts_range_and_optional_calendars() -> None:
    """Event listing should accept two dates followed by calendar IDs."""
    definition = _definition("/calendar_events")

    assert definition.channel_command == "calendar.list_events"
    assert definition.required_capability is ChannelCapability.CALENDAR_READ
    assert definition.minimum_arguments == 2
    assert definition.maximum_arguments is None


def test_calendar_show_route_requires_exact_composite_identity() -> None:
    """Exact event lookup should require calendar ID and event UID."""
    definition = _definition("/calendar_show")

    assert definition.channel_command == "calendar.show_event"
    assert definition.required_capability is ChannelCapability.CALENDAR_READ
    assert definition.minimum_arguments == 2
    assert definition.maximum_arguments == 2


def test_calendar_commands_are_in_deterministic_help_text() -> None:
    """The shared channel help should describe every Telegram calendar route."""
    assert "/calendars" in _SUPPORTED_EXPLICIT_COMMANDS
    assert (
        "/calendar_events <start-date> <end-date> [calendar-id ...]"
        in _SUPPORTED_EXPLICIT_COMMANDS
    )
    assert "/calendar_show <calendar-id> <event-uid>" in _SUPPORTED_EXPLICIT_COMMANDS
