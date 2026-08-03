"""Provider-neutral explicit calendar synchronization contracts."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from lea.calendars.contracts import CalendarProviderIssue


@dataclass(frozen=True, slots=True)
class CalendarSynchronizationInspectionResult:
    available: bool
    provider: str
    version: str | None
    issues: tuple[CalendarProviderIssue, ...]

    def __post_init__(self) -> None:
        if self.available and (self.version is None or self.issues):
            raise ValueError("Available synchronization requires only a version.")
        if not self.available and (self.version is not None or not self.issues):
            raise ValueError("Unavailable synchronization requires only issues.")


@dataclass(frozen=True, slots=True)
class CalendarSynchronizationResult:
    success: bool
    issues: tuple[CalendarProviderIssue, ...]

    def __post_init__(self) -> None:
        if self.success and self.issues:
            raise ValueError("Successful synchronization must not contain issues.")
        if not self.success and not self.issues:
            raise ValueError("Failed synchronization must contain an issue.")


@runtime_checkable
class CalendarSynchronizer(Protocol):
    def inspect(self) -> CalendarSynchronizationInspectionResult: ...

    def synchronize(self) -> CalendarSynchronizationResult: ...
