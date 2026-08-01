"""Public khal CLI adapter interfaces."""

from lea.adapters.khal.contracts import (
    KhalCalendarItemParseResult,
    KhalCommandResult,
    KhalConfig,
    KhalRunResult,
)
from lea.adapters.khal.events import (
    list_khal_calendar_events,
    show_khal_calendar_event,
)
from lea.adapters.khal.factory import (
    KhalCalendarProviderBuildResult,
    KhalCalendarProviderFactoryConfig,
    build_khal_calendar_provider,
)
from lea.adapters.khal.icalendar_parser import (
    KHAL_MAX_ICALENDAR_ITEM_BYTES,
    parse_khal_calendar_item,
    read_khal_calendar_item,
)
from lea.adapters.khal.inspection import inspect_khal
from lea.adapters.khal.provider import KhalCalendarProvider
from lea.adapters.khal.runner import KhalRunner
from lea.adapters.khal.vdirs import (
    KHAL_MAX_DISPLAY_NAME_BYTES,
    discover_khal_calendar_collections,
)

__all__ = [
    "KHAL_MAX_DISPLAY_NAME_BYTES",
    "KHAL_MAX_ICALENDAR_ITEM_BYTES",
    "KhalCalendarItemParseResult",
    "KhalCalendarProvider",
    "KhalCalendarProviderBuildResult",
    "KhalCalendarProviderFactoryConfig",
    "KhalCommandResult",
    "KhalConfig",
    "KhalRunResult",
    "KhalRunner",
    "build_khal_calendar_provider",
    "discover_khal_calendar_collections",
    "inspect_khal",
    "list_khal_calendar_events",
    "parse_khal_calendar_item",
    "read_khal_calendar_item",
    "show_khal_calendar_event",
]
