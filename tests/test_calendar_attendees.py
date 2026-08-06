"""Tests for canonical attendee contracts."""

import pytest

from lea.calendars import CalendarAttendee, canonical_attendees


def test_attendees_normalize_and_sort_stably() -> None:
    values = canonical_attendees(
        [
            CalendarAttendee("mailto:Zed@example.com", display_name="Zed"),
            CalendarAttendee("alice@example.com", response="accepted", rsvp=True),
        ]
    )

    assert [value.address for value in values] == [
        "alice@example.com",
        "zed@example.com",
    ]
    assert values[0].response == "ACCEPTED"


def test_duplicate_attendees_are_rejected() -> None:
    value = CalendarAttendee("a@example.com")
    with pytest.raises(ValueError, match="duplicate"):
        canonical_attendees((value, CalendarAttendee(value.address)))
