"""Installer progress-reporting boundaries."""

from __future__ import annotations

from typing import Protocol

from lea.installers.release_candidate.contracts import InstallerStepId


class InstallerProgressReporter(Protocol):
    """Non-terminal boundary for reporting installer progress."""

    def step_started(
        self,
        step: InstallerStepId,
        message: str,
    ) -> None:
        """Report that one installer step started."""
        ...

    def step_completed(
        self,
        step: InstallerStepId,
        message: str,
    ) -> None:
        """Report that one installer step completed."""
        ...

    def heartbeat(
        self,
        message: str,
        *,
        elapsed_seconds: float,
    ) -> None:
        """Report that a long-running operation remains active."""
        ...

    def detail(
        self,
        message: str,
    ) -> None:
        """Report one verbose operational detail."""
        ...

    def output(
        self,
        text: str,
    ) -> None:
        """Report live subprocess output."""
        ...


class NullInstallerProgressReporter:
    """No-op progress reporter used by non-terminal callers."""

    def step_started(
        self,
        step: InstallerStepId,
        message: str,
    ) -> None:
        """Discard a step-started event."""

    def step_completed(
        self,
        step: InstallerStepId,
        message: str,
    ) -> None:
        """Discard a step-completed event."""

    def heartbeat(
        self,
        message: str,
        *,
        elapsed_seconds: float,
    ) -> None:
        """Discard a heartbeat event."""

    def detail(
        self,
        message: str,
    ) -> None:
        """Discard an operational detail."""

    def output(
        self,
        text: str,
    ) -> None:
        """Discard live subprocess output."""
