"""Tests for deterministic local khal vdir event listing."""

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from lea.adapters.khal import (
    KHAL_MAX_ICALENDAR_ITEM_BYTES,
    KhalConfig,
    list_khal_calendar_events,
)
from lea.calendars import CalendarEventQuery


def make_config(
    tmp_path: Path,
    *,
    display_timezone: str = "Africa/Gaborone",
) -> KhalConfig:
    """Return one isolated local khal configuration."""
    executable = tmp_path / "bin" / "khal"
    configuration = tmp_path / "config" / "khal.conf"
    vdirs_directory = tmp_path / "state" / "vdirs"
    state_directory = tmp_path / "state" / "khal"
    working_directory = tmp_path / "working"

    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    configuration.parent.mkdir(parents=True)
    configuration.write_text("[calendars]\n", encoding="utf-8")
    vdirs_directory.mkdir(parents=True)
    state_directory.mkdir(parents=True)
    working_directory.mkdir()

    return KhalConfig(
        executable=executable,
        configuration=configuration,
        vdirs_directory=vdirs_directory,
        state_directory=state_directory,
        working_directory=working_directory,
        expected_version="0.11.4",
        display_timezone=display_timezone,
    )


def make_collection(
    config: KhalConfig,
    calendar_id: str,
) -> Path:
    """Create one local calendar collection."""
    collection = config.vdirs_directory / calendar_id
    collection.mkdir()
    return collection


def write_event(
    collection: Path,
    filename: str,
    *,
    uid: str,
    start: str,
    end: str,
    summary: str | None = None,
    status: str | None = None,
) -> Path:
    """Write one strict non-recurring vdir event item."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//LEA//Event-list tests//EN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTART{start}",
        f"DTEND{end}",
        f"SUMMARY:{summary or uid}",
    ]

    if status is not None:
        lines.append(f"STATUS:{status}")

    lines.extend(
        [
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )
    path = collection / filename
    path.write_bytes("\r\n".join(lines).encode("utf-8"))
    return path


def query(
    *,
    start: date = date(2026, 8, 1),
    end: date = date(2026, 8, 2),
    calendar_ids: tuple[str, ...] = (),
    include_cancelled: bool = False,
) -> CalendarEventQuery:
    """Return one supported immutable list query."""
    return CalendarEventQuery(
        start_date=start,
        end_date=end,
        calendar_ids=calendar_ids,
        include_cancelled=include_cancelled,
    )


def test_empty_collection_set_returns_empty_success(
    tmp_path: Path,
) -> None:
    """No collections should produce one valid empty result."""
    result = list_khal_calendar_events(
        make_config(tmp_path),
        query(),
    )

    assert result.success is True
    assert result.events == ()
    assert result.issues == ()


def test_lists_events_in_display_local_deterministic_order(
    tmp_path: Path,
) -> None:
    """All-day events should precede timed events at the same local date."""
    config = make_config(tmp_path)
    personal = make_collection(config, "personal")
    work = make_collection(config, "work")

    write_event(
        work,
        "late.ics",
        uid="late",
        start=":20260801T090000Z",
        end=":20260801T100000Z",
    )
    write_event(
        personal,
        "all-day.ics",
        uid="all-day",
        start=";VALUE=DATE:20260801",
        end=";VALUE=DATE:20260802",
    )
    write_event(
        personal,
        "early.ics",
        uid="early",
        start=":20260801T060000Z",
        end=":20260801T070000Z",
    )

    result = list_khal_calendar_events(config, query())

    assert result.success is True
    assert tuple(event.event_uid for event in result.events) == (
        "all-day",
        "early",
        "late",
    )


def test_calendar_filter_is_explicit_and_unknown_ids_fail(
    tmp_path: Path,
) -> None:
    """Requested calendar IDs should be selected without implicit fallback."""
    config = make_config(tmp_path)
    personal = make_collection(config, "personal")
    work = make_collection(config, "work")
    write_event(
        personal,
        "personal.ics",
        uid="personal-event",
        start=":20260801T080000Z",
        end=":20260801T090000Z",
    )
    write_event(
        work,
        "work.ics",
        uid="work-event",
        start=":20260801T080000Z",
        end=":20260801T090000Z",
    )

    selected = list_khal_calendar_events(
        config,
        query(calendar_ids=("work",)),
    )

    assert selected.success is True
    assert tuple(event.event_uid for event in selected.events) == ("work-event",)

    unknown = list_khal_calendar_events(
        config,
        query(calendar_ids=("missing",)),
    )

    assert unknown.success is False
    assert unknown.events == ()
    assert unknown.issues[0].code == "khal_calendar_not_found"
    assert unknown.issues[0].calendar_id == "missing"
    assert unknown.issues[0].operation == "list_events"


def test_unselected_malformed_items_are_not_parsed(
    tmp_path: Path,
) -> None:
    """An explicit filter should bound item parsing to selected calendars."""
    config = make_config(tmp_path)
    selected = make_collection(config, "selected")
    unselected = make_collection(config, "unselected")
    write_event(
        selected,
        "event.ics",
        uid="selected-event",
        start=":20260801T080000Z",
        end=":20260801T090000Z",
    )
    (unselected / "broken.ics").write_bytes(b"not iCalendar")

    result = list_khal_calendar_events(
        config,
        query(calendar_ids=("selected",)),
    )

    assert result.success is True
    assert tuple(event.event_uid for event in result.events) == ("selected-event",)


def test_all_day_overlap_uses_half_open_dates(
    tmp_path: Path,
) -> None:
    """Date-only intervals should use strict half-open overlap."""
    config = make_config(tmp_path)
    collection = make_collection(config, "personal")
    write_event(
        collection,
        "ends-at-start.ics",
        uid="ends-at-start",
        start=";VALUE=DATE:20260731",
        end=";VALUE=DATE:20260801",
    )
    write_event(
        collection,
        "overlaps.ics",
        uid="overlaps",
        start=";VALUE=DATE:20260731",
        end=";VALUE=DATE:20260802",
    )
    write_event(
        collection,
        "starts-at-end.ics",
        uid="starts-at-end",
        start=";VALUE=DATE:20260802",
        end=";VALUE=DATE:20260803",
    )

    result = list_khal_calendar_events(config, query())

    assert result.success is True
    assert tuple(event.event_uid for event in result.events) == ("overlaps",)


def test_timed_overlap_uses_configured_display_timezone(
    tmp_path: Path,
) -> None:
    """UTC events should be filtered by local display-date boundaries."""
    config = make_config(tmp_path, display_timezone="Africa/Gaborone")
    collection = make_collection(config, "personal")
    write_event(
        collection,
        "before.ics",
        uid="before",
        start=":20260731T210000Z",
        end=":20260731T213000Z",
    )
    write_event(
        collection,
        "local-after-midnight.ics",
        uid="local-after-midnight",
        start=":20260731T223000Z",
        end=":20260731T233000Z",
    )
    write_event(
        collection,
        "ends-at-start.ics",
        uid="ends-at-start",
        start=":20260731T210000Z",
        end=":20260731T220000Z",
    )
    write_event(
        collection,
        "starts-at-end.ics",
        uid="starts-at-end",
        start=":20260801T220000Z",
        end=":20260801T230000Z",
    )

    result = list_khal_calendar_events(config, query())

    assert result.success is True
    assert tuple(event.event_uid for event in result.events) == (
        "local-after-midnight",
    )


def test_cancelled_events_are_filtered_unless_requested(
    tmp_path: Path,
) -> None:
    """Cancellation state should remain explicit and query-controlled."""
    config = make_config(tmp_path)
    collection = make_collection(config, "personal")
    write_event(
        collection,
        "confirmed.ics",
        uid="confirmed",
        start=":20260801T080000Z",
        end=":20260801T090000Z",
        status="CONFIRMED",
    )
    write_event(
        collection,
        "cancelled.ics",
        uid="cancelled",
        start=":20260801T100000Z",
        end=":20260801T110000Z",
        status="CANCELLED",
    )

    default_result = list_khal_calendar_events(config, query())
    included_result = list_khal_calendar_events(
        config,
        query(include_cancelled=True),
    )

    assert tuple(event.event_uid for event in default_result.events) == ("confirmed",)
    assert tuple(event.event_uid for event in included_result.events) == (
        "confirmed",
        "cancelled",
    )
    assert included_result.events[1].cancelled is True


def test_duplicate_identity_within_one_calendar_fails(
    tmp_path: Path,
) -> None:
    """Two items must not claim the same composite stable identity."""
    config = make_config(tmp_path)
    collection = make_collection(config, "personal")

    for filename in ("first.ics", "second.ics"):
        write_event(
            collection,
            filename,
            uid="duplicate",
            start=":20260801T080000Z",
            end=":20260801T090000Z",
        )

    result = list_khal_calendar_events(config, query())

    assert result.success is False
    assert result.events == ()
    assert result.issues[0].code == ("khal_calendar_event_identity_duplicate")
    assert result.issues[0].calendar_id == "personal"
    assert result.issues[0].event_uid == "duplicate"


def test_same_uid_in_different_calendars_is_valid(
    tmp_path: Path,
) -> None:
    """Stable identity is the calendar ID and event UID pair."""
    config = make_config(tmp_path)

    for calendar_id in ("personal", "work"):
        collection = make_collection(config, calendar_id)
        write_event(
            collection,
            "shared.ics",
            uid="shared",
            start=":20260801T080000Z",
            end=":20260801T090000Z",
        )

    result = list_khal_calendar_events(config, query())

    assert result.success is True
    assert tuple((event.calendar_id, event.event_uid) for event in result.events) == (
        ("personal", "shared"),
        ("work", "shared"),
    )


def test_parser_failures_are_remapped_to_list_operation(
    tmp_path: Path,
) -> None:
    """Item diagnostics should remain structured under list_events."""
    config = make_config(tmp_path)
    collection = make_collection(config, "personal")
    (collection / "broken.ics").write_bytes(b"not iCalendar")

    result = list_khal_calendar_events(config, query())

    assert result.success is False
    assert result.events == ()
    assert result.issues[0].code == "khal_icalendar_parse_failed"
    assert result.issues[0].operation == "list_events"
    assert result.issues[0].calendar_id == "personal"


def test_hidden_and_non_ics_metadata_are_ignored(
    tmp_path: Path,
) -> None:
    """Only immediate visible `.ics` vdir items should be parsed."""
    config = make_config(tmp_path)
    collection = make_collection(config, "personal")
    write_event(
        collection,
        "visible.ics",
        uid="visible",
        start=":20260801T080000Z",
        end=":20260801T090000Z",
    )
    (collection / ".hidden.ics").write_bytes(b"not iCalendar")
    (collection / "displayname").write_text(
        "Personal calendar\n",
        encoding="utf-8",
    )
    (collection / "colour").write_text("#ffffff\n", encoding="utf-8")
    (collection / "archive").mkdir()

    result = list_khal_calendar_events(config, query())

    assert result.success is True
    assert tuple(event.event_uid for event in result.events) == ("visible",)


def test_symbolic_and_non_regular_ics_items_fail_closed(
    tmp_path: Path,
) -> None:
    """Candidate `.ics` paths must pass the strict item reader."""
    config = make_config(tmp_path)
    collection = make_collection(config, "personal")
    outside = tmp_path / "outside.ics"
    outside.write_bytes(b"not relevant")
    (collection / "linked.ics").symlink_to(outside)

    symbolic = list_khal_calendar_events(config, query())

    assert symbolic.success is False
    assert symbolic.issues[0].code == "khal_icalendar_item_unsafe"
    assert symbolic.issues[0].operation == "list_events"

    (collection / "linked.ics").unlink()
    (collection / "directory.ics").mkdir()
    directory = list_khal_calendar_events(config, query())

    assert directory.success is False
    assert directory.issues[0].code == "khal_icalendar_item_unsafe"


def test_item_size_limit_is_forwarded(
    tmp_path: Path,
) -> None:
    """The event scanner should preserve the bounded parser policy."""
    config = make_config(tmp_path)
    collection = make_collection(config, "personal")
    write_event(
        collection,
        "event.ics",
        uid="event",
        start=":20260801T080000Z",
        end=":20260801T090000Z",
    )

    result = list_khal_calendar_events(
        config,
        query(),
        maximum_item_bytes=10,
    )

    assert result.success is False
    assert result.issues[0].code == "khal_icalendar_item_too_large"


def test_display_timezone_is_validated_by_configuration(
    tmp_path: Path,
) -> None:
    """Query-date interpretation requires a valid IANA timezone."""
    config = make_config(tmp_path)

    with pytest.raises(ValueError, match="display_timezone"):
        replace(config, display_timezone="Not/AZone")


def test_programming_inputs_are_validated(
    tmp_path: Path,
) -> None:
    """Caller errors should fail before any filesystem read."""
    config = make_config(tmp_path)

    with pytest.raises(TypeError, match="KhalConfig"):
        list_khal_calendar_events(
            object(),  # type: ignore[arg-type]
            query(),
        )

    with pytest.raises(TypeError, match="CalendarEventQuery"):
        list_khal_calendar_events(
            config,
            object(),  # type: ignore[arg-type]
        )

    with pytest.raises(TypeError, match="must be an integer"):
        list_khal_calendar_events(
            config,
            query(),
            maximum_item_bytes=True,
        )

    with pytest.raises(ValueError, match="greater than zero"):
        list_khal_calendar_events(
            config,
            query(),
            maximum_item_bytes=0,
        )


def test_query_bounds_preserve_canonical_utc_events(
    tmp_path: Path,
) -> None:
    """Returned timed events should remain canonical UTC projections."""
    config = make_config(tmp_path)
    collection = make_collection(config, "personal")
    write_event(
        collection,
        "event.ics",
        uid="event",
        start=";TZID=Africa/Gaborone:20260801T100000",
        end=";TZID=Africa/Gaborone:20260801T110000",
    )

    result = list_khal_calendar_events(config, query())

    assert result.success is True
    event = result.events[0]
    assert event.timing.start == datetime(
        2026,
        8,
        1,
        8,
        0,
        tzinfo=UTC,
    )
    assert event.timing.end == datetime(
        2026,
        8,
        1,
        9,
        0,
        tzinfo=UTC,
    )
    assert event.timing.timezone == "Africa/Gaborone"


def test_default_limits_remain_stable() -> None:
    """The public default item bound should remain explicit."""
    assert KHAL_MAX_ICALENDAR_ITEM_BYTES == 1_048_576
