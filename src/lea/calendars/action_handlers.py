"""Provider-neutral read-only calendar action handlers."""

from collections.abc import Mapping
from datetime import date, datetime

from lea.actions import ActionHandler, ActionHandlerRegistry, ActionProposal
from lea.calendars.contracts import (
    CalendarCollection,
    CalendarEvent,
    CalendarEventQuery,
    CalendarEventTiming,
    CalendarListCalendarsResult,
    CalendarListEventsResult,
    CalendarProviderIssue,
    CalendarShowEventResult,
)
from lea.calendars.provider import CalendarProvider


class CalendarActionHandlerError(RuntimeError):
    """Deterministic failure raised by a calendar action handler."""

    def __init__(self, *, code: str, message: str) -> None:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code must be non-empty.")

        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be non-empty.")

        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def list_calendars_action_handler(
    provider: CalendarProvider,
) -> ActionHandler:
    """Return a handler for one ``calendar.list_calendars`` proposal."""

    def handle(proposal: ActionProposal) -> Mapping[str, object]:
        _parameters(proposal, allowed=set())
        return _calendar_list_output(provider.list_calendars())

    return handle


def list_calendar_events_action_handler(
    provider: CalendarProvider,
) -> ActionHandler:
    """Return a handler for one ``calendar.list_events`` proposal."""

    def handle(proposal: ActionProposal) -> Mapping[str, object]:
        parameters = _parameters(
            proposal,
            allowed={
                "start_date",
                "end_date",
                "calendar_ids",
                "include_cancelled",
            },
        )
        query = CalendarEventQuery(
            start_date=_required_date(parameters, "start_date"),
            end_date=_required_date(parameters, "end_date"),
            calendar_ids=_optional_identifier_tuple(
                parameters,
                "calendar_ids",
            ),
            include_cancelled=_optional_boolean(
                parameters,
                "include_cancelled",
            ),
        )
        return _event_list_output(provider.list_events(query))

    return handle


def show_calendar_event_action_handler(
    provider: CalendarProvider,
) -> ActionHandler:
    """Return a handler for one ``calendar.show_event`` proposal."""

    def handle(proposal: ActionProposal) -> Mapping[str, object]:
        parameters = _parameters(
            proposal,
            allowed={"calendar_id", "event_uid"},
        )
        calendar_id = _required_identifier(
            parameters,
            "calendar_id",
        )
        event_uid = _required_identifier(
            parameters,
            "event_uid",
        )
        return _show_event_output(
            provider.show_event(
                calendar_id,
                event_uid,
            )
        )

    return handle


def calendar_action_handler_registry(
    provider: CalendarProvider,
) -> ActionHandlerRegistry:
    """Return the canonical read-only calendar action-handler registry."""
    registry = ActionHandlerRegistry()
    registry.register(
        "calendar.list_calendars",
        list_calendars_action_handler(provider),
    )
    registry.register(
        "calendar.list_events",
        list_calendar_events_action_handler(provider),
    )
    registry.register(
        "calendar.show_event",
        show_calendar_event_action_handler(provider),
    )
    return registry


def _parameters(
    proposal: ActionProposal,
    *,
    allowed: set[str],
) -> Mapping[str, object]:
    """Return parameters after rejecting every unknown field."""
    parameters = proposal.parameters
    unknown = sorted(set(parameters) - allowed)

    if unknown:
        raise CalendarActionHandlerError(
            code="calendar_action_parameter_unknown",
            message=(f"Unsupported calendar action parameter: {unknown[0]}."),
        )

    return parameters


def _required_date(
    parameters: Mapping[str, object],
    field: str,
) -> date:
    """Parse one canonical ISO local date."""
    value = parameters.get(field)

    if not isinstance(value, str) or not value:
        raise CalendarActionHandlerError(
            code="calendar_action_parameter_invalid",
            message=f"{field} must be a canonical ISO date string.",
        )

    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise CalendarActionHandlerError(
            code="calendar_action_parameter_invalid",
            message=f"{field} must be a valid ISO date.",
        ) from error

    if parsed.isoformat() != value:
        raise CalendarActionHandlerError(
            code="calendar_action_parameter_invalid",
            message=f"{field} must use YYYY-MM-DD format.",
        )

    return parsed


def _required_identifier(
    parameters: Mapping[str, object],
    field: str,
) -> str:
    """Return one exact opaque provider identifier."""
    value = parameters.get(field)

    if not isinstance(value, str) or not value.strip():
        raise CalendarActionHandlerError(
            code="calendar_action_parameter_invalid",
            message=f"{field} must be a non-empty string.",
        )

    if value != value.strip():
        raise CalendarActionHandlerError(
            code="calendar_action_parameter_invalid",
            message=(f"{field} must not contain leading or trailing whitespace."),
        )

    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise CalendarActionHandlerError(
            code="calendar_action_parameter_invalid",
            message=f"{field} must not contain control characters.",
        )

    return value


def _optional_identifier_tuple(
    parameters: Mapping[str, object],
    field: str,
) -> tuple[str, ...]:
    """Return one optional sequence of exact provider identifiers."""
    if field not in parameters:
        return ()

    value = parameters[field]

    if not isinstance(value, (list, tuple)):
        raise CalendarActionHandlerError(
            code="calendar_action_parameter_invalid",
            message=f"{field} must be an array of non-empty strings.",
        )

    values: list[str] = []

    for item in value:
        values.append(
            _required_identifier(
                {field: item},
                field,
            )
        )

    return tuple(values)


def _optional_boolean(
    parameters: Mapping[str, object],
    field: str,
) -> bool:
    """Return one optional boolean defaulting to false."""
    if field not in parameters:
        return False

    value = parameters[field]

    if not isinstance(value, bool):
        raise CalendarActionHandlerError(
            code="calendar_action_parameter_invalid",
            message=f"{field} must be a boolean.",
        )

    return value


def _calendar_list_output(
    result: CalendarListCalendarsResult,
) -> Mapping[str, object]:
    """Map one provider calendar-list result to action output."""
    if not result.success:
        _raise_provider_failure(result.issues)

    return {"calendars": [_calendar_to_dict(calendar) for calendar in result.calendars]}


def _event_list_output(
    result: CalendarListEventsResult,
) -> Mapping[str, object]:
    """Map one provider event-list result to action output."""
    if not result.success:
        _raise_provider_failure(result.issues)

    return {"events": [_event_to_dict(event) for event in result.events]}


def _show_event_output(
    result: CalendarShowEventResult,
) -> Mapping[str, object]:
    """Map one provider exact-event result to action output."""
    if not result.success:
        _raise_provider_failure(result.issues)

    if result.event is None:
        raise CalendarActionHandlerError(
            code="calendar_action_result_invalid",
            message="Successful exact-event lookup returned no event.",
        )

    return {"event": _event_to_dict(result.event)}


def _raise_provider_failure(
    issues: tuple[CalendarProviderIssue, ...],
) -> None:
    """Raise the first provider issue through the action boundary."""
    if not issues:
        raise CalendarActionHandlerError(
            code="calendar_provider_failed",
            message=("The calendar provider failed without reporting an issue."),
        )

    issue = issues[0]
    raise CalendarActionHandlerError(
        code=issue.code,
        message=issue.message,
    )


def _calendar_to_dict(
    calendar: CalendarCollection,
) -> dict[str, object]:
    """Return one JSON-compatible calendar projection."""
    return {
        "calendar_id": calendar.calendar_id,
        "display_name": calendar.display_name,
        "read_only": calendar.read_only,
    }


def _event_to_dict(
    event: CalendarEvent,
) -> dict[str, object]:
    """Return one canonical JSON-compatible event projection."""
    return {
        "calendar_id": event.calendar_id,
        "event_uid": event.event_uid,
        "summary": event.summary,
        "timing": _timing_to_dict(event.timing),
        "description": event.description,
        "location": event.location,
        "cancelled": event.cancelled,
    }


def _timing_to_dict(
    timing: CalendarEventTiming,
) -> dict[str, object]:
    """Return one explicit all-day or canonical-instant interval."""
    return {
        "start": _temporal_to_string(timing.start),
        "end": _temporal_to_string(timing.end),
        "all_day": timing.all_day,
        "timezone": timing.timezone,
    }


def _temporal_to_string(
    value: date | datetime,
) -> str:
    """Serialise one canonical date or datetime."""
    return value.isoformat()
