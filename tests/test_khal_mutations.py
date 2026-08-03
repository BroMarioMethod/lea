"""Tests for safe local-vdir calendar mutations."""

from datetime import UTC, date, datetime
from pathlib import Path

from lea.adapters.khal import (
    KhalConfig,
    cancel_khal_calendar_event,
    create_khal_calendar_event,
    modify_khal_calendar_event,
)
from lea.calendars import (
    CalendarCancelRequest,
    CalendarCreateRequest,
    CalendarEventTiming,
    CalendarModifyRequest,
)


def _config(tmp_path: Path) -> KhalConfig:
    for directory in ("vdirs", "state", "work", "bin", "config"):
        (tmp_path / directory).mkdir(parents=True)
    executable = tmp_path / "bin" / "khal"
    configuration = tmp_path / "config" / "khal.conf"
    executable.write_text("executable", encoding="utf-8")
    configuration.write_text("configuration", encoding="utf-8")
    return KhalConfig(
        executable=executable,
        configuration=configuration,
        vdirs_directory=tmp_path / "vdirs",
        state_directory=tmp_path / "state",
        working_directory=tmp_path / "work",
        expected_version="0.11.4",
        display_timezone="Africa/Gaborone",
    )


def test_create_all_day_event_atomically_and_read_back(tmp_path: Path) -> None:
    config = _config(tmp_path)
    collection = config.vdirs_directory / "personal"
    collection.mkdir()

    result = create_khal_calendar_event(
        config,
        CalendarCreateRequest(
            calendar_id="personal",
            summary="Public holiday",
            timing=CalendarEventTiming(date(2026, 8, 2), date(2026, 8, 3)),
            description="Rest",
        ),
        uid_factory=lambda: "event-1@lea.local",
    )

    assert result.success is True
    assert result.event is not None
    assert result.event.event_uid == "event-1@lea.local"
    assert result.event.summary == "Public holiday"
    assert result.event.description == "Rest"
    assert (collection / "event-1@lea.local.ics").stat().st_mode & 0o777 == 0o600
    assert not tuple(collection.glob(".lea-create-*"))


def test_create_timed_event_preserves_canonical_utc_and_timezone(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    (config.vdirs_directory / "work").mkdir()
    timing = CalendarEventTiming(
        datetime(2026, 8, 2, 8, tzinfo=UTC),
        datetime(2026, 8, 2, 9, tzinfo=UTC),
        "Africa/Gaborone",
    )

    result = create_khal_calendar_event(
        config,
        CalendarCreateRequest("work", "Meeting", timing, location="Office"),
        uid_factory=lambda: "event-2@lea.local",
    )

    assert result.success is True
    assert result.event is not None
    assert result.event.timing == timing
    assert result.event.location == "Office"


def test_create_rejects_unknown_calendar_without_writing(tmp_path: Path) -> None:
    config = _config(tmp_path)

    result = create_khal_calendar_event(
        config,
        CalendarCreateRequest(
            "missing",
            "Event",
            CalendarEventTiming(date(2026, 8, 2), date(2026, 8, 3)),
        ),
        uid_factory=lambda: "event-3@lea.local",
    )

    assert result.success is False
    assert result.issues[0].code == "khal_calendar_not_found"
    assert not tuple(config.vdirs_directory.rglob("*.ics"))


def test_create_fails_closed_on_uid_collision(tmp_path: Path) -> None:
    config = _config(tmp_path)
    collection = config.vdirs_directory / "personal"
    collection.mkdir()
    existing = collection / "event-4@lea.local.ics"
    existing.write_bytes(b"existing")

    result = create_khal_calendar_event(
        config,
        CalendarCreateRequest(
            "personal",
            "Event",
            CalendarEventTiming(date(2026, 8, 2), date(2026, 8, 3)),
        ),
        uid_factory=lambda: "event-4@lea.local",
    )

    assert result.success is False
    assert result.issues[0].code == "khal_calendar_event_create_failed"
    assert existing.read_bytes() == b"existing"
    assert not tuple(collection.glob(".lea-create-*"))


def test_create_rejects_unsafe_generated_uid(tmp_path: Path) -> None:
    config = _config(tmp_path)
    (config.vdirs_directory / "personal").mkdir()

    result = create_khal_calendar_event(
        config,
        CalendarCreateRequest(
            "personal",
            "Event",
            CalendarEventTiming(date(2026, 8, 2), date(2026, 8, 3)),
        ),
        uid_factory=lambda: "../escape",
    )

    assert result.success is False
    assert result.issues[0].code == "khal_calendar_uid_generation_failed"
    assert not tuple(config.vdirs_directory.rglob("*.ics"))


def test_modify_exact_event_preserves_identity_and_unmodified_fields(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    (config.vdirs_directory / "personal").mkdir()
    created = create_khal_calendar_event(
        config,
        CalendarCreateRequest(
            "personal",
            "Original",
            CalendarEventTiming(date(2026, 8, 2), date(2026, 8, 3)),
            description="Description",
            location="Office",
        ),
        uid_factory=lambda: "event-5@lea.local",
    )
    assert created.success

    result = modify_khal_calendar_event(
        config,
        CalendarModifyRequest(
            "personal",
            "event-5@lea.local",
            summary="Changed",
            clear_location=True,
        ),
    )

    assert result.success is True
    assert result.event is not None
    assert result.event.event_uid == "event-5@lea.local"
    assert result.event.summary == "Changed"
    assert result.event.description == "Description"
    assert result.event.location is None
    assert not tuple(config.vdirs_directory.rglob(".lea-modify-*"))


def test_modify_fails_closed_for_missing_or_duplicate_identity(tmp_path: Path) -> None:
    config = _config(tmp_path)
    collection = config.vdirs_directory / "personal"
    collection.mkdir()
    request = CalendarCreateRequest(
        "personal",
        "Original",
        CalendarEventTiming(date(2026, 8, 2), date(2026, 8, 3)),
    )
    created = create_khal_calendar_event(
        config,
        request,
        uid_factory=lambda: "event-6@lea.local",
    )
    assert created.success
    source = collection / "event-6@lea.local.ics"
    duplicate = collection / "duplicate.ics"
    duplicate.write_bytes(source.read_bytes())
    original = source.read_bytes()

    duplicate_result = modify_khal_calendar_event(
        config,
        CalendarModifyRequest("personal", "event-6@lea.local", summary="Changed"),
    )
    missing_result = modify_khal_calendar_event(
        config,
        CalendarModifyRequest("personal", "missing", summary="Changed"),
    )

    assert duplicate_result.success is False
    assert duplicate_result.issues[0].code == ("khal_calendar_event_identity_duplicate")
    assert missing_result.success is False
    assert missing_result.issues[0].code == "khal_calendar_event_not_found"
    assert source.read_bytes() == original


def test_cancel_exact_event_is_persistent_and_idempotent(tmp_path: Path) -> None:
    config = _config(tmp_path)
    (config.vdirs_directory / "personal").mkdir()
    created = create_khal_calendar_event(
        config,
        CalendarCreateRequest(
            "personal",
            "Event",
            CalendarEventTiming(date(2026, 8, 2), date(2026, 8, 3)),
        ),
        uid_factory=lambda: "event-7@lea.local",
    )
    assert created.success
    request = CalendarCancelRequest("personal", "event-7@lea.local")

    first = cancel_khal_calendar_event(config, request)
    second = cancel_khal_calendar_event(config, request)

    assert first.success is True
    assert first.event is not None and first.event.cancelled is True
    assert second == first
    document = config.vdirs_directory / "personal" / "event-7@lea.local.ics"
    assert b"STATUS:CANCELLED" in document.read_bytes()
