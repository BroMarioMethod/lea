"""Public provider-neutral calendar interfaces."""

from lea.calendars.action_handlers import (
    CalendarActionHandlerError,
    calendar_action_handler_registry,
    list_calendar_events_action_handler,
    list_calendars_action_handler,
    show_calendar_event_action_handler,
)
from lea.calendars.contracts import (
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
from lea.calendars.proposal_builders import (
    build_calendar_list_calendars_proposal,
    build_calendar_list_events_proposal,
    build_calendar_show_event_proposal,
)
from lea.calendars.provider import CalendarProvider

__all__ = [
    "CalendarActionHandlerError",
    "CalendarCancelRequest",
    "CalendarCollection",
    "CalendarCreateRequest",
    "CalendarEvent",
    "CalendarEventQuery",
    "CalendarEventTiming",
    "CalendarListCalendarsResult",
    "CalendarListEventsResult",
    "CalendarModifyRequest",
    "CalendarMutationResult",
    "CalendarProvider",
    "CalendarProviderInspectionResult",
    "CalendarProviderIssue",
    "CalendarShowEventResult",
    "build_calendar_list_calendars_proposal",
    "build_calendar_list_events_proposal",
    "build_calendar_show_event_proposal",
    "calendar_action_handler_registry",
    "list_calendar_events_action_handler",
    "list_calendars_action_handler",
    "show_calendar_event_action_handler",
]
