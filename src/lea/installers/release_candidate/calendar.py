"""Calendar toolchain integration for release-candidate installation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lea.installers.calendar.contracts import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallMode,
)
from lea.installers.calendar.dispatch import (
    CalendarToolchainInstallResult,
    install_calendar_toolchain,
)
from lea.installers.calendar.ownership import (
    CalendarOwnershipApplier,
    ignore_calendar_ownership,
)
from lea.installers.calendar.records import (
    CalendarToolchainInstallationRecord,
)
from lea.installers.release_candidate.contracts import (
    InstallerIssue,
    InstallerIssueCode,
    InstallerStepId,
    ReleaseCandidateInstallRequest,
)

CalendarToolchainInstaller = Callable[..., CalendarToolchainInstallResult]


@dataclass(frozen=True, slots=True)
class ReleaseCandidateCalendarInputs:
    """Pinned verified-network calendar inputs for one installation."""

    toolchain_version: str
    platform: str
    requirements_lock: Path
    expected_lock_sha256: str
    uv_executable: Path
    python_executable: Path
    package_index_url: str
    khal_version: str = "0.11.4"
    vdirsyncer_version: str = "0.19.3"
    timeout_seconds: float = 600.0

    def __post_init__(self) -> None:
        """Validate pinned calendar installation inputs."""
        for field_name, value in (
            ("toolchain_version", self.toolchain_version),
            ("platform", self.platform),
            ("khal_version", self.khal_version),
            ("vdirsyncer_version", self.vdirsyncer_version),
            ("expected_lock_sha256", self.expected_lock_sha256),
            ("package_index_url", self.package_index_url),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty.")

        for field_name, path in (
            ("requirements_lock", self.requirements_lock),
            ("uv_executable", self.uv_executable),
            ("python_executable", self.python_executable),
        ):
            _validate_absolute_path(path, field_name=field_name)

        if len(self.expected_lock_sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.expected_lock_sha256
        ):
            raise ValueError(
                "expected_lock_sha256 must be lower-case hexadecimal SHA-256 text."
            )

        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds,
            (int, float),
        ):
            raise TypeError("timeout_seconds must be a number.")

        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")


@dataclass(frozen=True, slots=True)
class ReleaseCandidateCalendarPlan:
    """Immutable managed calendar installation plan for the release candidate."""

    config: CalendarToolchainInstallerConfig
    expected_khal_executable: Path
    expected_vdirsyncer_executable: Path

    def __post_init__(self) -> None:
        """Validate managed executable relationships."""
        for field_name, executable in (
            ("expected_khal_executable", self.expected_khal_executable),
            (
                "expected_vdirsyncer_executable",
                self.expected_vdirsyncer_executable,
            ),
        ):
            _validate_absolute_path(executable, field_name=field_name)

        expected_bin = (
            self.config.tools_root / self.config.toolchain_version / ".venv" / "bin"
        )

        if self.expected_khal_executable != expected_bin / "khal":
            raise ValueError(
                "expected_khal_executable must match the managed khal path."
            )

        if self.expected_vdirsyncer_executable != (expected_bin / "vdirsyncer"):
            raise ValueError(
                "expected_vdirsyncer_executable must match the managed vdirsyncer path."
            )


@dataclass(frozen=True, slots=True)
class ReleaseCandidateCalendarResult:
    """Release-candidate view of one calendar toolchain installation."""

    success: bool
    already_installed: bool
    khal_executable: Path | None
    vdirsyncer_executable: Path | None
    record: CalendarToolchainInstallationRecord | None
    issues: tuple[InstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate result consistency."""
        for field_name, executable in (
            ("khal_executable", self.khal_executable),
            ("vdirsyncer_executable", self.vdirsyncer_executable),
        ):
            if executable is not None:
                _validate_absolute_path(executable, field_name=field_name)

        if self.success:
            if (
                self.khal_executable is None
                or self.vdirsyncer_executable is None
                or self.record is None
            ):
                raise ValueError(
                    "A successful result must contain both executables "
                    "and the installation record."
                )

            if self.issues:
                raise ValueError("A successful result must not contain issues.")

            return

        if self.already_installed:
            raise ValueError("A failed result must not be marked already installed.")

        if (
            self.khal_executable is not None
            or self.vdirsyncer_executable is not None
            or self.record is not None
        ):
            raise ValueError(
                "A failed result must not contain executables or a record."
            )

        if not self.issues:
            raise ValueError("A failed result must contain at least one issue.")


def create_calendar_toolchain_installation_plan(
    request: ReleaseCandidateInstallRequest,
    inputs: ReleaseCandidateCalendarInputs,
) -> ReleaseCandidateCalendarPlan:
    """Create the pinned verified-network calendar installer configuration."""
    if not isinstance(request, ReleaseCandidateInstallRequest):
        raise TypeError("request must be a ReleaseCandidateInstallRequest value.")

    if not isinstance(inputs, ReleaseCandidateCalendarInputs):
        raise TypeError("inputs must be a ReleaseCandidateCalendarInputs value.")

    tools_root = Path("/opt/lea-tools/calendar")
    config = CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.VERIFIED_NETWORK,
        toolchain_version=inputs.toolchain_version,
        khal_version=inputs.khal_version,
        vdirsyncer_version=inputs.vdirsyncer_version,
        platform=inputs.platform,
        tools_root=tools_root,
        configuration_dir=request.configuration_root / "calendar",
        state_root=request.state_root / "calendar",
        installation_record=(
            request.state_root / "install" / "calendar-toolchain.json"
        ),
        service_user=request.service_user,
        service_group=request.service_group,
        uv_executable=inputs.uv_executable,
        python_executable=inputs.python_executable,
        requirements_lock=inputs.requirements_lock,
        expected_lock_sha256=inputs.expected_lock_sha256,
        package_index_url=inputs.package_index_url,
        timeout_seconds=inputs.timeout_seconds,
        non_interactive=True,
    )
    executable_root = tools_root / inputs.toolchain_version / ".venv" / "bin"

    return ReleaseCandidateCalendarPlan(
        config=config,
        expected_khal_executable=executable_root / "khal",
        expected_vdirsyncer_executable=executable_root / "vdirsyncer",
    )


def install_release_candidate_calendar_toolchain(
    plan: ReleaseCandidateCalendarPlan,
    *,
    display_timezone: str,
    installer: CalendarToolchainInstaller = install_calendar_toolchain,
    fsync: bool = True,
    apply_ownership: CalendarOwnershipApplier = ignore_calendar_ownership,
) -> ReleaseCandidateCalendarResult:
    """Install the calendar toolchain through its existing dispatcher."""
    if not isinstance(plan, ReleaseCandidateCalendarPlan):
        raise TypeError("plan must be a ReleaseCandidateCalendarPlan value.")

    result = installer(
        plan.config,
        display_timezone=display_timezone,
        fsync=fsync,
        apply_ownership=apply_ownership,
    )

    if not result.success or result.record is None:
        issues = _translate_component_issues(result.issues)

        if not issues:
            issues = (
                InstallerIssue(
                    code=InstallerIssueCode.STEP_FAILED,
                    message=(
                        "Calendar toolchain installation failed without "
                        "a structured component issue."
                    ),
                    step=InstallerStepId.CALENDAR_TOOLCHAIN,
                ),
            )

        return ReleaseCandidateCalendarResult(
            success=False,
            already_installed=False,
            khal_executable=None,
            vdirsyncer_executable=None,
            record=None,
            issues=issues,
        )

    record = result.record

    if (
        record.khal_executable != plan.expected_khal_executable
        or record.vdirsyncer_executable != plan.expected_vdirsyncer_executable
    ):
        unexpected = (
            record.khal_executable
            if record.khal_executable != plan.expected_khal_executable
            else record.vdirsyncer_executable
        )
        return ReleaseCandidateCalendarResult(
            success=False,
            already_installed=False,
            khal_executable=None,
            vdirsyncer_executable=None,
            record=None,
            issues=(
                InstallerIssue(
                    code=InstallerIssueCode.STEP_FAILED,
                    message=(
                        "Calendar installation returned an unexpected "
                        "managed executable path."
                    ),
                    step=InstallerStepId.CALENDAR_TOOLCHAIN,
                    path=unexpected,
                ),
            ),
        )

    return ReleaseCandidateCalendarResult(
        success=True,
        already_installed=result.already_installed,
        khal_executable=record.khal_executable,
        vdirsyncer_executable=record.vdirsyncer_executable,
        record=record,
        issues=(),
    )


def _translate_component_issues(
    issues: tuple[CalendarToolchainInstallerIssue, ...],
) -> tuple[InstallerIssue, ...]:
    """Translate calendar component diagnostics into installer-step issues."""
    return tuple(
        InstallerIssue(
            code=InstallerIssueCode.STEP_FAILED,
            message=issue.message,
            step=InstallerStepId.CALENDAR_TOOLCHAIN,
            field=issue.field,
            path=issue.path,
        )
        for issue in issues
    )


def _validate_absolute_path(
    path: Path,
    *,
    field_name: str,
) -> None:
    """Validate one absolute pathlib path."""
    if not isinstance(path, Path):
        raise TypeError(f"{field_name} must be a pathlib.Path value.")

    if not path.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path.")

    if "\x00" in str(path):
        raise ValueError(f"{field_name} must not contain a null byte.")
