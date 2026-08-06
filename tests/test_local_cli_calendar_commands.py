"""Tests for read-only Local CLI calendar commands."""

from datetime import UTC, date, datetime
from pathlib import Path

from lea.calendars import (
    CalendarCollection,
    CalendarEvent,
    CalendarEventQuery,
    CalendarEventTiming,
    CalendarListCalendarsResult,
    CalendarListEventsResult,
    CalendarProviderInspectionResult,
    CalendarShowEventResult,
)
from lea.cli.calendar_commands import (
    CalendarCommandDependencies,
    execute_calendar_events,
    execute_calendar_list,
    execute_calendar_show,
    render_calendar_events_result,
)
from lea.runtime import ConfigurationResult, isolated_test_runtime_config


class RecordingCalendarProvider:
    """Return deterministic calendar reads and record query boundaries."""

    def __init__(self) -> None:
        self.queries: list[CalendarEventQuery] = []

    def inspect(self) -> CalendarProviderInspectionResult:
        return CalendarProviderInspectionResult(True, "test", "1", ())

    def list_calendars(self) -> CalendarListCalendarsResult:
        return CalendarListCalendarsResult(
            True, (CalendarCollection("personal", "Personal"),), ()
        )

    def list_events(self, query: CalendarEventQuery) -> CalendarListEventsResult:
        self.queries.append(query)
        return CalendarListEventsResult(True, (_event(),), ())

    def show_event(self, calendar_id: str, event_uid: str) -> CalendarShowEventResult:
        assert (calendar_id, event_uid) == ("personal", "event-1")
        return CalendarShowEventResult(True, _event(), ())

    def create_event(self, request: object) -> object:
        raise AssertionError("read command attempted a mutation")

    def modify_event(self, request: object) -> object:
        raise AssertionError("read command attempted a mutation")

    def cancel_event(self, request: object) -> object:
        raise AssertionError("read command attempted a mutation")


def _event() -> CalendarEvent:
    return CalendarEvent(
        calendar_id="personal",
        event_uid="event-1",
        summary="Review milestone",
        timing=CalendarEventTiming(
            start=datetime(2026, 8, 4, 8, tzinfo=UTC),
            end=datetime(2026, 8, 4, 9, tzinfo=UTC),
            timezone="Africa/Gaborone",
        ),
    )


def _dependencies(
    tmp_path: Path, provider: RecordingCalendarProvider
) -> CalendarCommandDependencies:
    config = isolated_test_runtime_config(tmp_path / "runtime")
    return CalendarCommandDependencies(
        load_configuration=lambda _path: ConfigurationResult(True, config, ()),
        build_provider=lambda _config: provider,  # type: ignore[arg-type,return-value]
    )


def test_calendar_read_commands_use_provider_neutral_boundary(tmp_path: Path) -> None:
    provider = RecordingCalendarProvider()
    dependencies = _dependencies(tmp_path, provider)
    config_path = tmp_path / "lea.toml"
    query = CalendarEventQuery(date(2026, 8, 4), date(2026, 8, 5), ("personal",))

    calendars = execute_calendar_list(
        config_path=config_path, expected_profile=None, dependencies=dependencies
    )
    events = execute_calendar_events(
        config_path=config_path,
        expected_profile=None,
        query=query,
        dependencies=dependencies,
    )
    shown = execute_calendar_show(
        config_path=config_path,
        expected_profile=None,
        calendar_id="personal",
        event_uid="event-1",
        dependencies=dependencies,
    )

    assert calendars.data == {
        "calendars": [
            {"calendar_id": "personal", "display_name": "Personal", "read_only": False}
        ]
    }
    assert provider.queries == [query]
    assert events.success is True
    assert shown.success is True
    assert "Review milestone" in render_calendar_events_result(events)
