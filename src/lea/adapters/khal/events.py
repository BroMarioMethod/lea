"""Deterministic read-only listing of local khal vdir events."""

from datetime import UTC, date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from lea.adapters.khal.contracts import KhalConfig
from lea.adapters.khal.icalendar_parser import (
    KHAL_MAX_ICALENDAR_ITEM_BYTES,
    read_khal_calendar_item,
)
from lea.adapters.khal.vdirs import discover_khal_calendar_collections
from lea.calendars import (
    CalendarEvent,
    CalendarEventQuery,
    CalendarListEventsResult,
    CalendarProviderIssue,
    CalendarShowEventResult,
)

_PROVIDER = "khal"
_OPERATION = "list_events"


def list_khal_calendar_events(
    config: KhalConfig,
    query: CalendarEventQuery,
    *,
    maximum_item_bytes: int = KHAL_MAX_ICALENDAR_ITEM_BYTES,
) -> CalendarListEventsResult:
    """List canonical events from selected trusted local vdir collections."""
    if not isinstance(config, KhalConfig):
        raise TypeError("config must be a KhalConfig value.")

    if not isinstance(query, CalendarEventQuery):
        raise TypeError("query must be a CalendarEventQuery value.")

    _validate_maximum_item_bytes(maximum_item_bytes)

    collections_result = discover_khal_calendar_collections(config)

    if not collections_result.success:
        return CalendarListEventsResult(
            success=False,
            events=(),
            issues=_with_list_operation(collections_result.issues),
        )

    available_ids = tuple(
        collection.calendar_id for collection in collections_result.calendars
    )
    selected_result = _select_calendar_ids(
        available_ids=available_ids,
        requested_ids=query.calendar_ids,
    )

    if isinstance(selected_result, CalendarProviderIssue):
        return _failure(selected_result)

    display_zone = ZoneInfo(config.display_timezone)
    query_start_utc, query_end_utc = _query_utc_bounds(
        query=query,
        display_zone=display_zone,
    )
    events: list[CalendarEvent] = []
    seen_identities: set[tuple[str, str]] = set()

    for calendar_id in selected_result:
        collection = config.vdirs_directory / calendar_id
        item_result = _calendar_item_paths(
            collection,
            calendar_id=calendar_id,
        )

        if isinstance(item_result, CalendarProviderIssue):
            return _failure(item_result)

        for item in item_result:
            parsed = read_khal_calendar_item(
                item,
                calendar_id=calendar_id,
                maximum_bytes=maximum_item_bytes,
            )

            if not parsed.success:
                return CalendarListEventsResult(
                    success=False,
                    events=(),
                    issues=_with_list_operation(parsed.issues),
                )

            event = parsed.event

            if event is None:
                return _failure(
                    _issue(
                        code="khal_calendar_item_parse_incomplete",
                        message=(
                            "A successful calendar-item parse did not contain an event."
                        ),
                        calendar_id=calendar_id,
                        field="event",
                    )
                )

            identity = (event.calendar_id, event.event_uid)

            if identity in seen_identities:
                return _failure(
                    _issue(
                        code="khal_calendar_event_identity_duplicate",
                        message=(
                            "The local vdir collection contained a "
                            "duplicate calendar and event identity."
                        ),
                        calendar_id=event.calendar_id,
                        event_uid=event.event_uid,
                        field="event_uid",
                    )
                )

            seen_identities.add(identity)

            if event.cancelled and not query.include_cancelled:
                continue

            if not _event_overlaps_query(
                event,
                query=query,
                query_start_utc=query_start_utc,
                query_end_utc=query_end_utc,
            ):
                continue

            events.append(event)

    events.sort(
        key=lambda event: _event_sort_key(
            event,
            display_zone=display_zone,
        )
    )

    return CalendarListEventsResult(
        success=True,
        events=tuple(events),
        issues=(),
    )


def show_khal_calendar_event(
    config: KhalConfig,
    calendar_id: str,
    event_uid: str,
    *,
    maximum_item_bytes: int = KHAL_MAX_ICALENDAR_ITEM_BYTES,
) -> CalendarShowEventResult:
    """Read one exact event by stable calendar and event identity."""
    if not isinstance(config, KhalConfig):
        raise TypeError("config must be a KhalConfig value.")

    _validate_identifier(calendar_id, field_name="calendar_id")
    _validate_identifier(event_uid, field_name="event_uid")
    _validate_maximum_item_bytes(maximum_item_bytes)

    collections_result = discover_khal_calendar_collections(config)

    if not collections_result.success:
        return CalendarShowEventResult(
            success=False,
            event=None,
            issues=_with_show_operation(collections_result.issues),
        )

    available_ids = {
        collection.calendar_id for collection in collections_result.calendars
    }

    if calendar_id not in available_ids:
        return _show_failure(
            _show_issue(
                code="khal_calendar_not_found",
                message=(
                    "The requested calendar was not present below the "
                    "configured vdirs root."
                ),
                calendar_id=calendar_id,
                field="calendar_id",
            )
        )

    item_result = _calendar_item_paths(
        config.vdirs_directory / calendar_id,
        calendar_id=calendar_id,
    )

    if isinstance(item_result, CalendarProviderIssue):
        return CalendarShowEventResult(
            success=False,
            event=None,
            issues=_with_show_operation((item_result,)),
        )

    matches: list[CalendarEvent] = []

    for item in item_result:
        parsed = read_khal_calendar_item(
            item,
            calendar_id=calendar_id,
            maximum_bytes=maximum_item_bytes,
        )

        if not parsed.success:
            return CalendarShowEventResult(
                success=False,
                event=None,
                issues=_with_show_operation(parsed.issues),
            )

        event = parsed.event

        if event is None:
            return _show_failure(
                _show_issue(
                    code="khal_calendar_item_parse_incomplete",
                    message=(
                        "A successful calendar-item parse did not contain an event."
                    ),
                    calendar_id=calendar_id,
                    field="event",
                )
            )

        if event.event_uid == event_uid:
            matches.append(event)

    if not matches:
        return _show_failure(
            _show_issue(
                code="khal_calendar_event_not_found",
                message=(
                    "No event matched the requested stable calendar and event identity."
                ),
                calendar_id=calendar_id,
                event_uid=event_uid,
                field="event_uid",
            )
        )

    if len(matches) != 1:
        return _show_failure(
            _show_issue(
                code="khal_calendar_event_identity_duplicate",
                message=(
                    "Multiple local vdir items claimed the requested "
                    "calendar and event identity."
                ),
                calendar_id=calendar_id,
                event_uid=event_uid,
                field="event_uid",
            )
        )

    return CalendarShowEventResult(
        success=True,
        event=matches[0],
        issues=(),
    )


def _select_calendar_ids(
    *,
    available_ids: tuple[str, ...],
    requested_ids: tuple[str, ...],
) -> tuple[str, ...] | CalendarProviderIssue:
    """Resolve an explicit deterministic calendar selection."""
    if not requested_ids:
        return available_ids

    available = set(available_ids)
    unknown = tuple(
        calendar_id for calendar_id in requested_ids if calendar_id not in available
    )

    if unknown:
        return _issue(
            code="khal_calendar_not_found",
            message=(
                "The event query referenced a calendar that was not "
                "present below the configured vdirs root."
            ),
            calendar_id=unknown[0],
            field="calendar_ids",
        )

    return requested_ids


def _calendar_item_paths(
    collection: Path,
    *,
    calendar_id: str,
) -> tuple[Path, ...] | CalendarProviderIssue:
    """Enumerate immediate visible `.ics` item paths in one collection."""
    try:
        if collection.is_symlink():
            return _issue(
                code="khal_calendar_collection_unsafe",
                message=(
                    "The selected local calendar collection must not be "
                    "a symbolic link."
                ),
                calendar_id=calendar_id,
                field="vdirs_directory",
            )

        if not collection.exists():
            return _issue(
                code="khal_calendar_collection_missing",
                message=("The selected local calendar collection no longer exists."),
                calendar_id=calendar_id,
                field="vdirs_directory",
            )

        if not collection.is_dir():
            return _issue(
                code="khal_calendar_collection_unsafe",
                message=("The selected local calendar collection is not a directory."),
                calendar_id=calendar_id,
                field="vdirs_directory",
            )

        return tuple(
            sorted(
                (
                    entry
                    for entry in collection.iterdir()
                    if not entry.name.startswith(".") and entry.suffix.lower() == ".ics"
                ),
                key=lambda entry: entry.name,
            )
        )
    except OSError:
        return _issue(
            code="khal_calendar_collection_unreadable",
            message=("The selected local calendar collection could not be enumerated."),
            calendar_id=calendar_id,
            field="vdirs_directory",
        )


def _query_utc_bounds(
    *,
    query: CalendarEventQuery,
    display_zone: ZoneInfo,
) -> tuple[datetime, datetime]:
    """Convert the half-open display-date query to canonical UTC bounds."""
    start = datetime.combine(
        query.start_date,
        time.min,
        tzinfo=display_zone,
    )
    end = datetime.combine(
        query.end_date,
        time.min,
        tzinfo=display_zone,
    )
    return start.astimezone(UTC), end.astimezone(UTC)


def _event_overlaps_query(
    event: CalendarEvent,
    *,
    query: CalendarEventQuery,
    query_start_utc: datetime,
    query_end_utc: datetime,
) -> bool:
    """Apply exact half-open date or instant interval overlap."""
    start = event.timing.start
    end = event.timing.end

    if not isinstance(start, datetime):
        assert isinstance(start, date)
        assert isinstance(end, date)
        assert not isinstance(end, datetime)
        return start < query.end_date and end > query.start_date

    assert isinstance(end, datetime)
    return start < query_end_utc and end > query_start_utc


def _event_sort_key(
    event: CalendarEvent,
    *,
    display_zone: ZoneInfo,
) -> tuple[datetime, int, datetime, str, str]:
    """Return the deterministic display-local event ordering key."""
    start = event.timing.start
    end = event.timing.end

    if not isinstance(start, datetime):
        assert isinstance(start, date)
        assert isinstance(end, date)
        assert not isinstance(end, datetime)
        local_start = datetime.combine(start, time.min)
        local_end = datetime.combine(end, time.min)
        all_day_rank = 0
    else:
        assert isinstance(end, datetime)
        local_start = start.astimezone(display_zone).replace(tzinfo=None)
        local_end = end.astimezone(display_zone).replace(tzinfo=None)
        all_day_rank = 1

    return (
        local_start,
        all_day_rank,
        local_end,
        event.calendar_id,
        event.event_uid,
    )


def _with_list_operation(
    issues: tuple[CalendarProviderIssue, ...],
) -> tuple[CalendarProviderIssue, ...]:
    """Preserve structured diagnostics under the public list operation."""
    return tuple(
        CalendarProviderIssue(
            code=issue.code,
            message=issue.message,
            provider=issue.provider or _PROVIDER,
            operation=_OPERATION,
            calendar_id=issue.calendar_id,
            event_uid=issue.event_uid,
            field=issue.field,
            return_code=issue.return_code,
        )
        for issue in issues
    )


def _with_show_operation(
    issues: tuple[CalendarProviderIssue, ...],
) -> tuple[CalendarProviderIssue, ...]:
    """Preserve structured diagnostics under the public show operation."""
    return tuple(
        CalendarProviderIssue(
            code=issue.code,
            message=issue.message,
            provider=issue.provider or _PROVIDER,
            operation="show_event",
            calendar_id=issue.calendar_id,
            event_uid=issue.event_uid,
            field=issue.field,
            return_code=issue.return_code,
        )
        for issue in issues
    )


def _validate_identifier(
    value: str,
    *,
    field_name: str,
) -> None:
    """Validate one exact provider identity value."""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")

    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty.")

    if value != value.strip():
        raise ValueError(
            f"{field_name} must not contain leading or trailing whitespace."
        )

    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field_name} must not contain control characters.")


def _show_failure(
    issue: CalendarProviderIssue,
) -> CalendarShowEventResult:
    """Construct one failed exact-event lookup result."""
    return CalendarShowEventResult(
        success=False,
        event=None,
        issues=(issue,),
    )


def _show_issue(
    *,
    code: str,
    message: str,
    field: str,
    calendar_id: str | None = None,
    event_uid: str | None = None,
) -> CalendarProviderIssue:
    """Construct one structured khal exact-event issue."""
    return CalendarProviderIssue(
        code=code,
        message=message,
        provider=_PROVIDER,
        operation="show_event",
        calendar_id=calendar_id,
        event_uid=event_uid,
        field=field,
    )


def _validate_maximum_item_bytes(value: int) -> None:
    """Validate one positive non-boolean item size limit."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("maximum_item_bytes must be an integer.")

    if value <= 0:
        raise ValueError("maximum_item_bytes must be greater than zero.")


def _failure(
    issue: CalendarProviderIssue,
) -> CalendarListEventsResult:
    """Construct one fail-closed event-list result."""
    return CalendarListEventsResult(
        success=False,
        events=(),
        issues=(issue,),
    )


def _issue(
    *,
    code: str,
    message: str,
    field: str,
    calendar_id: str | None = None,
    event_uid: str | None = None,
) -> CalendarProviderIssue:
    """Construct one structured khal event-listing issue."""
    return CalendarProviderIssue(
        code=code,
        message=message,
        provider=_PROVIDER,
        operation=_OPERATION,
        calendar_id=calendar_id,
        event_uid=event_uid,
        field=field,
    )
