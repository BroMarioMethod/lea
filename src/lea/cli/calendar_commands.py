"""Read-only Local CLI calendar command services."""

from datetime import date, datetime
from pathlib import Path

from lea.calendars import CalendarEvent, CalendarEventQuery, CalendarProviderIssue
from lea.cli.calendar_provider import (
    CalendarProviderDependencies,
    load_calendar_provider,
)
from lea.cli.contracts import CliIssue, CliResult, JsonValue, LocalCliExitCode
from lea.runtime import RuntimeProfile

CalendarCommandDependencies = CalendarProviderDependencies


def execute_calendar_list(
    *,
    config_path: Path,
    expected_profile: RuntimeProfile | None,
    dependencies: CalendarCommandDependencies | None = None,
) -> CliResult:
    provider = load_calendar_provider(
        config_path=config_path,
        expected_profile=expected_profile,
        dependencies=dependencies,
    )
    if isinstance(provider, CliResult):
        return provider
    result = provider.list_calendars()
    if not result.success:
        return _provider_failure(result.issues, {"calendars": []})
    return CliResult.succeeded(
        data={
            "calendars": [
                {
                    "calendar_id": value.calendar_id,
                    "display_name": value.display_name,
                    "read_only": value.read_only,
                }
                for value in result.calendars
            ]
        }
    )


def execute_calendar_events(
    *,
    config_path: Path,
    expected_profile: RuntimeProfile | None,
    query: CalendarEventQuery,
    dependencies: CalendarCommandDependencies | None = None,
) -> CliResult:
    provider = load_calendar_provider(
        config_path=config_path,
        expected_profile=expected_profile,
        dependencies=dependencies,
    )
    if isinstance(provider, CliResult):
        return provider
    result = provider.list_events(query)
    if not result.success:
        return _provider_failure(result.issues, {"events": []})
    return CliResult.succeeded(
        data={"events": [_event_json(event) for event in result.events]}
    )


def execute_calendar_show(
    *,
    config_path: Path,
    expected_profile: RuntimeProfile | None,
    calendar_id: str,
    event_uid: str,
    dependencies: CalendarCommandDependencies | None = None,
) -> CliResult:
    provider = load_calendar_provider(
        config_path=config_path,
        expected_profile=expected_profile,
        dependencies=dependencies,
    )
    if isinstance(provider, CliResult):
        return provider
    result = provider.show_event(calendar_id, event_uid)
    if not result.success:
        return _provider_failure(result.issues, {"event": None})
    assert result.event is not None
    return CliResult.succeeded(data={"event": _event_json(result.event)})


def render_calendar_list_result(result: CliResult) -> str:
    if not result.success:
        return _issues(result)
    calendars = result.data.get("calendars") if isinstance(result.data, dict) else None
    if not isinstance(calendars, list) or not calendars:
        return "No calendars found."
    return "Calendars\n\n" + "\n".join(
        f"{item['calendar_id']}  {item['display_name']}"
        for item in calendars
        if isinstance(item, dict)
    )


def render_calendar_events_result(result: CliResult) -> str:
    if not result.success:
        return _issues(result)
    events = result.data.get("events") if isinstance(result.data, dict) else None
    if not isinstance(events, list) or not events:
        return "No calendar events found."
    return "Calendar events\n\n" + "\n".join(
        "  ".join(
            str(item[field])
            for field in ("calendar_id", "event_uid", "start", "summary")
        )
        for item in events
        if isinstance(item, dict)
    )


def render_calendar_show_result(result: CliResult) -> str:
    if not result.success:
        return _issues(result)
    event = result.data.get("event") if isinstance(result.data, dict) else None
    if not isinstance(event, dict):
        return _issues(result)
    return "\n".join(
        (
            "Calendar event",
            "",
            f"Calendar: {event['calendar_id']}",
            f"UID: {event['event_uid']}",
            f"Start: {event['start']}",
            f"End: {event['end']}",
            f"Summary: {event['summary']}",
        )
    )


def _event_json(event: CalendarEvent) -> dict[str, JsonValue]:
    def temporal(value: date | datetime) -> str:
        return value.isoformat()

    return {
        "calendar_id": event.calendar_id,
        "event_uid": event.event_uid,
        "summary": event.summary,
        "start": temporal(event.timing.start),
        "end": temporal(event.timing.end),
        "timezone": event.timing.timezone,
        "all_day": event.timing.all_day,
        "description": event.description,
        "location": event.location,
        "cancelled": event.cancelled,
    }


def _provider_failure(
    issues: tuple[CalendarProviderIssue, ...], data: JsonValue
) -> CliResult:
    return CliResult.failed(
        exit_code=LocalCliExitCode.APPLICATION_ERROR,
        issues=tuple(
            CliIssue(code=issue.code, message=issue.message, field=issue.field)
            for issue in issues
        ),
        data=data,
    )


def _issues(result: CliResult) -> str:
    return "\n".join(issue.message for issue in result.issues)
