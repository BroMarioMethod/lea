"""Tests for strict local khal vdir iCalendar item parsing."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from lea.adapters.khal import (
    KHAL_MAX_ICALENDAR_ITEM_BYTES,
    KhalCalendarItemParseResult,
    parse_khal_calendar_item,
    read_khal_calendar_item,
)
from lea.calendars import CalendarEventTiming


def calendar_document(event: str) -> bytes:
    """Wrap one VEVENT fragment in a complete calendar."""
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//LEA//Calendar parser tests//EN\r\n"
        f"{event}"
        "END:VCALENDAR\r\n"
    ).encode()


def timed_event(
    *,
    uid: str = "timed@example.invalid",
    start: str = "DTSTART:20260801T080000Z\r\n",
    end: str = "DTEND:20260801T090000Z\r\n",
    extra: str = "",
) -> str:
    """Return one basic timed VEVENT fragment."""
    return (
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"{start}"
        f"{end}"
        "SUMMARY:Parser test\r\n"
        f"{extra}"
        "END:VEVENT\r\n"
    )


def test_parses_canonical_utc_event() -> None:
    """UTC events should become canonical immutable projections."""
    result = parse_khal_calendar_item(
        calendar_document(
            timed_event(
                extra=(
                    "DESCRIPTION:Strict parsing\r\n"
                    "LOCATION:Workshop\r\n"
                    "STATUS:CONFIRMED\r\n"
                )
            )
        ),
        calendar_id="personal",
    )

    assert result.success is True
    assert result.event is not None
    assert result.event.calendar_id == "personal"
    assert result.event.event_uid == "timed@example.invalid"
    assert result.event.summary == "Parser test"
    assert result.event.description == "Strict parsing"
    assert result.event.location == "Workshop"
    assert result.event.cancelled is False
    assert result.event.timing == CalendarEventTiming(
        start=datetime(2026, 8, 1, 8, 0, tzinfo=UTC),
        end=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        timezone="UTC",
    )


def test_converts_explicit_iana_timezone_to_utc() -> None:
    """TZID events should preserve the zone and store canonical instants."""
    result = parse_khal_calendar_item(
        calendar_document(
            timed_event(
                start=("DTSTART;TZID=Africa/Gaborone:20260802T100000\r\n"),
                end=("DTEND;TZID=Africa/Gaborone:20260802T110000\r\n"),
            )
        ),
        calendar_id="work",
    )

    assert result.success is True
    assert result.event is not None
    assert result.event.timing.start == datetime(
        2026,
        8,
        2,
        8,
        0,
        tzinfo=UTC,
    )
    assert result.event.timing.end == datetime(
        2026,
        8,
        2,
        9,
        0,
        tzinfo=UTC,
    )
    assert result.event.timing.timezone == "Africa/Gaborone"


def test_parses_half_open_all_day_event() -> None:
    """All-day dates should remain dates without a timezone."""
    document = calendar_document(
        "BEGIN:VEVENT\r\n"
        "UID:all-day@example.invalid\r\n"
        "DTSTART;VALUE=DATE:20260803\r\n"
        "DTEND;VALUE=DATE:20260804\r\n"
        "SUMMARY:All-day event\r\n"
        "END:VEVENT\r\n"
    )

    result = parse_khal_calendar_item(
        document,
        calendar_id="personal",
    )

    assert result.success is True
    assert result.event is not None
    assert result.event.timing == CalendarEventTiming(
        start=date(2026, 8, 3),
        end=date(2026, 8, 4),
        timezone=None,
    )


def test_cancelled_status_is_preserved() -> None:
    """STATUS:CANCELLED should map to the provider-neutral flag."""
    result = parse_khal_calendar_item(
        calendar_document(timed_event(extra="STATUS:CANCELLED\r\n")),
        calendar_id="personal",
    )

    assert result.success is True
    assert result.event is not None
    assert result.event.cancelled is True


@pytest.mark.parametrize(
    ("property_name", "fragment"),
    [
        ("UID", "UID:"),
        ("SUMMARY", "SUMMARY:"),
        ("DTSTART", "DTSTART:"),
        ("DTEND", "DTEND:"),
    ],
)
def test_missing_required_fields_fail_closed(
    property_name: str,
    fragment: str,
) -> None:
    """Required event fields must not be silently inferred."""
    event = timed_event()
    event = event.replace(
        next(
            line
            for line in event.splitlines(keepends=True)
            if line.startswith(fragment)
        ),
        "",
    )

    result = parse_khal_calendar_item(
        calendar_document(event),
        calendar_id="personal",
    )

    assert result.success is False
    assert result.event is None
    assert result.issues[0].code == "khal_icalendar_field_invalid"
    assert result.issues[0].field == property_name


def test_rejects_invalid_utf8() -> None:
    """Malformed text input should fail before iCalendar parsing."""
    result = parse_khal_calendar_item(
        b"\xff",
        calendar_id="personal",
    )

    assert result.success is False
    assert result.issues[0].code == ("khal_icalendar_item_invalid_utf8")


def test_rejects_malformed_calendar() -> None:
    """Invalid calendar syntax should return a structured issue."""
    result = parse_khal_calendar_item(
        b"not an iCalendar document",
        calendar_id="personal",
    )

    assert result.success is False
    assert result.issues[0].code in {
        "khal_icalendar_parse_failed",
        "khal_icalendar_event_count_invalid",
    }


def test_rejects_multiple_events_per_vdir_item() -> None:
    """One vdir item must represent exactly one logical event."""
    result = parse_khal_calendar_item(
        calendar_document(timed_event(uid="first")).replace(
            b"END:VCALENDAR\r\n",
            timed_event(uid="second").encode() + b"END:VCALENDAR\r\n",
        ),
        calendar_id="personal",
    )

    assert result.success is False
    assert result.issues[0].code == ("khal_icalendar_event_count_invalid")


@pytest.mark.parametrize(
    "recurrence",
    [
        "RDATE:20260802T080000Z\r\n",
        "EXDATE:20260802T080000Z\r\n",
        "RECURRENCE-ID:20260802T080000Z\r\n",
    ],
)
def test_rejects_recurrence_material(
    recurrence: str,
) -> None:
    """Unsupported recurrence must never be flattened silently."""
    result = parse_khal_calendar_item(
        calendar_document(timed_event(extra=recurrence)),
        calendar_id="personal",
    )

    assert result.success is False
    assert result.issues[0].code == ("khal_icalendar_recurrence_exception_unsupported")


def test_parses_supported_rrule_without_flattening() -> None:
    result = parse_khal_calendar_item(
        calendar_document(
            timed_event(extra="RRULE:FREQ=WEEKLY;INTERVAL=2;COUNT=3\r\n")
        ),
        calendar_id="work",
    )

    assert result.success is True
    assert result.event is not None
    assert result.event.recurrence is not None
    assert result.event.recurrence.to_rrule() == ("FREQ=WEEKLY;INTERVAL=2;COUNT=3")


def test_rejects_floating_time() -> None:
    """Naive local datetimes should remain explicitly unsupported."""
    result = parse_khal_calendar_item(
        calendar_document(
            timed_event(
                start="DTSTART:20260801T080000\r\n",
                end="DTEND:20260801T090000\r\n",
            )
        ),
        calendar_id="personal",
    )

    assert result.success is False
    assert result.issues[0].code == ("khal_icalendar_floating_time_unsupported")


def test_rejects_mixed_date_and_datetime_interval() -> None:
    """DTSTART and DTEND must use the same temporal type."""
    result = parse_khal_calendar_item(
        calendar_document(
            timed_event(
                start="DTSTART;VALUE=DATE:20260801\r\n",
            )
        ),
        calendar_id="personal",
    )

    assert result.success is False
    assert result.issues[0].code == "khal_icalendar_field_invalid"


def test_rejects_mismatched_tzid() -> None:
    """Both timed interval boundaries must use one exact TZID."""
    result = parse_khal_calendar_item(
        calendar_document(
            timed_event(
                start=("DTSTART;TZID=Africa/Gaborone:20260802T100000\r\n"),
                end=("DTEND;TZID=Africa/Johannesburg:20260802T110000\r\n"),
            )
        ),
        calendar_id="personal",
    )

    assert result.success is False
    assert result.issues[0].code == ("khal_icalendar_timezone_invalid")


def test_rejects_unsupported_status() -> None:
    """Unknown status values should not be treated as active."""
    result = parse_khal_calendar_item(
        calendar_document(timed_event(extra="STATUS:UNKNOWN\r\n")),
        calendar_id="personal",
    )

    assert result.success is False
    assert result.issues[0].code == "khal_icalendar_field_invalid"
    assert result.issues[0].field == "STATUS"


def test_rejects_oversized_document() -> None:
    """Direct parsing should enforce the same bounded item limit."""
    result = parse_khal_calendar_item(
        b"x" * (KHAL_MAX_ICALENDAR_ITEM_BYTES + 1),
        calendar_id="personal",
    )

    assert result.success is False
    assert result.issues[0].code == ("khal_icalendar_item_too_large")


def test_reads_exact_regular_ics_file(
    tmp_path: Path,
) -> None:
    """The filesystem boundary should accept only regular `.ics` items."""
    item = tmp_path / "event.ics"
    item.write_bytes(calendar_document(timed_event()))

    result = read_khal_calendar_item(
        item,
        calendar_id="personal",
    )

    assert result.success is True
    assert result.event is not None


def test_rejects_missing_symbolic_and_wrong_suffix_items(
    tmp_path: Path,
) -> None:
    """Unsafe vdir item paths should fail before parsing."""
    missing_result = read_khal_calendar_item(
        tmp_path / "missing.ics",
        calendar_id="personal",
    )
    assert missing_result.issues[0].code == ("khal_icalendar_item_missing")

    target = tmp_path / "target.ics"
    target.write_bytes(calendar_document(timed_event()))
    symbolic = tmp_path / "symbolic.ics"
    symbolic.symlink_to(target)

    symbolic_result = read_khal_calendar_item(
        symbolic,
        calendar_id="personal",
    )
    assert symbolic_result.issues[0].code == ("khal_icalendar_item_unsafe")

    wrong_suffix = tmp_path / "event.txt"
    wrong_suffix.write_bytes(calendar_document(timed_event()))
    suffix_result = read_khal_calendar_item(
        wrong_suffix,
        calendar_id="personal",
    )
    assert suffix_result.issues[0].code == ("khal_icalendar_item_unsafe")


def test_parse_result_contract_rejects_ambiguity() -> None:
    """Adapter parse results must not mix success and failure state."""
    with pytest.raises(ValueError, match="must contain an event"):
        KhalCalendarItemParseResult(
            success=True,
            event=None,
            issues=(),
        )

    with pytest.raises(ValueError, match="at least one issue"):
        KhalCalendarItemParseResult(
            success=False,
            event=None,
            issues=(),
        )


def test_parser_rejects_invalid_programming_inputs(
    tmp_path: Path,
) -> None:
    """Caller errors should be rejected before provider work."""
    with pytest.raises(TypeError, match="document must be bytes"):
        parse_khal_calendar_item(
            "text",  # type: ignore[arg-type]
            calendar_id="personal",
        )

    with pytest.raises(ValueError, match="calendar_id"):
        parse_khal_calendar_item(
            b"",
            calendar_id=" ",
        )

    with pytest.raises(ValueError, match="greater than zero"):
        read_khal_calendar_item(
            tmp_path / "event.ics",
            calendar_id="personal",
            maximum_bytes=0,
        )
