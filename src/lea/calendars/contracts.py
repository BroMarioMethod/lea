"""Immutable provider-neutral calendar contracts."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lea.calendars.recurrence import CalendarRecurrence


@dataclass(frozen=True, slots=True)
class CalendarProviderIssue:
    """One structured calendar-provider problem."""

    code: str
    message: str
    provider: str | None = None
    operation: str | None = None
    calendar_id: str | None = None
    event_uid: str | None = None
    field: str | None = None
    return_code: int | None = None

    def __post_init__(self) -> None:
        """Validate calendar-provider issue fields."""
        _validate_non_empty(self.code, field_name="code")
        _validate_non_empty(self.message, field_name="message")

        for field_name, value in (
            ("provider", self.provider),
            ("operation", self.operation),
            ("calendar_id", self.calendar_id),
            ("event_uid", self.event_uid),
            ("field", self.field),
        ):
            if value is not None:
                _validate_non_empty(value, field_name=field_name)


@dataclass(frozen=True, slots=True)
class CalendarCollection:
    """Immutable provider-neutral calendar collection projection."""

    calendar_id: str
    display_name: str
    read_only: bool = False

    def __post_init__(self) -> None:
        """Validate one calendar collection."""
        _validate_identifier(self.calendar_id, field_name="calendar_id")
        _validate_non_empty(self.display_name, field_name="display_name")

        if not isinstance(self.read_only, bool):
            raise TypeError("read_only must be a boolean.")


@dataclass(frozen=True, slots=True)
class CalendarEventTiming:
    """Canonical half-open all-day or timezone-aware timed interval."""

    start: date | datetime
    end: date | datetime
    timezone: str | None = None

    def __post_init__(self) -> None:
        """Validate one canonical event interval."""
        if not isinstance(self.start, date):
            raise TypeError("start must be a date or datetime.")

        if not isinstance(self.end, date):
            raise TypeError("end must be a date or datetime.")

        start_is_datetime = isinstance(self.start, datetime)
        end_is_datetime = isinstance(self.end, datetime)

        if start_is_datetime != end_is_datetime:
            raise ValueError("start and end must use the same temporal type.")

        if start_is_datetime:
            start = self.start
            end = self.end
            assert isinstance(start, datetime)
            assert isinstance(end, datetime)

            _validate_canonical_utc_datetime(start, field_name="start")
            _validate_canonical_utc_datetime(end, field_name="end")

            if self.timezone is None:
                raise ValueError("Timed events must contain an IANA timezone.")

            _validate_timezone(self.timezone)

            if end <= start:
                raise ValueError("end must be later than start.")

            return

        start_date = self.start
        end_date = self.end
        assert not isinstance(start_date, datetime)
        assert not isinstance(end_date, datetime)

        if self.timezone is not None:
            raise ValueError("All-day events must not contain a timezone.")

        if end_date <= start_date:
            raise ValueError("end must be later than start.")

    @property
    def all_day(self) -> bool:
        """Return whether the interval uses all-day dates."""
        return not isinstance(self.start, datetime)


@dataclass(frozen=True, slots=True)
class CalendarEventTarget:
    """Explicit target for a recurring series or one recurrence instance."""

    calendar_id: str
    event_uid: str
    kind: str = "series"
    recurrence_id: date | datetime | None = None

    def __post_init__(self) -> None:
        _validate_identifier(self.calendar_id, field_name="calendar_id")
        _validate_identifier(self.event_uid, field_name="event_uid")
        if self.kind not in {"series", "instance"}:
            raise ValueError("kind must be series or instance.")
        if self.kind == "series" and self.recurrence_id is not None:
            raise ValueError("series targets must not contain recurrence_id.")
        if self.kind == "instance" and self.recurrence_id is None:
            raise ValueError("instance targets require recurrence_id.")
        if self.recurrence_id is not None:
            if type(self.recurrence_id) is date:
                return
            if not isinstance(self.recurrence_id, datetime):
                raise TypeError("recurrence_id must be a date or datetime.")
            _validate_canonical_utc_datetime(
                self.recurrence_id,
                field_name="recurrence_id",
            )


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    """Immutable provider-neutral calendar event projection."""

    calendar_id: str
    event_uid: str
    summary: str
    timing: CalendarEventTiming
    description: str | None = None
    location: str | None = None
    cancelled: bool = False
    recurrence: CalendarRecurrence | None = None

    def __post_init__(self) -> None:
        """Validate one canonical calendar event."""
        _validate_identifier(self.calendar_id, field_name="calendar_id")
        _validate_identifier(self.event_uid, field_name="event_uid")
        _validate_non_empty(self.summary, field_name="summary")

        if not isinstance(self.timing, CalendarEventTiming):
            raise TypeError("timing must be a CalendarEventTiming value.")

        _validate_optional_text(self.description, field_name="description")
        _validate_optional_text(self.location, field_name="location")

        if not isinstance(self.cancelled, bool):
            raise TypeError("cancelled must be a boolean.")

        if self.recurrence is not None and not isinstance(
            self.recurrence, CalendarRecurrence
        ):
            raise TypeError("recurrence must be a CalendarRecurrence or None.")


@dataclass(frozen=True, slots=True)
class CalendarEventQuery:
    """Immutable supported calendar-event listing query."""

    start_date: date
    end_date: date
    calendar_ids: tuple[str, ...] = ()
    include_cancelled: bool = False

    def __post_init__(self) -> None:
        """Validate and normalise supported event-list filters."""
        if not isinstance(self.start_date, date) or isinstance(
            self.start_date,
            datetime,
        ):
            raise TypeError("start_date must be a date, not a datetime.")

        if not isinstance(self.end_date, date) or isinstance(
            self.end_date,
            datetime,
        ):
            raise TypeError("end_date must be a date, not a datetime.")

        if self.end_date <= self.start_date:
            raise ValueError("end_date must be later than start_date.")

        canonical_ids = tuple(sorted(set(self.calendar_ids)))

        for calendar_id in canonical_ids:
            _validate_identifier(calendar_id, field_name="calendar_ids")

        if not isinstance(self.include_cancelled, bool):
            raise TypeError("include_cancelled must be a boolean.")

        object.__setattr__(self, "calendar_ids", canonical_ids)


@dataclass(frozen=True, slots=True)
class CalendarCreateRequest:
    """Immutable request to create one calendar event."""

    calendar_id: str
    summary: str
    timing: CalendarEventTiming
    description: str | None = None
    location: str | None = None
    recurrence: CalendarRecurrence | None = None

    def __post_init__(self) -> None:
        """Validate one event-creation request."""
        _validate_identifier(self.calendar_id, field_name="calendar_id")
        _validate_non_empty(self.summary, field_name="summary")

        if not isinstance(self.timing, CalendarEventTiming):
            raise TypeError("timing must be a CalendarEventTiming value.")

        _validate_optional_text(self.description, field_name="description")
        _validate_optional_text(self.location, field_name="location")

        if self.recurrence is not None and not isinstance(
            self.recurrence, CalendarRecurrence
        ):
            raise TypeError("recurrence must be a CalendarRecurrence or None.")


@dataclass(frozen=True, slots=True)
class CalendarModifyRequest:
    """Immutable request to modify one exact calendar event."""

    calendar_id: str
    event_uid: str
    summary: str | None = None
    timing: CalendarEventTiming | None = None
    description: str | None = None
    clear_description: bool = False
    location: str | None = None
    clear_location: bool = False
    recurrence: CalendarRecurrence | None = None
    clear_recurrence: bool = False
    target: CalendarEventTarget | None = None

    def __post_init__(self) -> None:
        """Validate one exact event modification."""
        _validate_identifier(self.calendar_id, field_name="calendar_id")
        _validate_identifier(self.event_uid, field_name="event_uid")

        if self.summary is not None:
            _validate_non_empty(self.summary, field_name="summary")

        if self.timing is not None and not isinstance(
            self.timing,
            CalendarEventTiming,
        ):
            raise TypeError("timing must be a CalendarEventTiming value.")

        _validate_optional_text(self.description, field_name="description")
        _validate_optional_text(self.location, field_name="location")

        if self.description is not None and self.clear_description:
            raise ValueError(
                "description and clear_description must not be supplied together."
            )

        if self.location is not None and self.clear_location:
            raise ValueError(
                "location and clear_location must not be supplied together."
            )

        if self.recurrence is not None and self.clear_recurrence:
            raise ValueError(
                "recurrence and clear_recurrence must not be supplied together."
            )

        if not isinstance(self.clear_description, bool):
            raise TypeError("clear_description must be a boolean.")

        if not isinstance(self.clear_location, bool):
            raise TypeError("clear_location must be a boolean.")

        if not isinstance(self.clear_recurrence, bool):
            raise TypeError("clear_recurrence must be a boolean.")

        if self.recurrence is not None and not isinstance(
            self.recurrence, CalendarRecurrence
        ):
            raise TypeError("recurrence must be a CalendarRecurrence or None.")

        if self.target is not None:
            if not isinstance(self.target, CalendarEventTarget):
                raise TypeError("target must be a CalendarEventTarget or None.")
            if (self.target.calendar_id, self.target.event_uid) != (
                self.calendar_id,
                self.event_uid,
            ):
                raise ValueError("target identity must match the request identity.")

        if not any(
            (
                self.summary is not None,
                self.timing is not None,
                self.description is not None,
                self.clear_description,
                self.location is not None,
                self.clear_location,
                self.recurrence is not None,
                self.clear_recurrence,
            )
        ):
            raise ValueError(
                "A calendar event modification must contain at least one change."
            )


@dataclass(frozen=True, slots=True)
class CalendarCancelRequest:
    """Immutable request to cancel one exact calendar event."""

    calendar_id: str
    event_uid: str
    target: CalendarEventTarget | None = None

    def __post_init__(self) -> None:
        """Validate one exact cancellation target."""
        _validate_identifier(self.calendar_id, field_name="calendar_id")
        _validate_identifier(self.event_uid, field_name="event_uid")
        if self.target is not None:
            if not isinstance(self.target, CalendarEventTarget):
                raise TypeError("target must be a CalendarEventTarget or None.")
            if (self.target.calendar_id, self.target.event_uid) != (
                self.calendar_id,
                self.event_uid,
            ):
                raise ValueError("target identity must match the request identity.")


@dataclass(frozen=True, slots=True)
class CalendarProviderInspectionResult:
    """Immutable result of inspecting one calendar provider."""

    available: bool
    provider: str
    version: str | None
    issues: tuple[CalendarProviderIssue, ...]

    def __post_init__(self) -> None:
        """Validate inspection-result consistency."""
        _validate_non_empty(self.provider, field_name="provider")

        if self.available:
            if self.version is None:
                raise ValueError("An available provider must contain a version.")

            _validate_non_empty(self.version, field_name="version")

            if self.issues:
                raise ValueError("An available provider must not contain issues.")

            return

        if self.version is not None:
            raise ValueError("An unavailable provider must not contain a version.")

        if not self.issues:
            raise ValueError("An unavailable provider must contain at least one issue.")


@dataclass(frozen=True, slots=True)
class CalendarListCalendarsResult:
    """Immutable result of listing calendar collections."""

    success: bool
    calendars: tuple[CalendarCollection, ...]
    issues: tuple[CalendarProviderIssue, ...]

    def __post_init__(self) -> None:
        """Validate calendar-list result consistency."""
        _validate_collection_result(
            success=self.success,
            values=self.calendars,
            issues=self.issues,
            value_name="calendars",
        )


@dataclass(frozen=True, slots=True)
class CalendarListEventsResult:
    """Immutable result of listing calendar events."""

    success: bool
    events: tuple[CalendarEvent, ...]
    issues: tuple[CalendarProviderIssue, ...]

    def __post_init__(self) -> None:
        """Validate event-list result consistency."""
        _validate_collection_result(
            success=self.success,
            values=self.events,
            issues=self.issues,
            value_name="events",
        )


@dataclass(frozen=True, slots=True)
class CalendarShowEventResult:
    """Immutable result of reading one exact calendar event."""

    success: bool
    event: CalendarEvent | None
    issues: tuple[CalendarProviderIssue, ...]

    def __post_init__(self) -> None:
        """Validate exact-event result consistency."""
        _validate_event_result(
            success=self.success,
            event=self.event,
            issues=self.issues,
            operation="show",
        )


@dataclass(frozen=True, slots=True)
class CalendarMutationResult:
    """Immutable result of one calendar event mutation."""

    success: bool
    event: CalendarEvent | None
    issues: tuple[CalendarProviderIssue, ...]

    def __post_init__(self) -> None:
        """Validate mutation-result consistency."""
        _validate_event_result(
            success=self.success,
            event=self.event,
            issues=self.issues,
            operation="mutation",
        )


def _validate_collection_result(
    *,
    success: bool,
    values: tuple[object, ...],
    issues: tuple[CalendarProviderIssue, ...],
    value_name: str,
) -> None:
    """Validate one result containing zero or more values."""
    if success:
        if issues:
            raise ValueError(
                f"A successful calendar {value_name} result must not contain issues."
            )
        return

    if values:
        raise ValueError(
            f"A failed calendar {value_name} result must not contain values."
        )

    if not issues:
        raise ValueError(
            f"A failed calendar {value_name} result must contain at least one issue."
        )


def _validate_event_result(
    *,
    success: bool,
    event: CalendarEvent | None,
    issues: tuple[CalendarProviderIssue, ...],
    operation: str,
) -> None:
    """Validate one result containing an optional event."""
    if success:
        if event is None:
            raise ValueError(
                f"A successful calendar {operation} must contain an event."
            )

        if issues:
            raise ValueError(
                f"A successful calendar {operation} must not contain issues."
            )

        return

    if event is not None:
        raise ValueError(f"A failed calendar {operation} must not contain an event.")

    if not issues:
        raise ValueError(
            f"A failed calendar {operation} must contain at least one issue."
        )


def _validate_identifier(value: str, *, field_name: str) -> None:
    """Validate one opaque stable provider identifier."""
    _validate_non_empty(value, field_name=field_name)

    if value != value.strip():
        raise ValueError(
            f"{field_name} must not contain leading or trailing whitespace."
        )

    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field_name} must not contain control characters.")


def _validate_non_empty(value: str, *, field_name: str) -> None:
    """Validate one non-empty string."""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")

    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty.")


def _validate_optional_text(value: str | None, *, field_name: str) -> None:
    """Validate optional non-empty text."""
    if value is not None:
        _validate_non_empty(value, field_name=field_name)


def _validate_timezone(value: str) -> None:
    """Validate one canonical IANA timezone identifier."""
    _validate_non_empty(value, field_name="timezone")

    try:
        zone = ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise ValueError("timezone must be a valid IANA timezone.") from error

    if zone.key != value:
        raise ValueError("timezone must use its canonical IANA identifier.")


def _validate_canonical_utc_datetime(
    value: datetime,
    *,
    field_name: str,
) -> None:
    """Validate one timezone-aware canonical UTC instant."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")

    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be a canonical UTC instant.")
