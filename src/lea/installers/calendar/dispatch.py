"""Mode-based calendar toolchain installer dispatch."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from lea.installers.calendar.bundled import (
    CalendarBundledWheelhouseInstallResult,
    install_bundled_calendar_toolchain,
)
from lea.installers.calendar.contracts import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
)
from lea.installers.calendar.external import (
    CalendarExternalInstallResult,
    install_external_calendar_toolchain,
)
from lea.installers.calendar.ownership import (
    CalendarOwnershipApplier,
    ignore_calendar_ownership,
)
from lea.installers.calendar.records import (
    CalendarToolchainInstallationRecord,
)
from lea.installers.calendar.verified_network import (
    CalendarVerifiedNetworkInstallResult,
    install_verified_network_calendar_toolchain,
)

type CalendarToolchainInstallerClock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class CalendarToolchainInstallResult:
    """Provider-neutral result of one calendar toolchain installation."""

    success: bool
    already_installed: bool
    record: CalendarToolchainInstallationRecord | None
    issues: tuple[CalendarToolchainInstallerIssue, ...]
    cleanup_issues: tuple[CalendarToolchainInstallerIssue, ...] = ()

    def __post_init__(self) -> None:
        """Validate generic installation-result consistency."""
        if not isinstance(self.success, bool):
            raise TypeError("success must be a boolean.")

        if not isinstance(self.already_installed, bool):
            raise TypeError("already_installed must be a boolean.")

        if self.success:
            if self.record is None:
                raise ValueError("A successful installation must contain a record.")

            if self.issues:
                raise ValueError("A successful installation must not contain issues.")

            return

        if self.already_installed:
            raise ValueError("A failed installation must not be already installed.")

        if self.record is not None:
            raise ValueError("A failed installation must not contain a record.")

        if not self.issues:
            raise ValueError("A failed installation must contain at least one issue.")


def install_calendar_toolchain(
    config: CalendarToolchainInstallerConfig,
    *,
    display_timezone: str,
    clock: CalendarToolchainInstallerClock = lambda: datetime.now(UTC),
    fsync: bool = False,
    apply_ownership: CalendarOwnershipApplier = (ignore_calendar_ownership),
) -> CalendarToolchainInstallResult:
    """Install the calendar toolchain using the configured mode."""
    if not isinstance(config, CalendarToolchainInstallerConfig):
        raise TypeError("config must be a CalendarToolchainInstallerConfig value.")

    if config.mode is CalendarToolchainInstallMode.VERIFIED_NETWORK:
        verified_result = install_verified_network_calendar_toolchain(
            config,
            display_timezone=display_timezone,
            clock=clock,
            fsync=fsync,
            apply_ownership=apply_ownership,
        )
        return _from_verified_network(verified_result)

    if config.mode is CalendarToolchainInstallMode.BUNDLED_WHEELHOUSE:
        bundled_result = install_bundled_calendar_toolchain(
            config,
            display_timezone=display_timezone,
            clock=clock,
            fsync=fsync,
            apply_ownership=apply_ownership,
        )
        return _from_bundled(bundled_result)

    if config.mode is CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES:
        external_result = install_external_calendar_toolchain(
            config,
            display_timezone=display_timezone,
            clock=clock,
            fsync=fsync,
            apply_ownership=apply_ownership,
        )
        return _from_external(external_result)

    return CalendarToolchainInstallResult(
        success=False,
        already_installed=False,
        record=None,
        issues=(
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=("The calendar toolchain installation mode is unsupported."),
                field="mode",
            ),
        ),
    )


def _from_verified_network(
    result: CalendarVerifiedNetworkInstallResult,
) -> CalendarToolchainInstallResult:
    """Convert one network result to the generic result contract."""
    return CalendarToolchainInstallResult(
        success=result.success,
        already_installed=result.already_installed,
        record=result.record,
        issues=result.issues,
        cleanup_issues=result.cleanup_issues,
    )


def _from_bundled(
    result: CalendarBundledWheelhouseInstallResult,
) -> CalendarToolchainInstallResult:
    """Convert one bundled result to the generic result contract."""
    return CalendarToolchainInstallResult(
        success=result.success,
        already_installed=result.already_installed,
        record=result.record,
        issues=result.issues,
        cleanup_issues=result.cleanup_issues,
    )


def _from_external(
    result: CalendarExternalInstallResult,
) -> CalendarToolchainInstallResult:
    """Convert one external result to the generic result contract."""
    return CalendarToolchainInstallResult(
        success=result.success,
        already_installed=result.already_installed,
        record=result.record,
        issues=result.issues,
        cleanup_issues=(),
    )
