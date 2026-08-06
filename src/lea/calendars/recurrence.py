"""Strict provider-neutral recurrence contracts and RRULE mapping."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import ClassVar

_FREQUENCIES = {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}
_WEEKDAYS = {"MO", "TU", "WE", "TH", "FR", "SA", "SU"}


@dataclass(frozen=True, slots=True)
class CalendarRecurrence:
    """A bounded, canonical subset of iCalendar RRULE semantics."""

    frequency: str
    interval: int = 1
    count: int | None = None
    until: date | datetime | None = None
    by_day: tuple[str, ...] = ()
    by_month_day: tuple[int, ...] = ()

    _UNTIL_FORMAT: ClassVar[str] = "%Y%m%dT%H%M%SZ"

    def __post_init__(self) -> None:
        frequency = self.frequency.upper()
        if frequency not in _FREQUENCIES:
            raise ValueError("frequency must be DAILY, WEEKLY, MONTHLY or YEARLY.")
        object.__setattr__(self, "frequency", frequency)
        if isinstance(self.interval, bool) or not isinstance(self.interval, int):
            raise TypeError("interval must be an integer.")
        if self.interval < 1:
            raise ValueError("interval must be positive.")
        if self.count is not None:
            if isinstance(self.count, bool) or not isinstance(self.count, int):
                raise TypeError("count must be an integer or None.")
            if self.count < 1:
                raise ValueError("count must be positive.")
        if self.count is not None and self.until is not None:
            raise ValueError("count and until must not be supplied together.")
        if self.until is not None and not isinstance(self.until, (date, datetime)):
            raise TypeError("until must be a date, datetime or None.")
        days = tuple(day.upper() for day in self.by_day)
        if len(set(days)) != len(days) or any(day not in _WEEKDAYS for day in days):
            raise ValueError("by_day must contain unique ISO weekday codes.")
        object.__setattr__(self, "by_day", tuple(sorted(days)))
        month_days = tuple(self.by_month_day)
        if len(set(month_days)) != len(month_days):
            raise ValueError("by_month_day must contain unique values.")
        if any(
            isinstance(day, bool)
            or not isinstance(day, int)
            or day == 0
            or day < -31
            or day > 31
            for day in month_days
        ):
            raise ValueError(
                "by_month_day values must be between -31 and 31, excluding zero."
            )
        object.__setattr__(self, "by_month_day", tuple(sorted(month_days)))

    def to_rrule(self) -> str:
        """Render a deterministic RFC 5545 RRULE value."""
        fields = [f"FREQ={self.frequency}"]
        if self.interval != 1:
            fields.append(f"INTERVAL={self.interval}")
        if self.count is not None:
            fields.append(f"COUNT={self.count}")
        elif self.until is not None:
            if isinstance(self.until, datetime):
                if self.until.tzinfo is None or self.until.utcoffset() is None:
                    raise ValueError("datetime until must be timezone-aware.")
                value = self.until.astimezone(UTC).strftime(self._UNTIL_FORMAT)
            else:
                value = self.until.strftime("%Y%m%d")
            fields.append(f"UNTIL={value}")
        if self.by_day:
            fields.append(f"BYDAY={','.join(self.by_day)}")
        if self.by_month_day:
            fields.append(f"BYMONTHDAY={','.join(map(str, self.by_month_day))}")
        return ";".join(fields)

    @classmethod
    def from_rrule(cls, value: str) -> CalendarRecurrence:
        """Parse one strict RRULE value and reject unsupported fields."""
        if not isinstance(value, str) or not value.strip():
            raise ValueError("RRULE must be non-empty text.")
        fields: dict[str, str] = {}
        for item in value.split(";"):
            key, separator, raw = item.partition("=")
            key = key.upper().strip()
            if not separator or not key or not raw or key in fields:
                raise ValueError("RRULE contains an invalid or duplicate field.")
            fields[key] = raw.strip().upper()
        unsupported = set(fields) - {
            "FREQ",
            "INTERVAL",
            "COUNT",
            "UNTIL",
            "BYDAY",
            "BYMONTHDAY",
        }
        if unsupported or "FREQ" not in fields:
            raise ValueError("RRULE contains unsupported fields.")
        interval = int(fields.get("INTERVAL", "1"))
        count = int(fields["COUNT"]) if "COUNT" in fields else None
        until: date | datetime | None = None
        if "UNTIL" in fields:
            raw_until = fields["UNTIL"]
            try:
                until = (
                    datetime.strptime(raw_until, cls._UNTIL_FORMAT).replace(tzinfo=UTC)
                    if "T" in raw_until
                    else datetime.strptime(raw_until, "%Y%m%d").date()
                )
            except ValueError as error:
                raise ValueError(
                    "UNTIL must be an RFC 5545 UTC datetime or date."
                ) from error
        by_day = tuple(fields["BYDAY"].split(",")) if "BYDAY" in fields else ()
        by_month_day = (
            tuple(int(value) for value in fields["BYMONTHDAY"].split(","))
            if "BYMONTHDAY" in fields
            else ()
        )
        return cls(fields["FREQ"], interval, count, until, by_day, by_month_day)
