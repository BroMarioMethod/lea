"""Tests for channel-neutral calendar read routing."""

from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path

from lea.actions import ActionProposal
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
    CalendarProviderInspectionResult,
    CalendarProviderIssue,
    CalendarShowEventResult,
)
from lea.channels import (
    ChannelIdentity,
    ChannelName,
    ChannelRequest,
    ChannelRequestType,
    ChannelResponseOutcome,
)
from lea.channels.handlers import (
    ChannelHandlerDependencies,
    build_default_channel_application,
)
from lea.proposals import ProposalSubmissionResult
from lea.runtime import RuntimeProfile

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
REQUEST_ID = "11111111-1111-4111-8111-111111111111"


class RecordingCalendarProvider:
    """Record channel calendar-provider reads."""

    def __init__(self) -> None:
        self.calendar_calls = 0
        self.queries: list[CalendarEventQuery] = []
        self.shown: list[tuple[str, str]] = []
        self.failure: CalendarProviderIssue | None = None

    def inspect(self) -> CalendarProviderInspectionResult:
        return CalendarProviderInspectionResult(
            available=True,
            provider="test",
            version="1.0",
            issues=(),
        )

    def list_calendars(self) -> CalendarListCalendarsResult:
        self.calendar_calls += 1
        if self.failure is not None:
            return CalendarListCalendarsResult(False, (), (self.failure,))
        return CalendarListCalendarsResult(
            True,
            (
                CalendarCollection(
                    calendar_id="personal",
                    display_name="Personal",
                ),
            ),
            (),
        )

    def list_events(
        self,
        query: CalendarEventQuery,
    ) -> CalendarListEventsResult:
        self.queries.append(query)
        if self.failure is not None:
            return CalendarListEventsResult(False, (), (self.failure,))
        return CalendarListEventsResult(
            True,
            (_timed_event(), _all_day_event()),
            (),
        )

    def show_event(
        self,
        calendar_id: str,
        event_uid: str,
    ) -> CalendarShowEventResult:
        self.shown.append((calendar_id, event_uid))
        if self.failure is not None:
            return CalendarShowEventResult(False, None, (self.failure,))
        return CalendarShowEventResult(True, _timed_event(), ())

    def create_event(
        self,
        request: CalendarCreateRequest,
    ) -> CalendarMutationResult:
        raise AssertionError("Read routing must not create events.")

    def modify_event(
        self,
        request: CalendarModifyRequest,
    ) -> CalendarMutationResult:
        raise AssertionError("Read routing must not modify events.")

    def cancel_event(
        self,
        request: CalendarCancelRequest,
    ) -> CalendarMutationResult:
        raise AssertionError("Read routing must not cancel events.")


def _timed_event() -> CalendarEvent:
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
    return CalendarEvent(
        calendar_id="personal",
        event_uid="all-day-event",
        summary="All-day event",
        timing=CalendarEventTiming(
            start=date(2026, 8, 2),
            end=date(2026, 8, 3),
        ),
        cancelled=True,
    )


def _unused_submitter(
    proposal: ActionProposal,
) -> ProposalSubmissionResult:
    del proposal
    raise AssertionError("Calendar reads must not submit proposals.")


def _dependencies(
    tmp_path: Path,
    provider: RecordingCalendarProvider | None,
) -> ChannelHandlerDependencies:
    return ChannelHandlerDependencies(
        config_path=(tmp_path / "lea.toml").resolve(),
        expected_profile=RuntimeProfile.TEST,
        clock=lambda: NOW,
        proposal_submitter=_unused_submitter,
        proposal_id_source=lambda: "22222222-2222-4222-8222-222222222222",
        control_id_source=lambda: "33333333-3333-4333-8333-333333333333",
        calendar_provider=provider,
    )


def _request(
    command: str,
    parameters: dict[str, object],
    *,
    capabilities: tuple[str, ...] = ("Calendar.Read",),
    calendar_ids: tuple[str, ...] = (),
) -> ChannelRequest:
    return ChannelRequest(
        request_id=REQUEST_ID,
        source_update_id="test:1",
        identity=ChannelIdentity(
            channel=ChannelName.WEB,
            user_id="calendar-user",
            conversation_id="calendar-conversation",
            role="owner",
            capabilities=capabilities,
            calendar_ids=calendar_ids,
        ),
        request_type=ChannelRequestType.COMMAND,
        command=command,
        parameters=parameters,
        received_at=NOW,
    )


def test_default_application_registers_singular_calendar_commands(
    tmp_path: Path,
) -> None:
    application = build_default_channel_application(
        _dependencies(tmp_path, RecordingCalendarProvider())
    )

    assert "calendar.list_calendars" in application.commands
    assert "calendar.list_events" in application.commands
    assert "calendar.show_event" in application.commands


def test_calendar_read_capability_is_required_before_provider_access(
    tmp_path: Path,
) -> None:
    provider = RecordingCalendarProvider()
    result = build_default_channel_application(
        _dependencies(tmp_path, provider)
    ).handle(
        _request(
            "calendar.list_calendars",
            {"arguments": []},
            capabilities=(),
        )
    )

    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.NOT_AUTHORISED
    assert result.response.issue is not None
    assert result.response.issue.code == "calendar_read_capability_required"
    assert result.response.data is not None
    assert result.response.data["required_capability"] == "Calendar.Read"
    assert provider.calendar_calls == 0


def test_missing_calendar_provider_is_temporarily_unavailable(
    tmp_path: Path,
) -> None:
    result = build_default_channel_application(_dependencies(tmp_path, None)).handle(
        _request(
            "calendar.list_calendars",
            {"arguments": []},
        )
    )

    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.TEMPORARILY_UNAVAILABLE
    assert result.response.issue is not None
    assert result.response.issue.code == "calendar_provider_unavailable"


def test_list_calendars_returns_stable_collection_data(
    tmp_path: Path,
) -> None:
    provider = RecordingCalendarProvider()
    result = build_default_channel_application(
        _dependencies(tmp_path, provider)
    ).handle(
        _request(
            "calendar.list_calendars",
            {"arguments": []},
        )
    )

    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.SUCCEEDED
    assert result.response.message == "Calendars loaded."
    assert result.response.data is not None
    assert result.response.data["calendars"] == (
        {
            "calendar_id": "personal",
            "display_name": "Personal",
            "read_only": False,
        },
    )


def test_calendar_policy_filters_discovery_and_scopes_unfiltered_query(
    tmp_path: Path,
) -> None:
    provider = RecordingCalendarProvider()
    application = build_default_channel_application(_dependencies(tmp_path, provider))

    calendars = application.handle(
        _request(
            "calendar.list_calendars",
            {"arguments": []},
            calendar_ids=("personal",),
        )
    )
    application.handle(
        _request(
            "calendar.list_events",
            {"arguments": ["2026-08-01", "2026-08-03"]},
            calendar_ids=("personal",),
        )
    )

    assert calendars.response is not None
    assert calendars.response.data is not None
    calendar_data = calendars.response.data["calendars"]
    assert isinstance(calendar_data, tuple)
    assert tuple(
        value["calendar_id"] for value in calendar_data if isinstance(value, Mapping)
    ) == ("personal",)
    assert provider.queries[-1].calendar_ids == ("personal",)


def test_calendar_policy_denies_exact_read_before_provider_access(
    tmp_path: Path,
) -> None:
    provider = RecordingCalendarProvider()
    result = build_default_channel_application(
        _dependencies(tmp_path, provider)
    ).handle(
        _request(
            "calendar.show_event",
            {"arguments": ["work", "secret-event"]},
            calendar_ids=("personal",),
        )
    )

    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.NOT_AUTHORISED
    assert result.response.issue is not None
    assert result.response.issue.code == "calendar_policy_denied"
    assert provider.shown == []


def test_list_events_accepts_named_query_parameters(
    tmp_path: Path,
) -> None:
    provider = RecordingCalendarProvider()
    result = build_default_channel_application(
        _dependencies(tmp_path, provider)
    ).handle(
        _request(
            "calendar.list_events",
            {
                "arguments": [],
                "start_date": "2026-08-01",
                "end_date": "2026-08-04",
                "calendar_ids": ["work", "personal", "work"],
                "include_cancelled": True,
            },
        )
    )

    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.SUCCEEDED
    assert provider.queries == [
        CalendarEventQuery(
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 4),
            calendar_ids=("personal", "work"),
            include_cancelled=True,
        )
    ]
    assert result.response.data is not None
    events = result.response.data["events"]
    assert isinstance(events, tuple)
    assert len(events) == 2
    timed = events[0]
    assert isinstance(timed, Mapping)
    assert timed["timing"] == {
        "start": "2026-08-01T08:00:00+00:00",
        "end": "2026-08-01T09:00:00+00:00",
        "all_day": False,
        "timezone": "Africa/Gaborone",
    }


def test_list_events_accepts_positional_range_and_calendar_ids(
    tmp_path: Path,
) -> None:
    provider = RecordingCalendarProvider()
    result = build_default_channel_application(
        _dependencies(tmp_path, provider)
    ).handle(
        _request(
            "calendar.list_events",
            {
                "arguments": [
                    "2026-08-01",
                    "2026-08-04",
                    "work",
                    "personal",
                ]
            },
        )
    )

    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.SUCCEEDED
    assert provider.queries == [
        CalendarEventQuery(
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 4),
            calendar_ids=("personal", "work"),
        )
    ]


def test_invalid_event_range_fails_before_provider_call(
    tmp_path: Path,
) -> None:
    provider = RecordingCalendarProvider()
    result = build_default_channel_application(
        _dependencies(tmp_path, provider)
    ).handle(
        _request(
            "calendar.list_events",
            {
                "arguments": [],
                "start_date": "2026-08-04",
                "end_date": "2026-08-01",
            },
        )
    )

    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.VALIDATION_FAILED
    assert result.response.issue is not None
    assert result.response.issue.code == "calendar_event_query_invalid"
    assert provider.queries == []


def test_show_event_preserves_exact_composite_identity(
    tmp_path: Path,
) -> None:
    provider = RecordingCalendarProvider()
    result = build_default_channel_application(
        _dependencies(tmp_path, provider)
    ).handle(
        _request(
            "calendar.show_event",
            {
                "arguments": [
                    "personal",
                    "timed-event",
                ]
            },
        )
    )

    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.SUCCEEDED
    assert provider.shown == [("personal", "timed-event")]
    assert result.response.data is not None
    event = result.response.data["event"]
    assert isinstance(event, Mapping)
    assert event["event_uid"] == "timed-event"


def test_show_event_not_found_maps_to_channel_not_found(
    tmp_path: Path,
) -> None:
    provider = RecordingCalendarProvider()
    provider.failure = CalendarProviderIssue(
        code="khal_calendar_event_not_found",
        message="The calendar event was not found.",
        provider="khal",
        operation="show_event",
        calendar_id="personal",
        event_uid="missing",
    )
    result = build_default_channel_application(
        _dependencies(tmp_path, provider)
    ).handle(
        _request(
            "calendar.show_event",
            {
                "arguments": [
                    "personal",
                    "missing",
                ]
            },
        )
    )

    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.NOT_FOUND
    assert result.response.issue is not None
    assert result.response.issue.code == "khal_calendar_event_not_found"


def test_unknown_calendar_parameter_fails_before_provider_call(
    tmp_path: Path,
) -> None:
    provider = RecordingCalendarProvider()
    result = build_default_channel_application(
        _dependencies(tmp_path, provider)
    ).handle(
        _request(
            "calendar.list_calendars",
            {
                "arguments": [],
                "unexpected": True,
            },
        )
    )

    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.VALIDATION_FAILED
    assert provider.calendar_calls == 0
