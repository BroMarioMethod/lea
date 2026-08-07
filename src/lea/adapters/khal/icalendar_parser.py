"""Strict bounded parsing of local khal vdir iCalendar items."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lea.adapters.khal.contracts import KhalCalendarItemParseResult
from lea.calendars import (
    CalendarAttendee,
    CalendarEvent,
    CalendarEventTiming,
    CalendarProviderIssue,
    CalendarRecurrence,
    canonical_attendees,
)

_PROVIDER = "khal"
KHAL_MAX_ICALENDAR_ITEM_BYTES = 1_048_576
_RECURRENCE_FIELDS = (
    "RRULE",
    "RDATE",
    "EXDATE",
    "RECURRENCE-ID",
)
_ALLOWED_STATUSES = {
    "CONFIRMED",
    "TENTATIVE",
    "CANCELLED",
}


class _ICalendarProperty(Protocol):
    """Structural subset used from one iCalendar property."""

    params: Mapping[object, object]

    def to_ical(self) -> bytes: ...


class _ICalendarComponent(Protocol):
    """Structural subset used from one iCalendar component."""

    name: str

    def walk(
        self,
        name: str | None = None,
    ) -> list[_ICalendarComponent]: ...

    def get(
        self,
        key: str,
        default: object | None = None,
    ) -> object: ...

    def decoded(
        self,
        key: str,
        default: object | None = None,
    ) -> object: ...


class _ICalendarFactory(Protocol):
    """Structural subset used from the third-party Calendar class."""

    def from_ical(
        self,
        value: str | bytes,
    ) -> _ICalendarComponent: ...


def parse_khal_calendar_item(
    document: bytes,
    *,
    calendar_id: str,
    maximum_bytes: int = KHAL_MAX_ICALENDAR_ITEM_BYTES,
) -> KhalCalendarItemParseResult:
    """Parse one bounded iCalendar vdir item into a canonical event."""
    _validate_calendar_id(calendar_id)
    _validate_maximum_bytes(maximum_bytes)

    if not isinstance(document, bytes):
        raise TypeError("document must be bytes.")

    if len(document) > maximum_bytes:
        return _failure(
            code="khal_icalendar_item_too_large",
            message="The iCalendar item exceeded the configured size limit.",
            calendar_id=calendar_id,
            field="document",
        )

    try:
        text = document.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return _failure(
            code="khal_icalendar_item_invalid_utf8",
            message="The iCalendar item was not valid UTF-8.",
            calendar_id=calendar_id,
            field="document",
        )

    try:
        calendar_factory = cast(
            _ICalendarFactory,
            vars(import_module("icalendar"))["Calendar"],
        )
        calendar = calendar_factory.from_ical(text)
        events = tuple(calendar.walk("VEVENT"))
    except (AttributeError, KeyError, TypeError, ValueError):
        return _failure(
            code="khal_icalendar_parse_failed",
            message="The iCalendar item could not be parsed.",
            calendar_id=calendar_id,
            field="document",
        )

    if len(events) != 1:
        return _failure(
            code="khal_icalendar_event_count_invalid",
            message="A vdir item must contain exactly one VEVENT component.",
            calendar_id=calendar_id,
            field="VEVENT",
        )

    component = events[0]

    recurrence = None
    recurrence_property = component.get("RRULE")
    if recurrence_property is not None:
        try:
            recurrence_value = cast(_ICalendarProperty, recurrence_property).to_ical()
            recurrence = CalendarRecurrence.from_rrule(recurrence_value.decode("ascii"))
        except (AttributeError, UnicodeDecodeError, ValueError):
            return _failure(
                code="khal_icalendar_recurrence_invalid",
                message="The iCalendar RRULE value is unsupported or invalid.",
                calendar_id=calendar_id,
                field="RRULE",
            )

    recurrence_id: date | datetime | None = None
    recurrence_id_property = component.get("RECURRENCE-ID")
    if recurrence_id_property is not None:
        try:
            value = cast(Any, recurrence_id_property).dt
            if isinstance(value, datetime):
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError
                recurrence_id = value.astimezone(UTC)
            elif type(value) is date:
                recurrence_id = value
            else:
                raise ValueError
        except (AttributeError, TypeError, ValueError):
            return _failure(
                code="khal_icalendar_recurrence_id_invalid",
                message="The recurrence instance identifier is invalid.",
                calendar_id=calendar_id,
                field="RECURRENCE-ID",
            )
    for field in ("RDATE", "EXDATE"):
        if component.get(field) is not None:
            return _failure(
                code="khal_icalendar_recurrence_exception_unsupported",
                message="RDATE and EXDATE recurrence material is unsupported.",
                calendar_id=calendar_id,
                field=field,
            )

    uid_result = _decode_required_text(
        component,
        property_name="UID",
        calendar_id=calendar_id,
        event_uid=None,
    )

    if isinstance(uid_result, KhalCalendarItemParseResult):
        return uid_result

    event_uid = uid_result
    summary_result = _decode_required_text(
        component,
        property_name="SUMMARY",
        calendar_id=calendar_id,
        event_uid=event_uid,
    )

    if isinstance(summary_result, KhalCalendarItemParseResult):
        return summary_result

    description_result = _decode_optional_text(
        component,
        property_name="DESCRIPTION",
        calendar_id=calendar_id,
        event_uid=event_uid,
    )

    if isinstance(description_result, KhalCalendarItemParseResult):
        return description_result

    location_result = _decode_optional_text(
        component,
        property_name="LOCATION",
        calendar_id=calendar_id,
        event_uid=event_uid,
    )

    if isinstance(location_result, KhalCalendarItemParseResult):
        return location_result

    attendees_result = _decode_attendees(
        component,
        calendar_id=calendar_id,
        event_uid=event_uid,
    )
    if isinstance(attendees_result, KhalCalendarItemParseResult):
        return attendees_result

    status_result = _decode_optional_text(
        component,
        property_name="STATUS",
        calendar_id=calendar_id,
        event_uid=event_uid,
    )

    if isinstance(status_result, KhalCalendarItemParseResult):
        return status_result

    if status_result is not None:
        status = status_result.upper()

        if status not in _ALLOWED_STATUSES:
            return _failure(
                code="khal_icalendar_field_invalid",
                message="The iCalendar STATUS value is not supported.",
                calendar_id=calendar_id,
                event_uid=event_uid,
                field="STATUS",
            )
    else:
        status = None

    timing_result = _parse_timing(
        component,
        calendar_id=calendar_id,
        event_uid=event_uid,
    )

    if isinstance(timing_result, KhalCalendarItemParseResult):
        return timing_result

    try:
        event = CalendarEvent(
            calendar_id=calendar_id,
            event_uid=event_uid,
            summary=summary_result,
            timing=timing_result,
            description=description_result,
            location=location_result,
            cancelled=status == "CANCELLED",
            recurrence=recurrence,
            recurrence_id=recurrence_id,
            attendees=attendees_result,
        )
    except (TypeError, ValueError):
        return _failure(
            code="khal_icalendar_field_invalid",
            message="The iCalendar event failed canonical field validation.",
            calendar_id=calendar_id,
            event_uid=event_uid,
            field="VEVENT",
        )

    return KhalCalendarItemParseResult(
        success=True,
        event=event,
        issues=(),
    )


def _decode_attendees(
    component: _ICalendarComponent,
    *,
    calendar_id: str,
    event_uid: str,
) -> tuple[CalendarAttendee, ...] | KhalCalendarItemParseResult:
    """Decode supported ATTENDEE properties into canonical participants."""
    attendees: list[CalendarAttendee] = []
    try:
        value = component.get("ATTENDEE")
        if value is None:
            properties: tuple[object, ...] = ()
        elif isinstance(value, (list, tuple)):
            properties = tuple(value)
        else:
            properties = (value,)
    except (AttributeError, TypeError):
        return _failure(
            code="khal_icalendar_attendee_invalid",
            message="The iCalendar attendee properties could not be read.",
            calendar_id=calendar_id,
            event_uid=event_uid,
            field="ATTENDEE",
        )
    for property_value in properties:
        try:
            property_item = cast(_ICalendarProperty, property_value)
            address = property_item.to_ical().decode("utf-8")
            params = property_item.params

            attendees.append(
                CalendarAttendee.from_ical(
                    address,
                    display_name=(
                        str(params["CN"]) if params.get("CN") is not None else None
                    ),
                    role=(
                        str(params["ROLE"]) if params.get("ROLE") is not None else None
                    ),
                    response=(
                        str(params["PARTSTAT"])
                        if params.get("PARTSTAT") is not None
                        else None
                    ),
                    rsvp=(
                        str(params["RSVP"]) if params.get("RSVP") is not None else None
                    ),
                )
            )
        except (AttributeError, UnicodeDecodeError, TypeError, ValueError):
            return _failure(
                code="khal_icalendar_attendee_invalid",
                message="The iCalendar attendee property is invalid.",
                calendar_id=calendar_id,
                event_uid=event_uid,
                field="ATTENDEE",
            )
    try:
        return canonical_attendees(attendees)
    except (TypeError, ValueError):
        return _failure(
            code="khal_icalendar_attendee_duplicate",
            message="The iCalendar event contains duplicate attendees.",
            calendar_id=calendar_id,
            event_uid=event_uid,
            field="ATTENDEE",
        )


def read_khal_calendar_item(
    path: Path,
    *,
    calendar_id: str,
    maximum_bytes: int = KHAL_MAX_ICALENDAR_ITEM_BYTES,
) -> KhalCalendarItemParseResult:
    """Read and parse one exact regular non-symbolic `.ics` vdir item."""
    _validate_absolute_path(path, field_name="path")
    _validate_calendar_id(calendar_id)
    _validate_maximum_bytes(maximum_bytes)

    try:
        if path.is_symlink():
            return _failure(
                code="khal_icalendar_item_unsafe",
                message="The iCalendar item must not be a symbolic link.",
                calendar_id=calendar_id,
                field="path",
            )

        if not path.exists():
            return _failure(
                code="khal_icalendar_item_missing",
                message="The iCalendar item does not exist.",
                calendar_id=calendar_id,
                field="path",
            )

        if not path.is_file():
            return _failure(
                code="khal_icalendar_item_unsafe",
                message="The iCalendar item is not a regular file.",
                calendar_id=calendar_id,
                field="path",
            )

        if path.suffix.lower() != ".ics":
            return _failure(
                code="khal_icalendar_item_unsafe",
                message="The calendar vdir item must use the .ics suffix.",
                calendar_id=calendar_id,
                field="path",
            )

        if path.stat().st_size > maximum_bytes:
            return _failure(
                code="khal_icalendar_item_too_large",
                message="The iCalendar item exceeded the configured size limit.",
                calendar_id=calendar_id,
                field="path",
            )

        document = path.read_bytes()
    except OSError:
        return _failure(
            code="khal_icalendar_item_unreadable",
            message="The iCalendar item could not be read.",
            calendar_id=calendar_id,
            field="path",
        )

    return parse_khal_calendar_item(
        document,
        calendar_id=calendar_id,
        maximum_bytes=maximum_bytes,
    )


def _parse_timing(
    component: _ICalendarComponent,
    *,
    calendar_id: str,
    event_uid: str,
) -> CalendarEventTiming | KhalCalendarItemParseResult:
    """Parse one exact half-open DTSTART/DTEND interval."""
    start_result = _decode_temporal_property(
        component,
        property_name="DTSTART",
        calendar_id=calendar_id,
        event_uid=event_uid,
    )

    if isinstance(start_result, KhalCalendarItemParseResult):
        return start_result

    end_result = _decode_temporal_property(
        component,
        property_name="DTEND",
        calendar_id=calendar_id,
        event_uid=event_uid,
    )

    if isinstance(end_result, KhalCalendarItemParseResult):
        return end_result

    start, start_params = start_result
    end, end_params = end_result
    start_is_datetime = isinstance(start, datetime)
    end_is_datetime = isinstance(end, datetime)

    if start_is_datetime != end_is_datetime:
        return _failure(
            code="khal_icalendar_field_invalid",
            message="DTSTART and DTEND must use the same temporal type.",
            calendar_id=calendar_id,
            event_uid=event_uid,
            field="DTEND",
        )

    if not start_is_datetime:
        assert isinstance(start, date)
        assert isinstance(end, date)

        if "TZID" in start_params or "TZID" in end_params:
            return _failure(
                code="khal_icalendar_timezone_invalid",
                message="All-day event dates must not contain a TZID.",
                calendar_id=calendar_id,
                event_uid=event_uid,
                field="TZID",
            )

        try:
            return CalendarEventTiming(
                start=start,
                end=end,
                timezone=None,
            )
        except (TypeError, ValueError):
            return _failure(
                code="khal_icalendar_field_invalid",
                message="The all-day event interval is invalid.",
                calendar_id=calendar_id,
                event_uid=event_uid,
                field="DTEND",
            )

    assert isinstance(start, datetime)
    assert isinstance(end, datetime)

    if (
        start.tzinfo is None
        or start.utcoffset() is None
        or end.tzinfo is None
        or end.utcoffset() is None
    ):
        return _failure(
            code="khal_icalendar_floating_time_unsupported",
            message="Floating event times are not supported.",
            calendar_id=calendar_id,
            event_uid=event_uid,
            field="DTSTART",
        )

    start_tzid = start_params.get("TZID")
    end_tzid = end_params.get("TZID")

    if start_tzid is None and end_tzid is None:
        if start.utcoffset() != timedelta(0) or end.utcoffset() != timedelta(0):
            return _failure(
                code="khal_icalendar_timezone_invalid",
                message=("Timed events without TZID must use canonical UTC instants."),
                calendar_id=calendar_id,
                event_uid=event_uid,
                field="TZID",
            )

        timezone_name = "UTC"
    else:
        if start_tzid is None or end_tzid is None or start_tzid != end_tzid:
            return _failure(
                code="khal_icalendar_timezone_invalid",
                message="DTSTART and DTEND must use the same explicit TZID.",
                calendar_id=calendar_id,
                event_uid=event_uid,
                field="TZID",
            )

        timezone_name = start_tzid

        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            return _failure(
                code="khal_icalendar_timezone_invalid",
                message="The event TZID is not a valid IANA timezone.",
                calendar_id=calendar_id,
                event_uid=event_uid,
                field="TZID",
            )

        if zone.key != timezone_name:
            return _failure(
                code="khal_icalendar_timezone_invalid",
                message="The event TZID is not canonical.",
                calendar_id=calendar_id,
                event_uid=event_uid,
                field="TZID",
            )

    try:
        return CalendarEventTiming(
            start=start.astimezone(UTC),
            end=end.astimezone(UTC),
            timezone=timezone_name,
        )
    except (TypeError, ValueError):
        return _failure(
            code="khal_icalendar_field_invalid",
            message="The timed event interval is invalid.",
            calendar_id=calendar_id,
            event_uid=event_uid,
            field="DTEND",
        )


def _decode_temporal_property(
    component: _ICalendarComponent,
    *,
    property_name: str,
    calendar_id: str,
    event_uid: str,
) -> tuple[date | datetime, dict[str, str]] | KhalCalendarItemParseResult:
    """Decode one required singular date or datetime property."""
    raw = component.get(property_name)

    if raw is None:
        return _failure(
            code="khal_icalendar_field_invalid",
            message=f"The iCalendar event is missing {property_name}.",
            calendar_id=calendar_id,
            event_uid=event_uid,
            field=property_name,
        )

    if isinstance(raw, (list, tuple)):
        return _failure(
            code="khal_icalendar_field_invalid",
            message=f"The iCalendar event contains ambiguous {property_name}.",
            calendar_id=calendar_id,
            event_uid=event_uid,
            field=property_name,
        )

    try:
        decoded = component.decoded(property_name)
    except (KeyError, TypeError, ValueError):
        return _failure(
            code="khal_icalendar_field_invalid",
            message=f"The iCalendar {property_name} value could not be decoded.",
            calendar_id=calendar_id,
            event_uid=event_uid,
            field=property_name,
        )

    if not isinstance(decoded, date):
        return _failure(
            code="khal_icalendar_field_invalid",
            message=f"The iCalendar {property_name} value is not temporal.",
            calendar_id=calendar_id,
            event_uid=event_uid,
            field=property_name,
        )

    params_object = getattr(raw, "params", None)

    if params_object is None:
        params: dict[str, str] = {}
    elif isinstance(params_object, Mapping):
        params = {str(key).upper(): str(value) for key, value in params_object.items()}
    else:
        return _failure(
            code="khal_icalendar_field_invalid",
            message=f"The iCalendar {property_name} parameters are invalid.",
            calendar_id=calendar_id,
            event_uid=event_uid,
            field=property_name,
        )

    return decoded, params


def _decode_required_text(
    component: _ICalendarComponent,
    *,
    property_name: str,
    calendar_id: str,
    event_uid: str | None,
) -> str | KhalCalendarItemParseResult:
    """Decode one required singular UTF-8 text property."""
    result = _decode_text(
        component,
        property_name=property_name,
        calendar_id=calendar_id,
        event_uid=event_uid,
        required=True,
    )
    assert result is not None
    return result


def _decode_optional_text(
    component: _ICalendarComponent,
    *,
    property_name: str,
    calendar_id: str,
    event_uid: str,
) -> str | None | KhalCalendarItemParseResult:
    """Decode one optional singular UTF-8 text property."""
    return _decode_text(
        component,
        property_name=property_name,
        calendar_id=calendar_id,
        event_uid=event_uid,
        required=False,
    )


def _decode_text(
    component: _ICalendarComponent,
    *,
    property_name: str,
    calendar_id: str,
    event_uid: str | None,
    required: bool,
) -> str | None | KhalCalendarItemParseResult:
    """Decode one singular text property without silent coercion."""
    raw = component.get(property_name)

    if raw is None:
        if required:
            return _failure(
                code="khal_icalendar_field_invalid",
                message=f"The iCalendar event is missing {property_name}.",
                calendar_id=calendar_id,
                event_uid=event_uid,
                field=property_name,
            )

        return None

    if isinstance(raw, (list, tuple)):
        return _failure(
            code="khal_icalendar_field_invalid",
            message=f"The iCalendar event contains ambiguous {property_name}.",
            calendar_id=calendar_id,
            event_uid=event_uid,
            field=property_name,
        )

    try:
        decoded = component.decoded(property_name)
    except (KeyError, TypeError, ValueError):
        return _failure(
            code="khal_icalendar_field_invalid",
            message=f"The iCalendar {property_name} value could not be decoded.",
            calendar_id=calendar_id,
            event_uid=event_uid,
            field=property_name,
        )

    if isinstance(decoded, bytes):
        try:
            value = decoded.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return _failure(
                code="khal_icalendar_field_invalid",
                message=f"The iCalendar {property_name} value was not UTF-8.",
                calendar_id=calendar_id,
                event_uid=event_uid,
                field=property_name,
            )
    elif isinstance(decoded, str):
        value = decoded
    else:
        return _failure(
            code="khal_icalendar_field_invalid",
            message=f"The iCalendar {property_name} value is not text.",
            calendar_id=calendar_id,
            event_uid=event_uid,
            field=property_name,
        )

    if not value.strip():
        return _failure(
            code="khal_icalendar_field_invalid",
            message=f"The iCalendar {property_name} value must be non-empty.",
            calendar_id=calendar_id,
            event_uid=event_uid,
            field=property_name,
        )

    return value


def _failure(
    *,
    code: str,
    message: str,
    calendar_id: str,
    event_uid: str | None = None,
    field: str | None = None,
) -> KhalCalendarItemParseResult:
    """Construct one deterministic failed item parse."""
    return KhalCalendarItemParseResult(
        success=False,
        event=None,
        issues=(
            CalendarProviderIssue(
                code=code,
                message=message,
                provider=_PROVIDER,
                operation="parse_item",
                calendar_id=calendar_id,
                event_uid=event_uid,
                field=field,
            ),
        ),
    )


def _validate_calendar_id(value: str) -> None:
    """Validate one exact provider calendar identifier."""
    if not isinstance(value, str):
        raise TypeError("calendar_id must be a string.")

    if not value.strip():
        raise ValueError("calendar_id must be non-empty.")

    if value != value.strip():
        raise ValueError("calendar_id must not contain leading or trailing whitespace.")

    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("calendar_id must not contain control characters.")


def _validate_maximum_bytes(value: int) -> None:
    """Validate one positive bounded-item size."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("maximum_bytes must be an integer.")

    if value <= 0:
        raise ValueError("maximum_bytes must be greater than zero.")


def _validate_absolute_path(
    path: Path,
    *,
    field_name: str,
) -> None:
    """Validate one absolute pathlib path."""
    if not isinstance(path, Path):
        raise TypeError(f"{field_name} must be a pathlib.Path value.")

    if not path.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path.")

    if "\x00" in str(path):
        raise ValueError(f"{field_name} must not contain a null byte.")
