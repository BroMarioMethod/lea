"""Tests for deterministic exact local khal event lookup."""

from pathlib import Path

import pytest

from lea.adapters.khal import (
    KHAL_MAX_ICALENDAR_ITEM_BYTES,
    KhalConfig,
    show_khal_calendar_event,
)


def make_config(tmp_path: Path) -> KhalConfig:
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
        display_timezone="Africa/Gaborone",
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
    summary: str,
    status: str | None = None,
) -> Path:
    """Write one strict timed vdir event."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//LEA//Show-event tests//EN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        "DTSTART:20260801T080000Z",
        "DTEND:20260801T090000Z",
        f"SUMMARY:{summary}",
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


def test_reads_one_exact_event_by_composite_identity(
    tmp_path: Path,
) -> None:
    """Calendar ID and UID should be the only lookup identity."""
    config = make_config(tmp_path)
    collection = make_collection(config, "personal")
    write_event(
        collection,
        "opaque-file-name.ics",
        uid="stable-uid",
        summary="Mutable summary",
    )

    result = show_khal_calendar_event(
        config,
        "personal",
        "stable-uid",
    )

    assert result.success is True
    assert result.event is not None
    assert result.event.calendar_id == "personal"
    assert result.event.event_uid == "stable-uid"
    assert result.event.summary == "Mutable summary"
    assert result.issues == ()


def test_cancelled_event_remains_visible(
    tmp_path: Path,
) -> None:
    """Exact lookup should not hide cancellation state."""
    config = make_config(tmp_path)
    collection = make_collection(config, "personal")
    write_event(
        collection,
        "cancelled.ics",
        uid="cancelled",
        summary="Cancelled event",
        status="CANCELLED",
    )

    result = show_khal_calendar_event(
        config,
        "personal",
        "cancelled",
    )

    assert result.success is True
    assert result.event is not None
    assert result.event.cancelled is True


def test_unknown_calendar_returns_structured_failure(
    tmp_path: Path,
) -> None:
    """Exact lookup must not fall back to another calendar."""
    config = make_config(tmp_path)
    make_collection(config, "personal")

    result = show_khal_calendar_event(
        config,
        "missing",
        "event",
    )

    assert result.success is False
    assert result.event is None
    assert result.issues[0].code == "khal_calendar_not_found"
    assert result.issues[0].calendar_id == "missing"
    assert result.issues[0].operation == "show_event"


def test_missing_event_returns_structured_failure(
    tmp_path: Path,
) -> None:
    """Zero UID matches should be distinguishable from provider failure."""
    config = make_config(tmp_path)
    collection = make_collection(config, "personal")
    write_event(
        collection,
        "other.ics",
        uid="other",
        summary="Other event",
    )

    result = show_khal_calendar_event(
        config,
        "personal",
        "missing",
    )

    assert result.success is False
    assert result.event is None
    assert result.issues[0].code == "khal_calendar_event_not_found"
    assert result.issues[0].event_uid == "missing"
    assert result.issues[0].operation == "show_event"


def test_filename_and_summary_are_not_identity(
    tmp_path: Path,
) -> None:
    """Mutable or storage-facing text must never select an event."""
    config = make_config(tmp_path)
    collection = make_collection(config, "personal")
    write_event(
        collection,
        "filename-match.ics",
        uid="actual-uid",
        summary="summary-match",
    )

    filename_result = show_khal_calendar_event(
        config,
        "personal",
        "filename-match",
    )
    summary_result = show_khal_calendar_event(
        config,
        "personal",
        "summary-match",
    )

    assert filename_result.success is False
    assert filename_result.issues[0].code == ("khal_calendar_event_not_found")
    assert summary_result.success is False
    assert summary_result.issues[0].code == ("khal_calendar_event_not_found")


def test_duplicate_target_identity_fails_closed(
    tmp_path: Path,
) -> None:
    """Multiple target UID matches should be reported as corruption."""
    config = make_config(tmp_path)
    collection = make_collection(config, "personal")

    for filename in ("first.ics", "second.ics"):
        write_event(
            collection,
            filename,
            uid="duplicate",
            summary=filename,
        )

    result = show_khal_calendar_event(
        config,
        "personal",
        "duplicate",
    )

    assert result.success is False
    assert result.event is None
    assert result.issues[0].code == ("khal_calendar_event_identity_duplicate")
    assert result.issues[0].calendar_id == "personal"
    assert result.issues[0].event_uid == "duplicate"


def test_same_uid_in_another_calendar_is_not_ambiguous(
    tmp_path: Path,
) -> None:
    """Composite identity should bound lookup to one exact calendar."""
    config = make_config(tmp_path)

    for calendar_id in ("personal", "work"):
        collection = make_collection(config, calendar_id)
        write_event(
            collection,
            "shared.ics",
            uid="shared",
            summary=calendar_id,
        )

    result = show_khal_calendar_event(
        config,
        "work",
        "shared",
    )

    assert result.success is True
    assert result.event is not None
    assert result.event.calendar_id == "work"
    assert result.event.summary == "work"


def test_unselected_calendar_is_not_parsed(
    tmp_path: Path,
) -> None:
    """Malformed items outside the selected calendar must remain isolated."""
    config = make_config(tmp_path)
    selected = make_collection(config, "selected")
    unselected = make_collection(config, "unselected")
    write_event(
        selected,
        "target.ics",
        uid="target",
        summary="Target",
    )
    (unselected / "broken.ics").write_bytes(b"not iCalendar")

    result = show_khal_calendar_event(
        config,
        "selected",
        "target",
    )

    assert result.success is True
    assert result.event is not None
    assert result.event.event_uid == "target"


def test_malformed_selected_item_fails_closed(
    tmp_path: Path,
) -> None:
    """Any malformed selected-calendar item should block exact lookup."""
    config = make_config(tmp_path)
    collection = make_collection(config, "personal")
    write_event(
        collection,
        "target.ics",
        uid="target",
        summary="Target",
    )
    (collection / "broken.ics").write_bytes(b"not iCalendar")

    result = show_khal_calendar_event(
        config,
        "personal",
        "target",
    )

    assert result.success is False
    assert result.event is None
    assert result.issues[0].code == "khal_icalendar_parse_failed"
    assert result.issues[0].operation == "show_event"
    assert result.issues[0].calendar_id == "personal"


def test_symbolic_candidate_item_fails_closed(
    tmp_path: Path,
) -> None:
    """Strict item safety remains active for exact lookup."""
    config = make_config(tmp_path)
    collection = make_collection(config, "personal")
    outside = tmp_path / "outside.ics"
    outside.write_bytes(b"not relevant")
    (collection / "linked.ics").symlink_to(outside)

    result = show_khal_calendar_event(
        config,
        "personal",
        "target",
    )

    assert result.success is False
    assert result.issues[0].code == "khal_icalendar_item_unsafe"
    assert result.issues[0].operation == "show_event"


def test_item_size_limit_is_forwarded(
    tmp_path: Path,
) -> None:
    """Exact lookup should preserve bounded item reading."""
    config = make_config(tmp_path)
    collection = make_collection(config, "personal")
    write_event(
        collection,
        "target.ics",
        uid="target",
        summary="Target",
    )

    result = show_khal_calendar_event(
        config,
        "personal",
        "target",
        maximum_item_bytes=10,
    )

    assert result.success is False
    assert result.issues[0].code == "khal_icalendar_item_too_large"


def test_hidden_and_non_ics_entries_are_ignored(
    tmp_path: Path,
) -> None:
    """Only immediate visible `.ics` candidates should be parsed."""
    config = make_config(tmp_path)
    collection = make_collection(config, "personal")
    write_event(
        collection,
        "target.ics",
        uid="target",
        summary="Target",
    )
    (collection / ".hidden.ics").write_bytes(b"not iCalendar")
    (collection / "displayname").write_text(
        "Personal calendar\n",
        encoding="utf-8",
    )
    (collection / "archive").mkdir()

    result = show_khal_calendar_event(
        config,
        "personal",
        "target",
    )

    assert result.success is True
    assert result.event is not None


def test_programming_inputs_are_validated(
    tmp_path: Path,
) -> None:
    """Caller errors should fail before filesystem work."""
    config = make_config(tmp_path)

    with pytest.raises(TypeError, match="KhalConfig"):
        show_khal_calendar_event(
            object(),  # type: ignore[arg-type]
            "personal",
            "event",
        )

    with pytest.raises(TypeError, match="calendar_id"):
        show_khal_calendar_event(
            config,
            1,  # type: ignore[arg-type]
            "event",
        )

    with pytest.raises(ValueError, match="event_uid"):
        show_khal_calendar_event(
            config,
            "personal",
            " ",
        )

    with pytest.raises(TypeError, match="must be an integer"):
        show_khal_calendar_event(
            config,
            "personal",
            "event",
            maximum_item_bytes=True,
        )

    with pytest.raises(ValueError, match="greater than zero"):
        show_khal_calendar_event(
            config,
            "personal",
            "event",
            maximum_item_bytes=0,
        )


def test_default_item_limit_remains_stable() -> None:
    """The public exact-lookup bound should remain explicit."""
    assert KHAL_MAX_ICALENDAR_ITEM_BYTES == 1_048_576
