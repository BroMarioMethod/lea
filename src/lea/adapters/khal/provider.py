"""Provider-neutral calendar access through khal and local vdirs."""

from lea.adapters.khal.contracts import KhalConfig
from lea.adapters.khal.events import (
    list_khal_calendar_events,
    show_khal_calendar_event,
)
from lea.adapters.khal.inspection import inspect_khal
from lea.adapters.khal.mutations import (
    cancel_khal_calendar_event,
    create_khal_calendar_event,
    modify_khal_calendar_event,
)
from lea.adapters.khal.runner import KhalRunner
from lea.adapters.khal.vdirs import discover_khal_calendar_collections
from lea.calendars import (
    CalendarCancelRequest,
    CalendarCreateRequest,
    CalendarEventQuery,
    CalendarListCalendarsResult,
    CalendarListEventsResult,
    CalendarModifyRequest,
    CalendarMutationResult,
    CalendarProviderInspectionResult,
    CalendarProviderIssue,
    CalendarShowEventResult,
)

_PROVIDER = "khal"
_UNSUPPORTED_CODE = "khal_operation_unsupported"


class KhalCalendarProvider:
    """Assemble deterministic read-only khal calendar operations."""

    def __init__(
        self,
        config: KhalConfig,
        *,
        runner: KhalRunner | None = None,
    ) -> None:
        """Configure one explicit isolated khal calendar provider."""
        if not isinstance(config, KhalConfig):
            raise TypeError("config must be a KhalConfig value.")

        if runner is not None and runner.config != config:
            raise ValueError("runner configuration must match config.")

        self._config = config
        self._runner = runner if runner is not None else KhalRunner(config)

    @property
    def config(self) -> KhalConfig:
        """Return the immutable provider configuration."""
        return self._config

    def inspect(self) -> CalendarProviderInspectionResult:
        """Inspect provider availability and compatibility."""
        return inspect_khal(
            self._config,
            runner=self._runner,
        )

    def list_calendars(self) -> CalendarListCalendarsResult:
        """List deterministic local vdir calendar collections."""
        return discover_khal_calendar_collections(self._config)

    def list_events(
        self,
        query: CalendarEventQuery,
    ) -> CalendarListEventsResult:
        """List events matching one supported local-date query."""
        return list_khal_calendar_events(
            self._config,
            query,
        )

    def show_event(
        self,
        calendar_id: str,
        event_uid: str,
    ) -> CalendarShowEventResult:
        """Read one exact event by composite stable identity."""
        return show_khal_calendar_event(
            self._config,
            calendar_id,
            event_uid,
        )

    def create_event(
        self,
        request: CalendarCreateRequest,
    ) -> CalendarMutationResult:
        """Create one event through an atomic local-vdir mutation."""
        if not isinstance(request, CalendarCreateRequest):
            raise TypeError("request must be a CalendarCreateRequest value.")

        return create_khal_calendar_event(self._config, request)

    def modify_event(
        self,
        request: CalendarModifyRequest,
    ) -> CalendarMutationResult:
        """Modify one exact event through an atomic local-vdir mutation."""
        if not isinstance(request, CalendarModifyRequest):
            raise TypeError("request must be a CalendarModifyRequest value.")

        return modify_khal_calendar_event(self._config, request)

    def cancel_event(
        self,
        request: CalendarCancelRequest,
    ) -> CalendarMutationResult:
        """Mark one exact local event as cancelled."""
        if not isinstance(request, CalendarCancelRequest):
            raise TypeError("request must be a CalendarCancelRequest value.")

        return cancel_khal_calendar_event(self._config, request)


def _unsupported_mutation(
    *,
    operation: str,
    message: str,
    calendar_id: str,
    event_uid: str | None,
) -> CalendarMutationResult:
    """Construct one explicit unsupported-operation mutation result."""
    return CalendarMutationResult(
        success=False,
        event=None,
        issues=(
            CalendarProviderIssue(
                code=_UNSUPPORTED_CODE,
                message=message,
                provider=_PROVIDER,
                operation=operation,
                calendar_id=calendar_id,
                event_uid=event_uid,
            ),
        ),
    )
