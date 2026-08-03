"""Explicit provider-neutral calendar synchronization through vdirsyncer."""

import re

from lea.adapters.vdirsyncer.contracts import VdirsyncerConfig
from lea.adapters.vdirsyncer.runner import VdirsyncerRunner
from lea.calendars import CalendarProviderIssue
from lea.calendars.synchronization import (
    CalendarSynchronizationInspectionResult,
    CalendarSynchronizationResult,
)

_VERSION_PATTERN = re.compile(r"^vdirsyncer(?:,? version)?\s+([^\s]+)$", re.I)


class VdirsyncerCalendarSynchronizer:
    """Inspect and explicitly synchronize all configured calendar pairs."""

    def __init__(
        self,
        config: VdirsyncerConfig,
        *,
        runner: VdirsyncerRunner | None = None,
    ) -> None:
        if not isinstance(config, VdirsyncerConfig):
            raise TypeError("config must be a VdirsyncerConfig value.")
        if runner is not None and runner.config != config:
            raise ValueError("runner configuration must match config.")
        self._config = config
        self._runner = runner or VdirsyncerRunner(config)

    def inspect(self) -> CalendarSynchronizationInspectionResult:
        """Verify exact configured vdirsyncer compatibility without syncing."""
        result = self._runner.run(
            ("--version",),
            operation="inspect_sync",
            configured=False,
        )
        if not result.success or result.command is None:
            return CalendarSynchronizationInspectionResult(
                available=False,
                provider="vdirsyncer",
                version=None,
                issues=result.issues,
            )
        match = _VERSION_PATTERN.fullmatch(result.command.stdout.strip())
        version = match.group(1) if match is not None else None
        if version != self._config.expected_version:
            return CalendarSynchronizationInspectionResult(
                available=False,
                provider="vdirsyncer",
                version=None,
                issues=(
                    CalendarProviderIssue(
                        code="vdirsyncer_version_mismatch",
                        message="The configured vdirsyncer version was incompatible.",
                        provider="vdirsyncer",
                        operation="inspect_sync",
                        field="expected_version",
                    ),
                ),
            )
        return CalendarSynchronizationInspectionResult(
            available=True,
            provider="vdirsyncer",
            version=version,
            issues=(),
        )

    def synchronize(self) -> CalendarSynchronizationResult:
        """Run one explicit synchronization of configured pairs."""
        inspection = self.inspect()
        if not inspection.available:
            return CalendarSynchronizationResult(False, inspection.issues)
        result = self._runner.run(("sync",), operation="calendar_sync")
        return CalendarSynchronizationResult(result.success, result.issues)
