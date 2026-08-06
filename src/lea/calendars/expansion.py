"""Deterministic recurrence expansion with explicit timezone semantics."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import cast
from zoneinfo import ZoneInfo

from lea.calendars.contracts import CalendarEvent
from lea.calendars.recurrence import CalendarRecurrence


@dataclass(frozen=True, slots=True)
class CalendarEventOccurrence:
    """One generated occurrence retaining its source event identity."""

    calendar_id: str
    event_uid: str
    occurrence_start: date | datetime
    occurrence_end: date | datetime
    ordinal: int

    def __post_init__(self) -> None:
        if not isinstance(self.calendar_id, str) or not self.calendar_id:
            raise ValueError("calendar_id must be non-empty.")
        if not isinstance(self.event_uid, str) or not self.event_uid:
            raise ValueError("event_uid must be non-empty.")
        if type(self.occurrence_start) is not type(self.occurrence_end):
            raise ValueError("occurrence bounds must use the same temporal type.")
        if self.occurrence_end <= self.occurrence_start:
            raise ValueError("occurrence_end must be later than occurrence_start.")
        if isinstance(self.occurrence_start, datetime) and (
            self.occurrence_start.tzinfo is None
            or cast(datetime, self.occurrence_end).tzinfo is None
        ):
            raise ValueError("timed occurrences must be timezone-aware.")
        if isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise ValueError("ordinal must be a non-negative integer.")


def expand_calendar_event(
    event: CalendarEvent,
    *,
    range_start: date,
    range_end: date,
    maximum_occurrences: int = 10_000,
) -> tuple[CalendarEventOccurrence, ...]:
    """Expand one event into a half-open local-date range deterministically."""
    if not isinstance(event, CalendarEvent):
        raise TypeError("event must be a CalendarEvent value.")
    if type(range_start) is not date or type(range_end) is not date:
        raise TypeError("range bounds must be date values.")
    if range_end <= range_start:
        raise ValueError("range_end must be later than range_start.")
    if isinstance(maximum_occurrences, bool) or maximum_occurrences < 1:
        raise ValueError("maximum_occurrences must be positive.")

    if event.recurrence is None:
        candidates: tuple[tuple[date | datetime, date | datetime], ...] = (
            (event.timing.start, event.timing.end),
        )
    elif event.timing.all_day:
        candidates = _expand_all_day(
            event.timing.start,
            event.timing.end,
            event.recurrence,
            range_end,
            maximum_occurrences,
        )
    else:
        candidates = _expand_timed(
            event.timing.start,
            event.timing.end,
            event.timing.timezone,
            event.recurrence,
            range_end,
            maximum_occurrences,
        )

    result: list[CalendarEventOccurrence] = []
    for ordinal, (start, end) in enumerate(candidates):
        local_start = (
            start
            if isinstance(start, date) and not isinstance(start, datetime)
            else start.astimezone(ZoneInfo(event.timing.timezone or "UTC")).date()
        )
        local_end = (
            end
            if isinstance(end, date) and not isinstance(end, datetime)
            else end.astimezone(ZoneInfo(event.timing.timezone or "UTC")).date()
        )
        if local_end < range_start or local_start >= range_end:
            continue
        result.append(
            CalendarEventOccurrence(
                event.calendar_id,
                event.event_uid,
                start,
                end,
                ordinal,
            )
        )
    return tuple(result)


def _expand_all_day(
    start: date | datetime,
    end: date | datetime,
    recurrence: CalendarRecurrence,
    range_end: date,
    maximum: int,
) -> tuple[tuple[date, date], ...]:
    assert type(start) is date and type(end) is date
    duration = end - start
    values: list[tuple[date, date]] = []
    for occurrence_start in _candidate_dates(start, recurrence, range_end, maximum):
        values.append((occurrence_start, occurrence_start + duration))
    return tuple(values)


def _expand_timed(
    start: date | datetime,
    end: date | datetime,
    timezone: str | None,
    recurrence: CalendarRecurrence,
    range_end: date,
    maximum: int,
) -> tuple[tuple[datetime, datetime], ...]:
    assert isinstance(start, datetime) and isinstance(end, datetime)
    zone = ZoneInfo(timezone or "UTC")
    local_start = start.astimezone(zone)
    local_end = end.astimezone(zone)
    duration = local_end - local_start
    values: list[tuple[datetime, datetime]] = []
    for occurrence_date in _candidate_dates(
        local_start.date(), recurrence, range_end, maximum
    ):
        local_occurrence = local_start.replace(
            year=occurrence_date.year,
            month=occurrence_date.month,
            day=occurrence_date.day,
        )
        values.append(
            (
                local_occurrence.astimezone(UTC),
                (local_occurrence + duration).astimezone(UTC),
            )
        )
    return tuple(values)


def _candidate_dates(
    start: date,
    recurrence: CalendarRecurrence,
    range_end: date,
    maximum: int,
) -> tuple[date, ...]:
    weekdays = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
    values: list[date] = []
    cursor = start
    periods = 0
    while cursor < range_end and len(values) < maximum:
        period_dates: list[date]
        if recurrence.frequency == "DAILY":
            period_dates = [cursor]
            next_cursor = cursor + timedelta(days=recurrence.interval)
        elif recurrence.frequency == "WEEKLY":
            week_start = cursor - timedelta(days=cursor.weekday())
            selected = tuple(weekdays[day] for day in recurrence.by_day) or (
                start.weekday(),
            )
            period_dates = [
                week_start + timedelta(days=day) for day in sorted(selected)
            ]
            next_cursor = week_start + timedelta(weeks=recurrence.interval)
        elif recurrence.frequency == "MONTHLY":
            period_dates = _monthly_dates(
                cursor.year, cursor.month, start.day, recurrence
            )
            next_cursor = _add_months(cursor.replace(day=1), recurrence.interval)
        else:
            period_dates = _yearly_dates(cursor.year, start, recurrence)
            next_cursor = cursor.replace(
                year=cursor.year + recurrence.interval, month=1, day=1
            )

        for candidate in sorted(period_dates):
            if candidate < start or candidate >= range_end or candidate in values:
                continue
            if recurrence.until is not None:
                until_date = (
                    recurrence.until.date()
                    if isinstance(recurrence.until, datetime)
                    else recurrence.until
                )
                if candidate > until_date:
                    continue
            values.append(candidate)
            if recurrence.count is not None and len(values) >= recurrence.count:
                return tuple(values)
            if len(values) >= maximum:
                return tuple(values)
        cursor = next_cursor
        periods += 1
        if periods > maximum * 4:
            break
    return tuple(values)


def _monthly_dates(
    year: int, month: int, original_day: int, recurrence: CalendarRecurrence
) -> list[date]:
    _, last_day = calendar.monthrange(year, month)
    days = recurrence.by_month_day or (original_day,)
    return [
        date(year, month, day if day > 0 else last_day + day + 1)
        for day in days
        if 1 <= (day if day > 0 else last_day + day + 1) <= last_day
    ]


def _yearly_dates(year: int, start: date, recurrence: CalendarRecurrence) -> list[date]:
    month_days = recurrence.by_month_day or (start.day,)
    return [
        date(year, start.month, day)
        for day in month_days
        if 1 <= day <= calendar.monthrange(year, start.month)[1]
    ]


def _add_months(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)
