"""Deterministic builders for calendar action proposals."""

from collections.abc import Mapping
from datetime import UTC, datetime

from lea.actions import (
    ActionProposal,
    ConfirmationPolicy,
    RiskLevel,
)
from lea.calendars.contracts import (
    CalendarCancelRequest,
    CalendarCreateRequest,
    CalendarEventQuery,
    CalendarEventTiming,
    CalendarModifyRequest,
)


def build_calendar_list_calendars_proposal(
    *,
    proposal_id: str,
    source: str,
    created_at: datetime,
) -> ActionProposal:
    """Build one low-risk proposal to list available calendars."""
    return _proposal(
        action="calendar.list_calendars",
        parameters={},
        proposal_id=proposal_id,
        source=source,
        created_at=created_at,
        reason="List available calendars.",
    )


def build_calendar_list_events_proposal(
    query: CalendarEventQuery,
    *,
    proposal_id: str,
    source: str,
    created_at: datetime,
) -> ActionProposal:
    """Build one low-risk proposal to list events in a local-date range."""
    if not isinstance(query, CalendarEventQuery):
        raise TypeError("query must be a CalendarEventQuery value.")

    parameters: dict[str, object] = {
        "start_date": query.start_date.isoformat(),
        "end_date": query.end_date.isoformat(),
    }

    if query.calendar_ids:
        parameters["calendar_ids"] = list(query.calendar_ids)

    if query.include_cancelled:
        parameters["include_cancelled"] = True

    return _proposal(
        action="calendar.list_events",
        parameters=parameters,
        proposal_id=proposal_id,
        source=source,
        created_at=created_at,
        reason="List calendar events.",
    )


def build_calendar_show_event_proposal(
    calendar_id: str,
    event_uid: str,
    *,
    proposal_id: str,
    source: str,
    created_at: datetime,
) -> ActionProposal:
    """Build one low-risk proposal to read an exact calendar event."""
    return _proposal(
        action="calendar.show_event",
        parameters={
            "calendar_id": _identifier(
                calendar_id,
                field_name="calendar_id",
            ),
            "event_uid": _identifier(
                event_uid,
                field_name="event_uid",
            ),
        },
        proposal_id=proposal_id,
        source=source,
        created_at=created_at,
        reason="Show one exact calendar event.",
    )


def build_calendar_create_event_proposal(
    request: CalendarCreateRequest,
    *,
    proposal_id: str,
    source: str,
    created_at: datetime,
) -> ActionProposal:
    """Build one proposal to create a calendar event."""
    if not isinstance(request, CalendarCreateRequest):
        raise TypeError("request must be a CalendarCreateRequest value.")

    parameters: dict[str, object] = {
        "calendar_id": request.calendar_id,
        "summary": request.summary,
        "timing": _timing_parameters(request.timing),
    }
    if request.description is not None:
        parameters["description"] = request.description
    if request.location is not None:
        parameters["location"] = request.location

    return _proposal(
        action="calendar.create",
        parameters=parameters,
        proposal_id=proposal_id,
        source=source,
        created_at=created_at,
        reason="Create a calendar event.",
        risk_level=RiskLevel.LOW,
    )


def build_calendar_modify_event_proposal(
    request: CalendarModifyRequest,
    *,
    proposal_id: str,
    source: str,
    created_at: datetime,
) -> ActionProposal:
    """Build one medium-risk proposal to modify an exact calendar event."""
    if not isinstance(request, CalendarModifyRequest):
        raise TypeError("request must be a CalendarModifyRequest value.")

    parameters: dict[str, object] = {
        "calendar_id": request.calendar_id,
        "event_uid": request.event_uid,
    }
    if request.summary is not None:
        parameters["summary"] = request.summary
    if request.timing is not None:
        parameters["timing"] = _timing_parameters(request.timing)
    if request.description is not None:
        parameters["description"] = request.description
    if request.clear_description:
        parameters["clear_description"] = True
    if request.location is not None:
        parameters["location"] = request.location
    if request.clear_location:
        parameters["clear_location"] = True

    return _proposal(
        action="calendar.modify",
        parameters=parameters,
        proposal_id=proposal_id,
        source=source,
        created_at=created_at,
        reason="Modify one exact calendar event.",
        risk_level=RiskLevel.MEDIUM,
    )


def build_calendar_cancel_event_proposal(
    request: CalendarCancelRequest,
    *,
    proposal_id: str,
    source: str,
    created_at: datetime,
) -> ActionProposal:
    """Build one medium-risk proposal to cancel an exact calendar event."""
    if not isinstance(request, CalendarCancelRequest):
        raise TypeError("request must be a CalendarCancelRequest value.")

    return _proposal(
        action="calendar.cancel",
        parameters={
            "calendar_id": request.calendar_id,
            "event_uid": request.event_uid,
        },
        proposal_id=proposal_id,
        source=source,
        created_at=created_at,
        reason="Cancel one exact calendar event.",
        risk_level=RiskLevel.MEDIUM,
    )


def _proposal(
    *,
    action: str,
    parameters: Mapping[str, object],
    proposal_id: str,
    source: str,
    created_at: datetime,
    reason: str,
    risk_level: RiskLevel = RiskLevel.LOW,
) -> ActionProposal:
    """Construct one canonical proposed calendar action."""
    return ActionProposal(
        proposal_id=proposal_id,
        action=action,
        parameters=parameters,
        source=source,
        risk_level=risk_level,
        confirmation_policy=ConfirmationPolicy.WHEN_REQUIRED,
        created_at=_utc_timestamp(created_at),
        reason=reason,
    )


def _timing_parameters(timing: CalendarEventTiming) -> dict[str, object]:
    """Serialise one canonical event interval into proposal parameters."""
    return {
        "start": timing.start.isoformat(),
        "end": timing.end.isoformat(),
        "all_day": timing.all_day,
        "timezone": timing.timezone,
    }


def _utc_timestamp(value: datetime) -> datetime:
    """Require and return one timezone-aware canonical UTC timestamp."""
    if not isinstance(value, datetime):
        raise TypeError("created_at must be a datetime value.")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Calendar proposal timestamps must be timezone-aware.")

    if value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("Calendar proposal timestamps must use UTC.")

    return value.astimezone(UTC)


def _identifier(
    value: str,
    *,
    field_name: str,
) -> str:
    """Require one exact opaque provider identifier without normalisation."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")

    if value != value.strip():
        raise ValueError(
            f"{field_name} must not contain leading or trailing whitespace."
        )

    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field_name} must not contain control characters.")

    return value
