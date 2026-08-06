"""Provider-neutral calendar execution interface."""

from typing import Protocol, runtime_checkable

from lea.calendars.contracts import (
    CalendarCancelRequest,
    CalendarCreateRequest,
    CalendarEventQuery,
    CalendarListCalendarsResult,
    CalendarListEventsResult,
    CalendarModifyRequest,
    CalendarMutationResult,
    CalendarProviderInspectionResult,
    CalendarShowEventResult,
)


@runtime_checkable
class CalendarProvider(Protocol):
    """Interface implemented by deterministic calendar providers."""

    def inspect(self) -> CalendarProviderInspectionResult:
        """Inspect provider availability and compatibility."""
        ...

    def list_calendars(self) -> CalendarListCalendarsResult:
        """List calendar collections permitted by provider policy."""
        ...

    def list_events(
        self,
        query: CalendarEventQuery,
    ) -> CalendarListEventsResult:
        """List events matching one supported date-range query."""
        ...

    def show_event(
        self,
        calendar_id: str,
        event_uid: str,
    ) -> CalendarShowEventResult:
        """Read one exact event by stable calendar and event identity."""
        ...

    def create_event(
        self,
        request: CalendarCreateRequest,
    ) -> CalendarMutationResult:
        """Create one event and return canonical provider state."""
        ...

    def modify_event(
        self,
        request: CalendarModifyRequest,
    ) -> CalendarMutationResult:
        """Modify one exact event and return canonical provider state."""
        ...

    def cancel_event(
        self,
        request: CalendarCancelRequest,
    ) -> CalendarMutationResult:
        """Cancel one exact event and return canonical provider state."""
        ...
