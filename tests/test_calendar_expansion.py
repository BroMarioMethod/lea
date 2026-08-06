"""Tests for deterministic recurrence expansion."""

from datetime import UTC, date, datetime
from typing import cast
from zoneinfo import ZoneInfo

from lea.calendars import (
    CalendarEvent,
    CalendarEventTiming,
    CalendarRecurrence,
    expand_calendar_event,
)


def test_daily_timed_expansion_preserves_local_time_across_dst() -> None:
    event = CalendarEvent(
        "work",
        "dst@example",
        "Daily",
        CalendarEventTiming(
            datetime(2026, 3, 28, 9, tzinfo=UTC),
            datetime(2026, 3, 28, 10, tzinfo=UTC),
            "Europe/London",
        ),
        recurrence=CalendarRecurrence("DAILY", count=3),
    )

    occurrences = expand_calendar_event(
        event,
        range_start=date(2026, 3, 28),
        range_end=date(2026, 4, 1),
    )

    assert all(isinstance(item.occurrence_start, datetime) for item in occurrences)
    assert [
        cast(datetime, item.occurrence_start).astimezone(ZoneInfo("Europe/London")).hour
        for item in occurrences
    ] == [9, 9, 9]
    assert cast(datetime, occurrences[0].occurrence_start).utcoffset() == UTC.utcoffset(
        None
    )
    assert cast(datetime, occurrences[2].occurrence_start).hour == 8


def test_weekly_all_day_expansion_uses_selected_weekdays() -> None:
    event = CalendarEvent(
        "work",
        "weekly@example",
        "Weekly",
        CalendarEventTiming(date(2026, 8, 3), date(2026, 8, 4)),
        recurrence=CalendarRecurrence("WEEKLY", by_day=("MO", "WE"), count=4),
    )

    occurrences = expand_calendar_event(
        event,
        range_start=date(2026, 8, 1),
        range_end=date(2026, 8, 25),
    )

    assert [item.occurrence_start for item in occurrences] == [
        date(2026, 8, 3),
        date(2026, 8, 5),
        date(2026, 8, 10),
        date(2026, 8, 12),
    ]


def test_monthly_invalid_day_is_skipped_without_crashing() -> None:
    event = CalendarEvent(
        "work",
        "monthly@example",
        "Monthly",
        CalendarEventTiming(date(2026, 1, 31), date(2026, 2, 1)),
        recurrence=CalendarRecurrence("MONTHLY", count=3),
    )

    occurrences = expand_calendar_event(
        event,
        range_start=date(2026, 1, 1),
        range_end=date(2026, 6, 1),
    )

    assert [item.occurrence_start for item in occurrences] == [
        date(2026, 1, 31),
        date(2026, 3, 31),
        date(2026, 5, 31),
    ]
