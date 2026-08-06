"""Tests for provider-neutral recurrence contracts."""

from datetime import UTC, datetime

import pytest

from lea.calendars import CalendarRecurrence


def test_recurrence_round_trips_deterministically() -> None:
    recurrence = CalendarRecurrence(
        "weekly",
        interval=2,
        count=3,
        by_day=("WE", "MO"),
    )

    assert recurrence.to_rrule() == "FREQ=WEEKLY;INTERVAL=2;COUNT=3;BYDAY=MO,WE"
    assert CalendarRecurrence.from_rrule(recurrence.to_rrule()) == recurrence


def test_recurrence_supports_utc_until() -> None:
    recurrence = CalendarRecurrence.from_rrule("FREQ=DAILY;UNTIL=20261231T220000Z")

    assert recurrence.until == datetime(2026, 12, 31, 22, tzinfo=UTC)
    assert recurrence.to_rrule() == "FREQ=DAILY;UNTIL=20261231T220000Z"


@pytest.mark.parametrize(
    "value",
    (
        "FREQ=HOURLY",
        "FREQ=DAILY;BYHOUR=9",
        "FREQ=DAILY;COUNT=2;UNTIL=20261231",
        "FREQ=WEEKLY;BYDAY=XX",
        "FREQ=DAILY;INTERVAL=0",
    ),
)
def test_recurrence_rejects_unsupported_or_ambiguous_rules(value: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        CalendarRecurrence.from_rrule(value)
