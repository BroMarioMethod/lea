"""Bundled-wheelhouse calendar toolchain installation workflow."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from lea.installers.calendar.activation import (
    CalendarToolchainActivatedLayout,
    activate_staged_calendar_toolchain,
    inspect_activated_calendar_toolchain,
    rollback_activated_calendar_toolchain,
)
from lea.installers.calendar.configuration import (
    persist_calendar_toolchain_configuration,
)
from lea.installers.calendar.contracts import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
)
from lea.installers.calendar.environment_execution import (
    execute_calendar_toolchain_environment_plan,
)
from lea.installers.calendar.environment_plan import (
    create_calendar_toolchain_environment_plan,
)
from lea.installers.calendar.ownership import (
    CalendarOwnershipApplier,
    ignore_calendar_ownership,
)
from lea.installers.calendar.preflight import (
    run_calendar_toolchain_installer_preflight,
)
from lea.installers.calendar.python_version import (
    inspect_calendar_python_version,
    inspect_staged_calendar_python_version,
)
from lea.installers.calendar.records import (
    CalendarToolchainInstallationRecord,
    calendar_toolchain_installation_record_matches,
    create_calendar_toolchain_installation_record,
    read_calendar_toolchain_installation_record,
    write_calendar_toolchain_installation_record,
)
from lea.installers.calendar.runtime_layout import (
    provision_calendar_toolchain_runtime_layout,
)
from lea.installers.calendar.smoke_test import (
    run_staged_calendar_toolchain_smoke_test,
)
from lea.installers.calendar.staging import (
    CalendarToolchainStagingLayout,
    create_calendar_toolchain_staging,
    remove_calendar_toolchain_staging,
)
from lea.installers.calendar.validation import (
    validate_calendar_toolchain_installer_config,
)
from lea.installers.calendar.version_check import (
    validate_calendar_tool_versions,
    validate_staged_calendar_tool_versions,
)
from lea.installers.calendar.wheelhouse import (
    extract_staged_calendar_wheelhouse,
)

type CalendarBundledInstallerClock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class CalendarBundledWheelhouseInstallResult:
    """Result of one bundled-wheelhouse calendar installation."""

    success: bool
    already_installed: bool
    record: CalendarToolchainInstallationRecord | None
    issues: tuple[CalendarToolchainInstallerIssue, ...]
    cleanup_issues: tuple[CalendarToolchainInstallerIssue, ...] = ()

    def __post_init__(self) -> None:
        """Validate result consistency."""
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


def install_bundled_calendar_toolchain(
    config: CalendarToolchainInstallerConfig,
    *,
    display_timezone: str,
    clock: CalendarBundledInstallerClock = lambda: datetime.now(UTC),
    fsync: bool = False,
    apply_ownership: CalendarOwnershipApplier = (ignore_calendar_ownership),
) -> CalendarBundledWheelhouseInstallResult:
    """Install one offline calendar toolchain from a verified wheelhouse."""
    if not isinstance(config, CalendarToolchainInstallerConfig):
        raise TypeError("config must be a CalendarToolchainInstallerConfig value.")

    if config.mode is not CalendarToolchainInstallMode.BUNDLED_WHEELHOUSE:
        return _failure(
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=(
                    "The bundled calendar installer requires bundled-wheelhouse mode."
                ),
                field="mode",
            )
        )

    validation = validate_calendar_toolchain_installer_config(config)

    if not validation.valid or validation.config is None:
        return CalendarBundledWheelhouseInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=validation.issues,
        )

    normalised = validation.config
    expected_lock_sha256 = normalised.expected_lock_sha256

    if expected_lock_sha256 is None:
        return _failure(
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message="The verified requirements-lock checksum is missing.",
                field="expected_lock_sha256",
            )
        )

    existing = _inspect_existing_installation(
        normalised,
        display_timezone=display_timezone,
        expected_lock_sha256=expected_lock_sha256,
        fsync=fsync,
        apply_ownership=apply_ownership,
    )

    if existing is not None:
        return existing

    preflight_issues = run_calendar_toolchain_installer_preflight(normalised)

    if preflight_issues:
        return CalendarBundledWheelhouseInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=preflight_issues,
        )

    staging = create_calendar_toolchain_staging(normalised)

    if staging.staged is None:
        return CalendarBundledWheelhouseInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=staging.issues,
        )

    staged = staging.staged
    extraction = extract_staged_calendar_wheelhouse(
        normalised,
        staged,
    )

    if extraction.extracted is None:
        return _failed_phase_with_cleanup(
            issues=extraction.issues,
            staged=staged,
        )

    try:
        plan = create_calendar_toolchain_environment_plan(
            normalised,
            staged,
        )
    except (TypeError, ValueError) as error:
        return _failure_with_cleanup(
            _phase_issue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=(
                    "The calendar environment plan could not be created: "
                    f"{_error_detail(error)}."
                ),
                field="environment_root",
                path=staged.environment_root,
            ),
            staged=staged,
        )

    environment = execute_calendar_toolchain_environment_plan(plan)

    if not environment.success:
        return _failed_phase_with_cleanup(
            issues=environment.issues,
            staged=staged,
        )

    staged_python = inspect_staged_calendar_python_version(
        normalised,
        staged,
    )

    if not staged_python.passed or staged_python.version is None:
        return _failed_phase_with_cleanup(
            issues=staged_python.issues,
            staged=staged,
        )

    versions = validate_staged_calendar_tool_versions(
        normalised,
        staged,
    )

    if not versions.passed:
        return _failed_phase_with_cleanup(
            issues=versions.issues,
            staged=staged,
        )

    smoke = run_staged_calendar_toolchain_smoke_test(
        normalised,
        staged,
    )

    if not smoke.passed:
        return _failed_phase_with_cleanup(
            issues=smoke.issues,
            staged=staged,
        )

    runtime = provision_calendar_toolchain_runtime_layout(
        normalised,
        apply_ownership=apply_ownership,
    )

    if not runtime.success or runtime.layout is None:
        return _failed_phase_with_cleanup(
            issues=runtime.issues,
            staged=staged,
        )

    configuration = persist_calendar_toolchain_configuration(
        normalised,
        runtime.layout,
        display_timezone=display_timezone,
        fsync=fsync,
        apply_ownership=apply_ownership,
    )

    if not configuration.success:
        return _failed_phase_with_cleanup(
            issues=configuration.issues,
            staged=staged,
        )

    activation = activate_staged_calendar_toolchain(
        normalised,
        staged,
        fsync=fsync,
        apply_ownership=apply_ownership,
    )

    if not activation.success or activation.activated is None:
        return _failed_phase_with_cleanup(
            issues=activation.issues,
            staged=staged,
        )

    activated = activation.activated
    final_python = inspect_calendar_python_version(
        python_executable=activated.python_executable,
        working_directory=activated.toolchain_root,
        timeout_seconds=normalised.timeout_seconds,
    )

    if not final_python.passed or final_python.version is None:
        return _failed_after_activation(
            issues=final_python.issues,
            config=normalised,
            activated=activated,
            staged=staged,
        )

    if final_python.version != staged_python.version:
        return _failed_after_activation(
            issues=(
                _phase_issue(
                    code=(CalendarToolchainInstallFailureCode.VERSION_CHECK_FAILED),
                    message=(
                        "The activated calendar Python version changed "
                        "after relocation."
                    ),
                    field="python_version",
                    path=activated.python_executable,
                ),
            ),
            config=normalised,
            activated=activated,
            staged=staged,
        )

    try:
        installed_at = clock()
        record = create_calendar_toolchain_installation_record(
            normalised,
            python_version=final_python.version,
            khal_executable=activated.khal_executable,
            vdirsyncer_executable=activated.vdirsyncer_executable,
            lock_or_manifest_sha256=(staged.requirements_lock_sha256),
            installed_at=installed_at,
        )
    except Exception as error:
        return _failed_after_activation(
            issues=(
                _phase_issue(
                    code=CalendarToolchainInstallFailureCode.RECORD_FAILED,
                    message=(
                        "The calendar installation record could not be "
                        f"created: {_error_detail(error)}."
                    ),
                    field="installation_record",
                    path=normalised.installation_record,
                ),
            ),
            config=normalised,
            activated=activated,
            staged=staged,
        )

    record_issues = write_calendar_toolchain_installation_record(
        record,
        destination=normalised.installation_record,
        owner="root",
        group=normalised.service_group,
        fsync=fsync,
        apply_ownership=apply_ownership,
    )

    if record_issues:
        return _failed_after_activation(
            issues=record_issues,
            config=normalised,
            activated=activated,
            staged=staged,
        )

    cleanup_issues = remove_calendar_toolchain_staging(staged)

    return CalendarBundledWheelhouseInstallResult(
        success=True,
        already_installed=False,
        record=record,
        issues=(),
        cleanup_issues=cleanup_issues,
    )


def _inspect_existing_installation(
    config: CalendarToolchainInstallerConfig,
    *,
    display_timezone: str,
    expected_lock_sha256: str,
    fsync: bool,
    apply_ownership: CalendarOwnershipApplier,
) -> CalendarBundledWheelhouseInstallResult | None:
    """Return idempotent success or fail closed for existing traces."""
    final_root = config.tools_root / config.toolchain_version
    record_path = config.installation_record
    root_present = final_root.exists() or final_root.is_symlink()
    record_present = record_path.exists() or record_path.is_symlink()

    if not root_present and not record_present:
        return None

    if not root_present:
        return _failure(
            _phase_issue(
                code=CalendarToolchainInstallFailureCode.ACTIVATION_FAILED,
                message=(
                    "A calendar installation record exists without its "
                    "versioned toolchain root."
                ),
                field="tools_root",
                path=final_root,
            )
        )

    if not record_present:
        return _failure(
            _phase_issue(
                code=CalendarToolchainInstallFailureCode.RECORD_FAILED,
                message=(
                    "An activated calendar toolchain exists without its "
                    "installation record."
                ),
                field="installation_record",
                path=record_path,
            )
        )

    activated = _activated_layout(config)
    inspection_issues = inspect_activated_calendar_toolchain(
        config,
        activated,
    )

    if inspection_issues:
        return CalendarBundledWheelhouseInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=inspection_issues,
        )

    python = inspect_calendar_python_version(
        python_executable=activated.python_executable,
        working_directory=activated.toolchain_root,
        timeout_seconds=config.timeout_seconds,
    )

    if not python.passed or python.version is None:
        return CalendarBundledWheelhouseInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=python.issues,
        )

    versions = validate_calendar_tool_versions(
        khal_executable=activated.khal_executable,
        expected_khal_version=config.khal_version,
        vdirsyncer_executable=activated.vdirsyncer_executable,
        expected_vdirsyncer_version=config.vdirsyncer_version,
        working_directory=activated.toolchain_root,
        timeout_seconds=config.timeout_seconds,
    )

    if not versions.passed:
        return CalendarBundledWheelhouseInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=versions.issues,
        )

    record, record_issues = read_calendar_toolchain_installation_record(record_path)

    if record_issues or record is None:
        return CalendarBundledWheelhouseInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=record_issues,
        )

    if not calendar_toolchain_installation_record_matches(
        record,
        config=config,
        python_version=python.version,
        khal_executable=activated.khal_executable,
        vdirsyncer_executable=activated.vdirsyncer_executable,
        lock_or_manifest_sha256=expected_lock_sha256,
    ):
        return _failure(
            _phase_issue(
                code=CalendarToolchainInstallFailureCode.RECORD_FAILED,
                message=(
                    "The existing calendar installation record does not "
                    "match the activated bundled toolchain."
                ),
                field="installation_record",
                path=record_path,
            )
        )

    runtime = provision_calendar_toolchain_runtime_layout(
        config,
        apply_ownership=apply_ownership,
    )

    if not runtime.success or runtime.layout is None:
        return CalendarBundledWheelhouseInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=runtime.issues,
        )

    configuration = persist_calendar_toolchain_configuration(
        config,
        runtime.layout,
        display_timezone=display_timezone,
        fsync=fsync,
        apply_ownership=apply_ownership,
    )

    if not configuration.success:
        return CalendarBundledWheelhouseInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=configuration.issues,
        )

    return CalendarBundledWheelhouseInstallResult(
        success=True,
        already_installed=True,
        record=record,
        issues=(),
    )


def _activated_layout(
    config: CalendarToolchainInstallerConfig,
) -> CalendarToolchainActivatedLayout:
    """Return canonical paths for one configured activated toolchain."""
    root = config.tools_root / config.toolchain_version
    environment = root / ".venv"
    bin_directory = environment / "bin"

    return CalendarToolchainActivatedLayout(
        toolchain_root=root,
        environment_root=environment,
        python_executable=bin_directory / "python",
        khal_executable=bin_directory / "khal",
        vdirsyncer_executable=bin_directory / "vdirsyncer",
    )


def _failed_after_activation(
    *,
    issues: tuple[CalendarToolchainInstallerIssue, ...],
    config: CalendarToolchainInstallerConfig,
    activated: CalendarToolchainActivatedLayout,
    staged: CalendarToolchainStagingLayout,
) -> CalendarBundledWheelhouseInstallResult:
    """Roll back a new activation and clean remaining staging."""
    rollback_issues = rollback_activated_calendar_toolchain(
        config,
        activated,
    )
    cleanup_issues = remove_calendar_toolchain_staging(staged)

    return CalendarBundledWheelhouseInstallResult(
        success=False,
        already_installed=False,
        record=None,
        issues=(*issues, *rollback_issues),
        cleanup_issues=cleanup_issues,
    )


def _failed_phase_with_cleanup(
    *,
    issues: tuple[CalendarToolchainInstallerIssue, ...],
    staged: CalendarToolchainStagingLayout,
) -> CalendarBundledWheelhouseInstallResult:
    """Return a failed pre-activation phase with cleanup evidence."""
    cleanup_issues = remove_calendar_toolchain_staging(staged)

    return CalendarBundledWheelhouseInstallResult(
        success=False,
        already_installed=False,
        record=None,
        issues=issues,
        cleanup_issues=cleanup_issues,
    )


def _failure_with_cleanup(
    issue: CalendarToolchainInstallerIssue,
    *,
    staged: CalendarToolchainStagingLayout,
) -> CalendarBundledWheelhouseInstallResult:
    """Return one failed phase and clean its private staging root."""
    return _failed_phase_with_cleanup(
        issues=(issue,),
        staged=staged,
    )


def _failure(
    issue: CalendarToolchainInstallerIssue,
) -> CalendarBundledWheelhouseInstallResult:
    """Return one coordinator failure."""
    return CalendarBundledWheelhouseInstallResult(
        success=False,
        already_installed=False,
        record=None,
        issues=(issue,),
    )


def _phase_issue(
    *,
    code: CalendarToolchainInstallFailureCode,
    message: str,
    field: str,
    path: Path,
) -> CalendarToolchainInstallerIssue:
    """Create one structured coordinator issue."""
    return CalendarToolchainInstallerIssue(
        code=code,
        message=message,
        field=field,
        path=path,
    )


def _error_detail(error: BaseException) -> str:
    """Return deterministic error text."""
    strerror = getattr(error, "strerror", None)

    if isinstance(strerror, str) and strerror:
        return strerror

    rendered = str(error).strip()
    return rendered or type(error).__name__
