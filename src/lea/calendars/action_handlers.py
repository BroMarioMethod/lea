"""Provider-neutral calendar action handlers."""

from collections.abc import Mapping
from datetime import UTC, date, datetime

from lea.actions import (
    ActionHandler,
    ActionHandlerFailure,
    ActionHandlerRegistry,
    ActionProposal,
)
from lea.calendars.attendees import CalendarAttendee
from lea.calendars.contracts import (
    CalendarCancelRequest,
    CalendarCollection,
    CalendarCreateRequest,
    CalendarEvent,
    CalendarEventQuery,
    CalendarEventTarget,
    CalendarEventTiming,
    CalendarListCalendarsResult,
    CalendarListEventsResult,
    CalendarModifyRequest,
    CalendarMutationResult,
    CalendarProviderIssue,
    CalendarShowEventResult,
)
from lea.calendars.provider import CalendarProvider
from lea.calendars.synchronization import CalendarSynchronizer


class CalendarActionHandlerError(ActionHandlerFailure):
    """Deterministic failure raised by a calendar action handler."""

    def __init__(self, *, code: str, message: str) -> None:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code must be non-empty.")

        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be non-empty.")

        super().__init__(code=code, message=message)


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


def create_calendar_event_action_handler(provider: CalendarProvider) -> ActionHandler:
    """Return a handler for one ``calendar.create`` proposal."""

    def handle(proposal: ActionProposal) -> Mapping[str, object]:
        parameters = _parameters(
            proposal,
            allowed={
                "calendar_id",
                "summary",
                "timing",
                "description",
                "location",
                "attendees",
            },
        )
        request = CalendarCreateRequest(
            calendar_id=_required_identifier(parameters, "calendar_id"),
            summary=_required_text(parameters, "summary"),
            timing=_required_timing(parameters, "timing"),
            description=_optional_text(parameters, "description"),
            location=_optional_text(parameters, "location"),
            attendees=_optional_attendees(parameters, "attendees") or (),
        )
        return _mutation_output(provider.create_event(request))

    return handle


def modify_calendar_event_action_handler(provider: CalendarProvider) -> ActionHandler:
    """Return a handler for one ``calendar.modify`` proposal."""

    def handle(proposal: ActionProposal) -> Mapping[str, object]:
        parameters = _parameters(
            proposal,
            allowed={
                "calendar_id",
                "event_uid",
                "summary",
                "timing",
                "description",
                "clear_description",
                "location",
                "clear_location",
                "target",
                "attendees",
                "clear_attendees",
            },
        )
        calendar_id = _required_identifier(parameters, "calendar_id")
        event_uid = _required_identifier(parameters, "event_uid")
        request = CalendarModifyRequest(
            calendar_id=calendar_id,
            event_uid=event_uid,
            summary=_optional_text(parameters, "summary"),
            timing=_optional_timing(parameters, "timing"),
            description=_optional_text(parameters, "description"),
            clear_description=_optional_boolean(parameters, "clear_description"),
            location=_optional_text(parameters, "location"),
            clear_location=_optional_boolean(parameters, "clear_location"),
            target=_optional_target(parameters, "target", calendar_id, event_uid),
            attendees=_optional_attendees(parameters, "attendees"),
            clear_attendees=_optional_boolean(parameters, "clear_attendees"),
        )
        return _mutation_output(provider.modify_event(request))

    return handle


def cancel_calendar_event_action_handler(provider: CalendarProvider) -> ActionHandler:
    """Return a handler for one ``calendar.cancel`` proposal."""

    def handle(proposal: ActionProposal) -> Mapping[str, object]:
        parameters = _parameters(
            proposal,
            allowed={"calendar_id", "event_uid", "target"},
        )
        calendar_id = _required_identifier(parameters, "calendar_id")
        event_uid = _required_identifier(parameters, "event_uid")
        request = CalendarCancelRequest(
            calendar_id=calendar_id,
            event_uid=event_uid,
            target=_optional_target(
                parameters,
                "target",
                calendar_id,
                event_uid,
            ),
        )
        return _mutation_output(provider.cancel_event(request))

    return handle


def synchronize_calendars_action_handler(
    synchronizer: CalendarSynchronizer,
) -> ActionHandler:
    """Return a handler for one explicit ``calendar.sync`` proposal."""

    def handle(proposal: ActionProposal) -> Mapping[str, object]:
        _parameters(proposal, allowed=set())
        result = synchronizer.synchronize()
        if not result.success:
            _raise_provider_failure(result.issues)
        return {"synchronized": True}

    return handle


def discover_calendars_action_handler(
    synchronizer: CalendarSynchronizer,
) -> ActionHandler:
    """Return a handler for one explicit ``calendar.discover`` proposal."""

    def handle(proposal: ActionProposal) -> Mapping[str, object]:
        _parameters(proposal, allowed=set())
        result = synchronizer.discover()
        if not result.success:
            _raise_provider_failure(result.issues)
        return {"discovered": True}

    return handle


def calendar_action_handler_registry(
    provider: CalendarProvider,
) -> ActionHandlerRegistry:
    """Return the canonical calendar action-handler registry."""
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
    registry.register("calendar.create", create_calendar_event_action_handler(provider))
    registry.register("calendar.modify", modify_calendar_event_action_handler(provider))
    registry.register("calendar.cancel", cancel_calendar_event_action_handler(provider))
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


def _optional_target(
    parameters: Mapping[str, object],
    field: str,
    calendar_id: str,
    event_uid: str,
) -> CalendarEventTarget | None:
    """Parse an optional explicit recurring target."""
    if field not in parameters:
        return None
    value = parameters[field]
    if not isinstance(value, Mapping):
        raise CalendarActionHandlerError(
            code="calendar_action_parameter_invalid",
            message="target must be an object.",
        )
    kind = value.get("kind")
    if not isinstance(kind, str):
        raise CalendarActionHandlerError(
            code="calendar_action_parameter_invalid",
            message="target.kind must be series or instance.",
        )
    recurrence_id = value.get("recurrence_id")
    parsed_id: date | datetime | None = None
    if recurrence_id is not None:
        if not isinstance(recurrence_id, str):
            raise CalendarActionHandlerError(
                code="calendar_action_parameter_invalid",
                message="target.recurrence_id must be an ISO date or datetime.",
            )
        try:
            parsed_id = datetime.fromisoformat(recurrence_id)
            if parsed_id.tzinfo is None:
                raise ValueError
            parsed_id = parsed_id.astimezone(UTC)
        except ValueError:
            try:
                parsed_id = date.fromisoformat(recurrence_id)
            except ValueError as error:
                raise CalendarActionHandlerError(
                    code="calendar_action_parameter_invalid",
                    message="target.recurrence_id must be canonical ISO text.",
                ) from error
    try:
        return CalendarEventTarget(calendar_id, event_uid, kind, parsed_id)
    except (TypeError, ValueError) as error:
        raise CalendarActionHandlerError(
            code="calendar_action_parameter_invalid",
            message="target is not a valid series or instance target.",
        ) from error


def _optional_attendees(
    parameters: Mapping[str, object],
    field: str,
) -> tuple[CalendarAttendee, ...] | None:
    """Parse one optional deterministic attendee collection."""
    if field not in parameters:
        return None
    value = parameters[field]
    if not isinstance(value, (list, tuple)):
        raise CalendarActionHandlerError(
            code="calendar_action_parameter_invalid",
            message="attendees must be an array.",
        )
    attendees: list[CalendarAttendee] = []
    for item in value:
        if not isinstance(item, Mapping) or not isinstance(item.get("address"), str):
            raise CalendarActionHandlerError(
                code="calendar_action_parameter_invalid",
                message="each attendee must contain an address.",
            )
        try:
            attendees.append(
                CalendarAttendee(
                    item["address"],
                    display_name=item.get("display_name")
                    if isinstance(item.get("display_name"), str)
                    else None,
                    role=item.get("role", "REQ-PARTICIPANT"),
                    response=item.get("response", "NEEDS-ACTION"),
                    rsvp=item.get("rsvp", False),
                )
            )
        except (TypeError, ValueError) as error:
            raise CalendarActionHandlerError(
                code="calendar_action_parameter_invalid",
                message="attendee is invalid.",
            ) from error
    return tuple(attendees)


def _required_text(parameters: Mapping[str, object], field: str) -> str:
    """Return one required non-empty text value."""
    value = parameters.get(field)
    if not isinstance(value, str) or not value.strip():
        raise CalendarActionHandlerError(
            code="calendar_action_parameter_invalid",
            message=f"{field} must be a non-empty string.",
        )
    return value


def _optional_text(parameters: Mapping[str, object], field: str) -> str | None:
    """Return one optional non-empty text value."""
    if field not in parameters:
        return None
    return _required_text(parameters, field)


def _required_timing(
    parameters: Mapping[str, object], field: str
) -> CalendarEventTiming:
    """Parse one explicit canonical all-day or timed interval."""
    value = parameters.get(field)
    if not isinstance(value, Mapping) or set(value) != {
        "start",
        "end",
        "all_day",
        "timezone",
    }:
        raise CalendarActionHandlerError(
            code="calendar_action_parameter_invalid",
            message=f"{field} must be a canonical calendar timing object.",
        )

    all_day = value.get("all_day")
    start = value.get("start")
    end = value.get("end")
    timezone = value.get("timezone")
    if (
        not isinstance(all_day, bool)
        or not isinstance(start, str)
        or not isinstance(end, str)
    ):
        raise CalendarActionHandlerError(
            code="calendar_action_parameter_invalid",
            message=f"{field} contains invalid temporal values.",
        )

    try:
        if all_day:
            if timezone is not None:
                raise ValueError
            parsed_start: date | datetime = date.fromisoformat(start)
            parsed_end: date | datetime = date.fromisoformat(end)
            if parsed_start.isoformat() != start or parsed_end.isoformat() != end:
                raise ValueError
        else:
            if not isinstance(timezone, str):
                raise ValueError
            parsed_start = datetime.fromisoformat(start)
            parsed_end = datetime.fromisoformat(end)
            if (
                parsed_start.tzinfo is None
                or parsed_end.tzinfo is None
                or parsed_start.utcoffset() != UTC.utcoffset(parsed_start)
                or parsed_end.utcoffset() != UTC.utcoffset(parsed_end)
                or parsed_start.isoformat() != start
                or parsed_end.isoformat() != end
            ):
                raise ValueError
        return CalendarEventTiming(parsed_start, parsed_end, timezone)
    except (TypeError, ValueError) as error:
        raise CalendarActionHandlerError(
            code="calendar_action_parameter_invalid",
            message=f"{field} must contain a valid canonical interval.",
        ) from error


def _optional_timing(
    parameters: Mapping[str, object], field: str
) -> CalendarEventTiming | None:
    """Parse one optional canonical event interval."""
    if field not in parameters:
        return None
    return _required_timing(parameters, field)


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


def _mutation_output(result: CalendarMutationResult) -> Mapping[str, object]:
    """Map one provider mutation result to action output."""
    if not result.success:
        _raise_provider_failure(result.issues)
    if result.event is None:
        raise CalendarActionHandlerError(
            code="calendar_action_result_invalid",
            message="Successful calendar mutation returned no event.",
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
