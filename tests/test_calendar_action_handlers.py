"""Tests for provider-neutral calendar action handlers."""

from datetime import UTC, date, datetime

import pytest

from lea.actions import (
    ActionProposal,
    ActionStatus,
    execute_action,
)
from lea.calendars import (
    CalendarActionHandlerError,
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
    CalendarProviderInspectionResult,
    CalendarProviderIssue,
    CalendarShowEventResult,
    CalendarSynchronizationInspectionResult,
    CalendarSynchronizationResult,
    calendar_action_handler_registry,
    cancel_calendar_event_action_handler,
    create_calendar_event_action_handler,
    list_calendar_events_action_handler,
    list_calendars_action_handler,
    modify_calendar_event_action_handler,
    show_calendar_event_action_handler,
    synchronize_calendars_action_handler,
)

PROPOSAL_ID = "11111111-1111-4111-8111-111111111111"
STARTED_AT = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 8, 1, 8, 1, tzinfo=UTC)


class RecordingProvider:
    """Record calendar action calls."""

    def __init__(self) -> None:
        self.calendar_list_calls = 0
        self.event_queries: list[CalendarEventQuery] = []
        self.shown: list[tuple[str, str]] = []
        self.created: list[CalendarCreateRequest] = []
        self.modified: list[CalendarModifyRequest] = []
        self.cancelled: list[CalendarCancelRequest] = []
        self.failure: CalendarProviderIssue | None = None

    def inspect(self) -> CalendarProviderInspectionResult:
        return CalendarProviderInspectionResult(
            available=True,
            provider="test",
            version="1.0",
            issues=(),
        )

    def list_calendars(self) -> CalendarListCalendarsResult:
        self.calendar_list_calls += 1

        if self.failure is not None:
            return CalendarListCalendarsResult(
                success=False,
                calendars=(),
                issues=(self.failure,),
            )

        return CalendarListCalendarsResult(
            success=True,
            calendars=(
                CalendarCollection(
                    calendar_id="personal",
                    display_name="Personal",
                ),
                CalendarCollection(
                    calendar_id="work",
                    display_name="Work",
                    read_only=True,
                ),
            ),
            issues=(),
        )

    def list_events(
        self,
        query: CalendarEventQuery,
    ) -> CalendarListEventsResult:
        self.event_queries.append(query)

        if self.failure is not None:
            return CalendarListEventsResult(
                success=False,
                events=(),
                issues=(self.failure,),
            )

        return CalendarListEventsResult(
            success=True,
            events=(
                _timed_event(),
                _all_day_event(),
            ),
            issues=(),
        )

    def show_event(
        self,
        calendar_id: str,
        event_uid: str,
    ) -> CalendarShowEventResult:
        self.shown.append((calendar_id, event_uid))

        if self.failure is not None:
            return CalendarShowEventResult(
                success=False,
                event=None,
                issues=(self.failure,),
            )

        return CalendarShowEventResult(
            success=True,
            event=_timed_event(),
            issues=(),
        )

    def create_event(
        self,
        request: CalendarCreateRequest,
    ) -> CalendarMutationResult:
        self.created.append(request)
        return CalendarMutationResult(True, _timed_event(), ())

    def modify_event(
        self,
        request: CalendarModifyRequest,
    ) -> CalendarMutationResult:
        self.modified.append(request)
        return CalendarMutationResult(True, _timed_event(), ())

    def cancel_event(
        self,
        request: CalendarCancelRequest,
    ) -> CalendarMutationResult:
        self.cancelled.append(request)
        return CalendarMutationResult(True, _all_day_event(), ())


def _proposal(
    action: str,
    parameters: dict[str, object],
    *,
    status: ActionStatus = ActionStatus.EXECUTING,
) -> ActionProposal:
    """Create one deterministic calendar proposal."""
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action=action,
        parameters=parameters,
        source="test",
        status=status,
        created_at=datetime(2026, 8, 1, 7, 0, tzinfo=UTC),
    )


def _timed_event() -> CalendarEvent:
    """Return one canonical UTC timed event."""
    return CalendarEvent(
        calendar_id="personal",
        event_uid="timed-event",
        summary="Timed event",
        timing=CalendarEventTiming(
            start=datetime(2026, 8, 1, 8, 0, tzinfo=UTC),
            end=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
            timezone="Africa/Gaborone",
        ),
        description="Description",
        location="Office",
    )


def _all_day_event() -> CalendarEvent:
    """Return one all-day cancelled event."""
    return CalendarEvent(
        calendar_id="work",
        event_uid="all-day-event",
        summary="All-day event",
        timing=CalendarEventTiming(
            start=date(2026, 8, 2),
            end=date(2026, 8, 3),
        ),
        cancelled=True,
    )


def test_registry_contains_calendar_read_and_mutation_handlers() -> None:
    """The calendar namespace should expose completed provider actions."""
    registry = calendar_action_handler_registry(RecordingProvider())

    assert len(registry) == 6
    assert "calendar.list_calendars" in registry
    assert "calendar.list_events" in registry
    assert "calendar.show_event" in registry
    assert "calendar.create" in registry
    assert "calendar.modify" in registry
    assert "calendar.cancel" in registry


def test_create_handler_reconstructs_canonical_request() -> None:
    provider = RecordingProvider()
    output = create_calendar_event_action_handler(provider)(
        _proposal(
            "calendar.create",
            {
                "calendar_id": "personal",
                "summary": "Appointment",
                "timing": {
                    "start": "2026-08-02",
                    "end": "2026-08-03",
                    "all_day": True,
                    "timezone": None,
                },
            },
        )
    )

    assert provider.created == [
        CalendarCreateRequest(
            "personal",
            "Appointment",
            CalendarEventTiming(date(2026, 8, 2), date(2026, 8, 3)),
        )
    ]
    assert output is not None
    assert output["event"] is not None


def test_modify_and_cancel_handlers_preserve_exact_identity() -> None:
    provider = RecordingProvider()
    modify_calendar_event_action_handler(provider)(
        _proposal(
            "calendar.modify",
            {
                "calendar_id": "personal",
                "event_uid": "event-1",
                "clear_location": True,
            },
        )
    )
    cancel_calendar_event_action_handler(provider)(
        _proposal(
            "calendar.cancel",
            {"calendar_id": "personal", "event_uid": "event-1"},
        )
    )

    assert provider.modified == [
        CalendarModifyRequest("personal", "event-1", clear_location=True)
    ]
    assert provider.cancelled == [CalendarCancelRequest("personal", "event-1")]


def test_invalid_mutation_timing_fails_before_provider_call() -> None:
    provider = RecordingProvider()
    with pytest.raises(CalendarActionHandlerError, match="timing"):
        create_calendar_event_action_handler(provider)(
            _proposal(
                "calendar.create",
                {
                    "calendar_id": "personal",
                    "summary": "Appointment",
                    "timing": {
                        "start": "2026-08-02T08:00:00+02:00",
                        "end": "2026-08-02T09:00:00+02:00",
                        "all_day": False,
                        "timezone": "Africa/Gaborone",
                    },
                },
            )
        )
    assert provider.created == []


def test_sync_handler_invokes_only_explicit_execution_boundary() -> None:
    class Synchronizer:
        calls = 0

        def inspect(self) -> CalendarSynchronizationInspectionResult:
            return CalendarSynchronizationInspectionResult(True, "test", "1", ())

        def synchronize(self) -> CalendarSynchronizationResult:
            self.calls += 1
            return CalendarSynchronizationResult(True, ())

    synchronizer = Synchronizer()
    handler = synchronize_calendars_action_handler(synchronizer)
    assert synchronizer.calls == 0

    output = handler(_proposal("calendar.sync", {}))

    assert synchronizer.calls == 1
    assert output == {"synchronized": True}


def test_sync_handler_propagates_structured_failure() -> None:
    class FailedSynchronizer:
        def inspect(self) -> CalendarSynchronizationInspectionResult:
            raise AssertionError

        def synchronize(self) -> CalendarSynchronizationResult:
            return CalendarSynchronizationResult(
                False,
                (CalendarProviderIssue("sync_conflict", "Synchronization failed."),),
            )

    with pytest.raises(CalendarActionHandlerError, match="sync_conflict"):
        synchronize_calendars_action_handler(FailedSynchronizer())(
            _proposal("calendar.sync", {})
        )


def test_list_calendars_serialises_provider_projections() -> None:
    """Calendar collection metadata should remain explicit and stable."""
    provider = RecordingProvider()

    output = list_calendars_action_handler(provider)(
        _proposal("calendar.list_calendars", {})
    )

    assert provider.calendar_list_calls == 1
    assert output == {
        "calendars": [
            {
                "calendar_id": "personal",
                "display_name": "Personal",
                "read_only": False,
            },
            {
                "calendar_id": "work",
                "display_name": "Work",
                "read_only": True,
            },
        ]
    }


def test_list_events_builds_canonical_provider_query() -> None:
    """Action parameters should become the provider-neutral query contract."""
    provider = RecordingProvider()

    list_calendar_events_action_handler(provider)(
        _proposal(
            "calendar.list_events",
            {
                "start_date": "2026-08-01",
                "end_date": "2026-08-04",
                "calendar_ids": ["work", "personal", "work"],
                "include_cancelled": True,
            },
        )
    )

    assert provider.event_queries == [
        CalendarEventQuery(
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 4),
            calendar_ids=("personal", "work"),
            include_cancelled=True,
        )
    ]


def test_list_events_serialises_timed_and_all_day_intervals() -> None:
    """Read output should distinguish dates from canonical UTC instants."""
    provider = RecordingProvider()

    output = list_calendar_events_action_handler(provider)(
        _proposal(
            "calendar.list_events",
            {
                "start_date": "2026-08-01",
                "end_date": "2026-08-04",
            },
        )
    )

    assert output == {
        "events": [
            {
                "calendar_id": "personal",
                "event_uid": "timed-event",
                "summary": "Timed event",
                "timing": {
                    "start": "2026-08-01T08:00:00+00:00",
                    "end": "2026-08-01T09:00:00+00:00",
                    "all_day": False,
                    "timezone": "Africa/Gaborone",
                },
                "description": "Description",
                "location": "Office",
                "cancelled": False,
            },
            {
                "calendar_id": "work",
                "event_uid": "all-day-event",
                "summary": "All-day event",
                "timing": {
                    "start": "2026-08-02",
                    "end": "2026-08-03",
                    "all_day": True,
                    "timezone": None,
                },
                "description": None,
                "location": None,
                "cancelled": True,
            },
        ]
    }


def test_show_event_uses_only_composite_stable_identity() -> None:
    """Exact lookup should forward calendar ID and event UID unchanged."""
    provider = RecordingProvider()

    output = show_calendar_event_action_handler(provider)(
        _proposal(
            "calendar.show_event",
            {
                "calendar_id": "personal",
                "event_uid": "timed-event",
            },
        )
    )

    assert provider.shown == [("personal", "timed-event")]
    assert output is not None
    event = output["event"]
    assert isinstance(event, dict)
    assert event["event_uid"] == "timed-event"


def test_empty_successful_lists_remain_successful_outputs() -> None:
    """Empty read results should not be mistaken for provider failure."""

    class EmptyProvider(RecordingProvider):
        def list_calendars(self) -> CalendarListCalendarsResult:
            return CalendarListCalendarsResult(True, (), ())

        def list_events(
            self,
            query: CalendarEventQuery,
        ) -> CalendarListEventsResult:
            return CalendarListEventsResult(True, (), ())

    provider = EmptyProvider()

    calendars = list_calendars_action_handler(provider)(
        _proposal("calendar.list_calendars", {})
    )
    events = list_calendar_events_action_handler(provider)(
        _proposal(
            "calendar.list_events",
            {
                "start_date": "2026-08-01",
                "end_date": "2026-08-02",
            },
        )
    )

    assert calendars == {"calendars": []}
    assert events == {"events": []}


def test_unknown_parameter_is_rejected_before_provider_call() -> None:
    """Unrecognised fields must fail before any provider access."""
    provider = RecordingProvider()

    with pytest.raises(
        CalendarActionHandlerError,
        match="calendar_action_parameter_unknown",
    ):
        list_calendars_action_handler(provider)(
            _proposal(
                "calendar.list_calendars",
                {"unexpected": True},
            )
        )

    assert provider.calendar_list_calls == 0


@pytest.mark.parametrize(
    ("parameters", "message"),
    [
        (
            {
                "start_date": "20260801",
                "end_date": "2026-08-02",
            },
            "start_date",
        ),
        (
            {
                "start_date": "2026-08-01",
                "end_date": "not-a-date",
            },
            "end_date",
        ),
        (
            {
                "start_date": "2026-08-01",
                "end_date": "2026-08-02",
                "calendar_ids": "personal",
            },
            "calendar_ids",
        ),
        (
            {
                "start_date": "2026-08-01",
                "end_date": "2026-08-02",
                "include_cancelled": 1,
            },
            "include_cancelled",
        ),
    ],
)
def test_invalid_list_parameters_fail_before_provider_call(
    parameters: dict[str, object],
    message: str,
) -> None:
    """Malformed read parameters should never reach the provider."""
    provider = RecordingProvider()

    with pytest.raises(
        CalendarActionHandlerError,
        match=message,
    ):
        list_calendar_events_action_handler(provider)(
            _proposal("calendar.list_events", parameters)
        )

    assert provider.event_queries == []


@pytest.mark.parametrize(
    "parameters",
    [
        {
            "calendar_id": " personal",
            "event_uid": "event",
        },
        {
            "calendar_id": "personal",
            "event_uid": " ",
        },
        {
            "calendar_id": "personal",
            "event_uid": "event\nuid",
        },
    ],
)
def test_invalid_exact_identity_fails_before_provider_call(
    parameters: dict[str, object],
) -> None:
    """Exact provider identifiers should be validated without normalisation."""
    provider = RecordingProvider()

    with pytest.raises(
        CalendarActionHandlerError,
        match="calendar_action_parameter_invalid",
    ):
        show_calendar_event_action_handler(provider)(
            _proposal("calendar.show_event", parameters)
        )

    assert provider.shown == []


@pytest.mark.parametrize(
    ("factory", "action", "parameters"),
    [
        (
            list_calendars_action_handler,
            "calendar.list_calendars",
            {},
        ),
        (
            list_calendar_events_action_handler,
            "calendar.list_events",
            {
                "start_date": "2026-08-01",
                "end_date": "2026-08-02",
            },
        ),
        (
            show_calendar_event_action_handler,
            "calendar.show_event",
            {
                "calendar_id": "personal",
                "event_uid": "timed-event",
            },
        ),
    ],
)
def test_provider_failure_preserves_first_issue(
    factory: object,
    action: str,
    parameters: dict[str, object],
) -> None:
    """Read handlers should preserve the first structured provider issue."""
    provider = RecordingProvider()
    provider.failure = CalendarProviderIssue(
        code="khal_read_failed",
        message="Calendar read failed.",
        provider="khal",
        operation=action,
    )

    assert callable(factory)

    with pytest.raises(
        CalendarActionHandlerError,
        match="khal_read_failed: Calendar read failed",
    ):
        factory(provider)(_proposal(action, parameters))


def test_approved_read_action_executes_through_action_boundary() -> None:
    """Calendar action output should satisfy the JSON-compatible execution contract."""
    registry = calendar_action_handler_registry(RecordingProvider())

    result = execute_action(
        _proposal(
            "calendar.list_events",
            {
                "start_date": "2026-08-01",
                "end_date": "2026-08-04",
            },
            status=ActionStatus.APPROVED,
        ),
        registry,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )

    assert result.success is True
    assert result.execution is not None
    assert result.execution.output is not None
    events = result.execution.output.get("events")
    assert isinstance(events, tuple)
    assert len(events) == 2
