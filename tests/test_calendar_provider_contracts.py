"""Tests for provider-neutral calendar contracts."""

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from lea.calendars import (
    CalendarCancelRequest,
    CalendarCollection,
    CalendarCreateRequest,
    CalendarEvent,
    CalendarEventQuery,
    CalendarEventTiming,
    CalendarListCalendarsResult,
    CalendarListEventsResult,
    CalendarModifyRequest,
    CalendarMutationResult,
    CalendarProvider,
    CalendarProviderInspectionResult,
    CalendarProviderIssue,
    CalendarShowEventResult,
)

CALENDAR_ID = "personal"
EVENT_UID = "20260731T170000Z-1234@example.test"


def timed_timing() -> CalendarEventTiming:
    """Return one valid canonical timed interval."""
    return CalendarEventTiming(
        start=datetime(2026, 7, 31, 17, 0, tzinfo=UTC),
        end=datetime(2026, 7, 31, 18, 0, tzinfo=UTC),
        timezone="Africa/Gaborone",
    )


def all_day_timing() -> CalendarEventTiming:
    """Return one valid all-day interval with exclusive end date."""
    return CalendarEventTiming(
        start=date(2026, 8, 1),
        end=date(2026, 8, 2),
    )


def event() -> CalendarEvent:
    """Return one valid provider event."""
    return CalendarEvent(
        calendar_id=CALENDAR_ID,
        event_uid=EVENT_UID,
        summary="Maintenance planning",
        timing=timed_timing(),
    )


def issue() -> CalendarProviderIssue:
    """Return one valid structured provider issue."""
    return CalendarProviderIssue(
        code="calendar_provider_unavailable",
        message="The calendar provider is unavailable.",
        provider="khal",
    )


def test_event_is_immutable() -> None:
    """Calendar events should be frozen provider projections."""
    value = event()

    with pytest.raises(FrozenInstanceError):
        value.summary = "Changed"  # type: ignore[misc]


def test_event_identity_accepts_opaque_ical_uid() -> None:
    """Event UIDs should not be restricted to UUID syntax."""
    assert event().event_uid == EVENT_UID


def test_event_identity_rejects_outer_whitespace() -> None:
    """Stable identifiers must not be silently trimmed."""
    with pytest.raises(ValueError, match="leading or trailing"):
        CalendarCancelRequest(
            calendar_id=" personal",
            event_uid=EVENT_UID,
        )


def test_timed_event_requires_aware_utc_instants() -> None:
    """Floating and non-canonical timed instants must be rejected."""
    with pytest.raises(ValueError, match="timezone-aware"):
        CalendarEventTiming(
            start=datetime(2026, 7, 31, 17, 0),
            end=datetime(2026, 7, 31, 18, 0),
            timezone="Africa/Gaborone",
        )

    with pytest.raises(ValueError, match="canonical UTC"):
        CalendarEventTiming(
            start=datetime(
                2026,
                7,
                31,
                19,
                0,
                tzinfo=timezone_plus_two(),
            ),
            end=datetime(
                2026,
                7,
                31,
                20,
                0,
                tzinfo=timezone_plus_two(),
            ),
            timezone="Africa/Gaborone",
        )


def test_timed_event_requires_valid_iana_timezone() -> None:
    """Timed intervals must retain one valid source timezone."""
    with pytest.raises(ValueError, match="valid IANA"):
        CalendarEventTiming(
            start=datetime(2026, 7, 31, 17, 0, tzinfo=UTC),
            end=datetime(2026, 7, 31, 18, 0, tzinfo=UTC),
            timezone="Not/AZone",
        )


def test_all_day_event_rejects_timezone() -> None:
    """All-day dates must remain distinct from local timed events."""
    with pytest.raises(ValueError, match="must not contain a timezone"):
        CalendarEventTiming(
            start=date(2026, 8, 1),
            end=date(2026, 8, 2),
            timezone="Africa/Gaborone",
        )


def test_event_timing_rejects_mixed_types() -> None:
    """One interval cannot mix an all-day date and a timed instant."""
    with pytest.raises(ValueError, match="same temporal type"):
        CalendarEventTiming(
            start=date(2026, 8, 1),
            end=datetime(2026, 8, 2, tzinfo=UTC),
        )


def test_event_timing_requires_positive_interval() -> None:
    """Event end boundaries must follow their starts."""
    with pytest.raises(ValueError, match="later than start"):
        CalendarEventTiming(
            start=date(2026, 8, 2),
            end=date(2026, 8, 2),
        )


def test_event_timing_exposes_all_day_classification() -> None:
    """Timing classification should derive from the temporal values."""
    assert all_day_timing().all_day is True
    assert timed_timing().all_day is False


def test_query_normalises_calendar_ids() -> None:
    """Calendar filters should be deterministic and deduplicated."""
    query = CalendarEventQuery(
        start_date=date(2026, 7, 31),
        end_date=date(2026, 8, 2),
        calendar_ids=("work", "personal", "work"),
    )

    assert query.calendar_ids == ("personal", "work")


def test_query_uses_exclusive_positive_date_window() -> None:
    """Event-list windows must have a positive date range."""
    with pytest.raises(ValueError, match="later than start_date"):
        CalendarEventQuery(
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1),
        )


def test_modify_request_requires_a_change() -> None:
    """Empty modifications must fail before provider invocation."""
    with pytest.raises(ValueError, match="at least one change"):
        CalendarModifyRequest(
            calendar_id=CALENDAR_ID,
            event_uid=EVENT_UID,
        )


def test_modify_request_rejects_conflicting_clear_operations() -> None:
    """Replacement text and clear flags must not be combined."""
    with pytest.raises(ValueError, match="clear_description"):
        CalendarModifyRequest(
            calendar_id=CALENDAR_ID,
            event_uid=EVENT_UID,
            description="Updated notes",
            clear_description=True,
        )

    with pytest.raises(ValueError, match="clear_location"):
        CalendarModifyRequest(
            calendar_id=CALENDAR_ID,
            event_uid=EVENT_UID,
            location="Control room",
            clear_location=True,
        )


def test_create_request_requires_stable_calendar_identity() -> None:
    """Creation targets must use a stable calendar ID, not display text."""
    request = CalendarCreateRequest(
        calendar_id=CALENDAR_ID,
        summary="Maintenance planning",
        timing=timed_timing(),
    )

    assert request.calendar_id == CALENDAR_ID


def test_successful_results_require_expected_values() -> None:
    """Successful provider results must contain canonical values."""
    with pytest.raises(ValueError):
        CalendarShowEventResult(success=True, event=None, issues=())

    with pytest.raises(ValueError):
        CalendarMutationResult(success=True, event=None, issues=())

    with pytest.raises(ValueError):
        CalendarListEventsResult(
            success=True,
            events=(),
            issues=(issue(),),
        )


def test_failed_results_require_issues() -> None:
    """Failed provider results must expose structured issues."""
    with pytest.raises(ValueError):
        CalendarShowEventResult(success=False, event=None, issues=())

    with pytest.raises(ValueError):
        CalendarListCalendarsResult(
            success=False,
            calendars=(),
            issues=(),
        )


def test_empty_successful_lists_are_valid() -> None:
    """A successful query may correctly return no values."""
    assert CalendarListCalendarsResult(
        success=True,
        calendars=(),
        issues=(),
    ).success
    assert CalendarListEventsResult(
        success=True,
        events=(),
        issues=(),
    ).success


def test_inspection_result_consistency() -> None:
    """Inspection results must not mix availability and failure data."""
    available = CalendarProviderInspectionResult(
        available=True,
        provider="khal",
        version="0.11.4",
        issues=(),
    )
    unavailable = CalendarProviderInspectionResult(
        available=False,
        provider="khal",
        version=None,
        issues=(issue(),),
    )

    assert available.version == "0.11.4"
    assert unavailable.issues == (issue(),)


def test_calendar_provider_protocol_is_runtime_checkable() -> None:
    """Complete compatible objects should satisfy the protocol."""

    class Provider:
        def inspect(self) -> CalendarProviderInspectionResult:
            return CalendarProviderInspectionResult(
                available=True,
                provider="test",
                version="1.0",
                issues=(),
            )

        def list_calendars(self) -> CalendarListCalendarsResult:
            return CalendarListCalendarsResult(
                success=True,
                calendars=(
                    CalendarCollection(
                        calendar_id=CALENDAR_ID,
                        display_name="Personal",
                    ),
                ),
                issues=(),
            )

        def list_events(
            self,
            query: CalendarEventQuery,
        ) -> CalendarListEventsResult:
            return CalendarListEventsResult(
                success=True,
                events=(event(),),
                issues=(),
            )

        def show_event(
            self,
            calendar_id: str,
            event_uid: str,
        ) -> CalendarShowEventResult:
            return CalendarShowEventResult(
                success=True,
                event=event(),
                issues=(),
            )

        def create_event(
            self,
            request: CalendarCreateRequest,
        ) -> CalendarMutationResult:
            return CalendarMutationResult(
                success=True,
                event=event(),
                issues=(),
            )

        def modify_event(
            self,
            request: CalendarModifyRequest,
        ) -> CalendarMutationResult:
            return CalendarMutationResult(
                success=True,
                event=event(),
                issues=(),
            )

        def cancel_event(
            self,
            request: CalendarCancelRequest,
        ) -> CalendarMutationResult:
            return CalendarMutationResult(
                success=True,
                event=CalendarEvent(
                    calendar_id=CALENDAR_ID,
                    event_uid=EVENT_UID,
                    summary="Maintenance planning",
                    timing=timed_timing(),
                    cancelled=True,
                ),
                issues=(),
            )

    assert isinstance(Provider(), CalendarProvider)


def timezone_plus_two() -> timezone:
    """Return one fixed non-UTC offset for validation tests."""
    return timezone(timedelta(hours=2))
