"""Safe local-vdir calendar event mutations."""

from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from importlib import import_module
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from lea.adapters.khal.contracts import KhalConfig
from lea.adapters.khal.icalendar_parser import read_khal_calendar_item
from lea.adapters.khal.vdirs import discover_khal_calendar_collections
from lea.calendars import (
    CalendarCreateRequest,
    CalendarMutationResult,
    CalendarProviderIssue,
)

CalendarUidFactory = Callable[[], str]
_PROVIDER = "khal"
_OPERATION = "create_event"


def create_khal_calendar_event(
    config: KhalConfig,
    request: CalendarCreateRequest,
    *,
    uid_factory: CalendarUidFactory | None = None,
) -> CalendarMutationResult:
    """Atomically create one vdir item and return strict canonical read-back."""
    if not isinstance(config, KhalConfig):
        raise TypeError("config must be a KhalConfig value.")
    if not isinstance(request, CalendarCreateRequest):
        raise TypeError("request must be a CalendarCreateRequest value.")

    collections = discover_khal_calendar_collections(config)
    if not collections.success:
        return _failure_from_issues(collections.issues)
    if request.calendar_id not in {
        collection.calendar_id for collection in collections.calendars
    }:
        return _failure(
            code="khal_calendar_not_found",
            message=(
                "The requested calendar was not present below the "
                "configured vdirs root."
            ),
            calendar_id=request.calendar_id,
            field="calendar_id",
        )

    factory = uid_factory or _new_uid
    try:
        event_uid = factory()
    except Exception:
        return _failure(
            code="khal_calendar_uid_generation_failed",
            message="A stable event identifier could not be generated.",
            calendar_id=request.calendar_id,
            field="event_uid",
        )
    if not _valid_uid(event_uid):
        return _failure(
            code="khal_calendar_uid_generation_failed",
            message="The generated event identifier was invalid.",
            calendar_id=request.calendar_id,
            field="event_uid",
        )

    collection = config.vdirs_directory / request.calendar_id
    destination = collection / f"{event_uid}.ics"
    temporary: Path | None = None
    try:
        document = _render_event(request, event_uid=event_uid)
        with NamedTemporaryFile(
            mode="wb",
            prefix=".lea-create-",
            suffix=".tmp",
            dir=collection,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            stream.write(document)
            stream.flush()
            os.fsync(stream.fileno())

        os.link(temporary, destination)
        temporary.unlink()
        temporary = None
        _fsync_directory(collection)
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return _failure(
            code="khal_calendar_event_create_failed",
            message="The local calendar event could not be created atomically.",
            calendar_id=request.calendar_id,
            event_uid=event_uid,
        )
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)

    parsed = read_khal_calendar_item(destination, calendar_id=request.calendar_id)
    if not parsed.success or parsed.event is None:
        with suppress(OSError):
            destination.unlink(missing_ok=True)
        return _failure(
            code="khal_calendar_event_readback_failed",
            message="The created calendar event failed canonical read-back validation.",
            calendar_id=request.calendar_id,
            event_uid=event_uid,
        )

    return CalendarMutationResult(success=True, event=parsed.event, issues=())


def _render_event(request: CalendarCreateRequest, *, event_uid: str) -> bytes:
    """Render one standards-compliant single-event iCalendar document."""
    module = import_module("icalendar")
    calendar: Any = vars(module)["Calendar"]()
    component: Any = vars(module)["Event"]()
    calendar.add("prodid", "-//LEA//Local calendar provider//EN")
    calendar.add("version", "2.0")
    component.add("uid", event_uid)
    component.add("summary", request.summary)

    start = request.timing.start
    end = request.timing.end
    if isinstance(start, datetime):
        assert isinstance(end, datetime)
        zone = ZoneInfo(request.timing.timezone or "UTC")
        component.add("dtstart", start.astimezone(zone))
        component.add("dtend", end.astimezone(zone))
    else:
        component.add("dtstart", start)
        component.add("dtend", end)
    if request.description is not None:
        component.add("description", request.description)
    if request.location is not None:
        component.add("location", request.location)
    calendar.add_component(component)
    document = calendar.to_ical()
    if not isinstance(document, bytes):
        raise TypeError("iCalendar rendering did not return bytes.")
    return document


def _new_uid() -> str:
    return f"{uuid4()}@lea.local"


def _valid_uid(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and "/" not in value
        and "\\" not in value
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _failure_from_issues(
    issues: tuple[CalendarProviderIssue, ...],
) -> CalendarMutationResult:
    return CalendarMutationResult(
        success=False,
        event=None,
        issues=tuple(
            CalendarProviderIssue(
                code=issue.code,
                message=issue.message,
                provider=issue.provider,
                operation=_OPERATION,
                calendar_id=issue.calendar_id,
                event_uid=issue.event_uid,
                field=issue.field,
                return_code=issue.return_code,
            )
            for issue in issues
        ),
    )


def _failure(
    *,
    code: str,
    message: str,
    calendar_id: str,
    event_uid: str | None = None,
    field: str | None = None,
) -> CalendarMutationResult:
    return CalendarMutationResult(
        success=False,
        event=None,
        issues=(
            CalendarProviderIssue(
                code=code,
                message=message,
                provider=_PROVIDER,
                operation=_OPERATION,
                calendar_id=calendar_id,
                event_uid=event_uid,
                field=field,
            ),
        ),
    )
