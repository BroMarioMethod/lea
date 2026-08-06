"""Tests for the assembled read-only khal calendar provider."""

import sys
from datetime import date
from pathlib import Path

import pytest

from lea.adapters.khal import (
    KhalCalendarProvider,
    KhalConfig,
    KhalRunner,
)
from lea.calendars import (
    CalendarCancelRequest,
    CalendarCreateRequest,
    CalendarEventQuery,
    CalendarEventTiming,
    CalendarModifyRequest,
    CalendarProvider,
)


def make_config(
    tmp_path: Path,
    *,
    version: str = "0.11.4",
) -> KhalConfig:
    """Return one complete isolated khal provider configuration."""
    executable = tmp_path / "bin" / "khal"
    configuration = tmp_path / "config" / "khal.conf"
    vdirs_directory = tmp_path / "state" / "vdirs"
    state_directory = tmp_path / "state" / "khal"
    working_directory = tmp_path / "working"

    executable.parent.mkdir(parents=True)
    executable.write_text(
        (f"#!{sys.executable}\nimport sys\nprint('khal, version {version}')\n"),
        encoding="utf-8",
    )
    executable.chmod(0o700)
    configuration.parent.mkdir(parents=True)
    configuration.write_text(
        "[locale]\nlocal_timezone = Africa/Gaborone\n",
        encoding="utf-8",
    )
    vdirs_directory.mkdir(parents=True)
    state_directory.mkdir(parents=True)
    working_directory.mkdir(parents=True)

    return KhalConfig(
        executable=executable,
        configuration=configuration,
        vdirs_directory=vdirs_directory,
        state_directory=state_directory,
        working_directory=working_directory,
        expected_version=version,
        display_timezone="Africa/Gaborone",
    )


def write_event(
    collection: Path,
    *,
    filename: str = "event.ics",
    uid: str = "event-uid",
    summary: str = "Provider event",
) -> Path:
    """Write one strict local vdir event."""
    item = collection / filename
    item.write_bytes(
        (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//LEA//Provider tests//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            "DTSTART;TZID=Africa/Gaborone:20260801T100000\r\n"
            "DTEND;TZID=Africa/Gaborone:20260801T110000\r\n"
            f"SUMMARY:{summary}\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        ).encode()
    )
    return item


def test_provider_is_protocol_compatible_and_exposes_config(
    tmp_path: Path,
) -> None:
    """The assembled object should satisfy the complete provider protocol."""
    config = make_config(tmp_path)
    provider = KhalCalendarProvider(config)

    assert isinstance(provider, CalendarProvider)
    assert provider.config is config


def test_provider_inspection_uses_exact_configured_runner(
    tmp_path: Path,
) -> None:
    """Inspection should preserve the existing khal compatibility boundary."""
    provider = KhalCalendarProvider(make_config(tmp_path))

    result = provider.inspect()

    assert result.available is True
    assert result.provider == "khal"
    assert result.version == "0.11.4"
    assert result.issues == ()


def test_provider_delegates_complete_read_only_lifecycle(
    tmp_path: Path,
) -> None:
    """Calendar discovery, listing and exact lookup should share one config."""
    config = make_config(tmp_path)
    collection = config.vdirs_directory / "personal"
    collection.mkdir()
    (collection / "displayname").write_text(
        "Personal calendar\n",
        encoding="utf-8",
    )
    write_event(collection)
    provider = KhalCalendarProvider(config)

    calendars = provider.list_calendars()
    events = provider.list_events(
        CalendarEventQuery(
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
        )
    )
    shown = provider.show_event(
        "personal",
        "event-uid",
    )

    assert calendars.success is True
    assert tuple(
        (calendar.calendar_id, calendar.display_name)
        for calendar in calendars.calendars
    ) == (("personal", "Personal calendar"),)

    assert events.success is True
    assert tuple(event.event_uid for event in events.events) == ("event-uid",)

    assert shown.success is True
    assert shown.event is not None
    assert shown.event.calendar_id == "personal"
    assert shown.event.event_uid == "event-uid"


def test_provider_preserves_read_failure_results(
    tmp_path: Path,
) -> None:
    """Read-side parser failures should pass through the assembled provider."""
    config = make_config(tmp_path)
    collection = config.vdirs_directory / "personal"
    collection.mkdir()
    (collection / "broken.ics").write_bytes(b"not iCalendar")
    provider = KhalCalendarProvider(config)

    result = provider.list_events(
        CalendarEventQuery(
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
        )
    )

    assert result.success is False
    assert result.events == ()
    assert result.issues[0].code == "khal_icalendar_parse_failed"
    assert result.issues[0].operation == "list_events"


def test_provider_executes_complete_local_mutation_lifecycle(
    tmp_path: Path,
) -> None:
    """The read-only provider should satisfy the protocol without mutation."""
    config = make_config(tmp_path)
    collection = config.vdirs_directory / "personal"
    collection.mkdir()
    item = write_event(collection)
    provider = KhalCalendarProvider(config)
    timing = CalendarEventTiming(
        start=date(2026, 8, 2),
        end=date(2026, 8, 3),
    )

    created = provider.create_event(
        CalendarCreateRequest(
            calendar_id="personal",
            summary="New event",
            timing=timing,
        )
    )
    modified = provider.modify_event(
        CalendarModifyRequest(
            calendar_id="personal",
            event_uid="event-uid",
            summary="Changed event",
        )
    )
    cancelled = provider.cancel_event(
        CalendarCancelRequest(
            calendar_id="personal",
            event_uid="event-uid",
        )
    )

    assert created.success is True
    assert created.event is not None
    assert created.event.calendar_id == "personal"
    assert created.event.summary == "New event"

    assert modified.success is True
    assert modified.event is not None
    assert modified.event.summary == "Changed event"

    assert cancelled.success is True
    assert cancelled.event is not None
    assert cancelled.event.cancelled is True
    assert cancelled.event.event_uid == "event-uid"
    assert b"SUMMARY:Changed event" in item.read_bytes()
    assert len(tuple(collection.glob("*.ics"))) == 2


def test_provider_rejects_mismatched_runner_configuration(
    tmp_path: Path,
) -> None:
    """Injected runners must belong to the same immutable configuration."""
    first = make_config(tmp_path / "first")
    second = make_config(tmp_path / "second")

    with pytest.raises(ValueError, match="runner configuration"):
        KhalCalendarProvider(
            first,
            runner=KhalRunner(second),
        )


def test_provider_rejects_invalid_programming_inputs(
    tmp_path: Path,
) -> None:
    """Programming errors should fail before provider work."""
    config = make_config(tmp_path)
    provider = KhalCalendarProvider(config)

    with pytest.raises(TypeError, match="KhalConfig"):
        KhalCalendarProvider(
            object(),  # type: ignore[arg-type]
        )

    with pytest.raises(TypeError, match="CalendarCreateRequest"):
        provider.create_event(
            object(),  # type: ignore[arg-type]
        )

    with pytest.raises(TypeError, match="CalendarModifyRequest"):
        provider.modify_event(
            object(),  # type: ignore[arg-type]
        )

    with pytest.raises(TypeError, match="CalendarCancelRequest"):
        provider.cancel_event(
            object(),  # type: ignore[arg-type]
        )
