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
    CalendarCancelRequest,
    CalendarCreateRequest,
    CalendarEvent,
    CalendarModifyRequest,
    CalendarMutationResult,
    CalendarProviderIssue,
)

CalendarUidFactory = Callable[[], str]
_PROVIDER = "khal"
_OPERATION = "create_event"


_CALENDAR_ITEM_MODE = 0o640


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
            stream.write(document)
            stream.flush()
            os.fchmod(
                stream.fileno(),
                _CALENDAR_ITEM_MODE,
            )
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


def modify_khal_calendar_event(
    config: KhalConfig,
    request: CalendarModifyRequest,
) -> CalendarMutationResult:
    """Atomically modify one event selected by exact stable identity."""
    if not isinstance(config, KhalConfig):
        raise TypeError("config must be a KhalConfig value.")
    if not isinstance(request, CalendarModifyRequest):
        raise TypeError("request must be a CalendarModifyRequest value.")

    found = _find_event_item(config, request.calendar_id, request.event_uid)
    if isinstance(found, CalendarMutationResult):
        return found
    destination, existing = found
    updated = CalendarEvent(
        calendar_id=existing.calendar_id,
        event_uid=existing.event_uid,
        summary=request.summary if request.summary is not None else existing.summary,
        timing=request.timing if request.timing is not None else existing.timing,
        description=(
            None
            if request.clear_description
            else request.description
            if request.description is not None
            else existing.description
        ),
        location=(
            None
            if request.clear_location
            else request.location
            if request.location is not None
            else existing.location
        ),
        cancelled=existing.cancelled,
    )

    staged: Path | None = None
    try:
        original = destination.read_bytes()
        staged = _write_staged_document(
            destination.parent,
            _render_event_values(updated),
        )
        parsed = read_khal_calendar_item(staged, calendar_id=request.calendar_id)
        if not parsed.success or parsed.event != updated:
            return _failure(
                code="khal_calendar_event_readback_failed",
                message="The modified calendar event failed canonical validation.",
                calendar_id=request.calendar_id,
                event_uid=request.event_uid,
                operation="modify_event",
            )
        os.replace(staged, destination)
        staged = None
        _fsync_directory(destination.parent)
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return _failure(
            code="khal_calendar_event_modify_failed",
            message="The local calendar event could not be replaced atomically.",
            calendar_id=request.calendar_id,
            event_uid=request.event_uid,
            operation="modify_event",
        )
    finally:
        if staged is not None:
            with suppress(OSError):
                staged.unlink(missing_ok=True)

    readback = read_khal_calendar_item(destination, calendar_id=request.calendar_id)
    if not readback.success or readback.event != updated:
        with suppress(OSError):
            replacement = _write_staged_document(destination.parent, original)
            os.replace(replacement, destination)
            _fsync_directory(destination.parent)
        return _failure(
            code="khal_calendar_event_readback_failed",
            message=(
                "The modified calendar event failed canonical read-back validation."
            ),
            calendar_id=request.calendar_id,
            event_uid=request.event_uid,
            operation="modify_event",
        )
    return CalendarMutationResult(success=True, event=readback.event, issues=())


def cancel_khal_calendar_event(
    config: KhalConfig,
    request: CalendarCancelRequest,
) -> CalendarMutationResult:
    """Atomically mark one exact local event as cancelled."""
    if not isinstance(config, KhalConfig):
        raise TypeError("config must be a KhalConfig value.")
    if not isinstance(request, CalendarCancelRequest):
        raise TypeError("request must be a CalendarCancelRequest value.")

    found = _find_event_item(
        config,
        request.calendar_id,
        request.event_uid,
        operation="cancel_event",
    )
    if isinstance(found, CalendarMutationResult):
        return found
    destination, existing = found
    cancelled = CalendarEvent(
        calendar_id=existing.calendar_id,
        event_uid=existing.event_uid,
        summary=existing.summary,
        timing=existing.timing,
        description=existing.description,
        location=existing.location,
        cancelled=True,
    )
    if existing.cancelled:
        return CalendarMutationResult(success=True, event=existing, issues=())

    staged: Path | None = None
    try:
        original = destination.read_bytes()
        staged = _write_staged_document(
            destination.parent,
            _render_event_values(cancelled),
        )
        parsed = read_khal_calendar_item(staged, calendar_id=request.calendar_id)
        if not parsed.success or parsed.event != cancelled:
            return _failure(
                code="khal_calendar_event_readback_failed",
                message="The cancelled event failed canonical validation.",
                calendar_id=request.calendar_id,
                event_uid=request.event_uid,
                operation="cancel_event",
            )
        os.replace(staged, destination)
        staged = None
        _fsync_directory(destination.parent)
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return _failure(
            code="khal_calendar_event_cancel_failed",
            message="The local calendar event could not be cancelled atomically.",
            calendar_id=request.calendar_id,
            event_uid=request.event_uid,
            operation="cancel_event",
        )
    finally:
        if staged is not None:
            with suppress(OSError):
                staged.unlink(missing_ok=True)

    readback = read_khal_calendar_item(destination, calendar_id=request.calendar_id)
    if not readback.success or readback.event != cancelled:
        with suppress(OSError):
            replacement = _write_staged_document(destination.parent, original)
            os.replace(replacement, destination)
            _fsync_directory(destination.parent)
        return _failure(
            code="khal_calendar_event_readback_failed",
            message="The cancelled event failed canonical read-back validation.",
            calendar_id=request.calendar_id,
            event_uid=request.event_uid,
            operation="cancel_event",
        )
    return CalendarMutationResult(success=True, event=readback.event, issues=())


def _find_event_item(
    config: KhalConfig,
    calendar_id: str,
    event_uid: str,
    *,
    operation: str = "modify_event",
) -> tuple[Path, CalendarEvent] | CalendarMutationResult:
    """Resolve exactly one safe vdir item by stable composite identity."""
    collections = discover_khal_calendar_collections(config)
    if not collections.success:
        return _failure_from_issues(collections.issues, operation=operation)
    if calendar_id not in {item.calendar_id for item in collections.calendars}:
        return _failure(
            code="khal_calendar_not_found",
            message="The requested calendar was not found.",
            calendar_id=calendar_id,
            event_uid=event_uid,
            field="calendar_id",
            operation=operation,
        )

    collection = config.vdirs_directory / calendar_id
    try:
        paths = tuple(
            sorted(
                (
                    path
                    for path in collection.iterdir()
                    if not path.name.startswith(".") and path.suffix.lower() == ".ics"
                ),
                key=lambda path: path.name,
            )
        )
    except OSError:
        return _failure(
            code="khal_calendar_collection_unreadable",
            message="The selected calendar collection could not be enumerated.",
            calendar_id=calendar_id,
            event_uid=event_uid,
            operation=operation,
        )

    matches: list[tuple[Path, CalendarEvent]] = []
    for path in paths:
        parsed = read_khal_calendar_item(path, calendar_id=calendar_id)
        if not parsed.success:
            return _failure_from_issues(parsed.issues, operation=operation)
        if parsed.event is not None and parsed.event.event_uid == event_uid:
            matches.append((path, parsed.event))
    if not matches:
        return _failure(
            code="khal_calendar_event_not_found",
            message=(
                "No event matched the requested stable calendar and event identity."
            ),
            calendar_id=calendar_id,
            event_uid=event_uid,
            field="event_uid",
            operation=operation,
        )
    if len(matches) != 1:
        return _failure(
            code="khal_calendar_event_identity_duplicate",
            message="Multiple local vdir items claimed the requested event identity.",
            calendar_id=calendar_id,
            event_uid=event_uid,
            field="event_uid",
            operation=operation,
        )
    return matches[0]


def _write_staged_document(directory: Path, document: bytes) -> Path:
    """Write and sync one private replacement beside its destination."""
    with NamedTemporaryFile(
        mode="wb",
        prefix=".lea-modify-",
        suffix=".ics",
        dir=directory,
        delete=False,
    ) as stream:
        path = Path(stream.name)
        stream.write(document)
        stream.flush()
        os.fchmod(
            stream.fileno(),
            _CALENDAR_ITEM_MODE,
        )
        os.fsync(stream.fileno())
    return path


def _render_event(request: CalendarCreateRequest, *, event_uid: str) -> bytes:
    """Render one standards-compliant single-event iCalendar document."""
    return _render_event_values(
        CalendarEvent(
            calendar_id=request.calendar_id,
            event_uid=event_uid,
            summary=request.summary,
            timing=request.timing,
            description=request.description,
            location=request.location,
        )
    )


def _render_event_values(event: CalendarEvent) -> bytes:
    """Render one canonical event projection as iCalendar."""
    module = import_module("icalendar")
    calendar: Any = vars(module)["Calendar"]()
    component: Any = vars(module)["Event"]()
    calendar.add("prodid", "-//LEA//Local calendar provider//EN")
    calendar.add("version", "2.0")
    component.add("uid", event.event_uid)
    component.add("summary", event.summary)

    start = event.timing.start
    end = event.timing.end
    if isinstance(start, datetime):
        assert isinstance(end, datetime)
        zone = ZoneInfo(event.timing.timezone or "UTC")
        component.add("dtstart", start.astimezone(zone))
        component.add("dtend", end.astimezone(zone))
    else:
        component.add("dtstart", start)
        component.add("dtend", end)
    if event.description is not None:
        component.add("description", event.description)
    if event.location is not None:
        component.add("location", event.location)
    if event.cancelled:
        component.add("status", "CANCELLED")
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
    *,
    operation: str = _OPERATION,
) -> CalendarMutationResult:
    return CalendarMutationResult(
        success=False,
        event=None,
        issues=tuple(
            CalendarProviderIssue(
                code=issue.code,
                message=issue.message,
                provider=issue.provider,
                operation=operation,
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
    operation: str = _OPERATION,
) -> CalendarMutationResult:
    return CalendarMutationResult(
        success=False,
        event=None,
        issues=(
            CalendarProviderIssue(
                code=code,
                message=message,
                provider=_PROVIDER,
                operation=operation,
                calendar_id=calendar_id,
                event_uid=event_uid,
                field=field,
            ),
        ),
    )
