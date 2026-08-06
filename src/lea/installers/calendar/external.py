"""Administrator-selected external calendar tool registration."""

import errno
import hashlib
import os
import stat
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from lea.installers.calendar.configuration import (
    persist_calendar_toolchain_configuration,
)
from lea.installers.calendar.contracts import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
)
from lea.installers.calendar.ownership import (
    CalendarOwnershipApplier,
    ignore_calendar_ownership,
)
from lea.installers.calendar.preflight import (
    run_calendar_toolchain_installer_preflight,
)
from lea.installers.calendar.records import (
    CalendarToolchainInstallationRecord,
    create_external_calendar_toolchain_installation_record,
    external_calendar_toolchain_installation_record_matches,
    read_calendar_toolchain_installation_record,
    write_calendar_toolchain_installation_record,
)
from lea.installers.calendar.runtime_layout import (
    provision_calendar_toolchain_runtime_layout,
)
from lea.installers.calendar.smoke_test import (
    run_calendar_toolchain_smoke_test,
)
from lea.installers.calendar.validation import (
    validate_calendar_toolchain_installer_config,
)
from lea.installers.calendar.version_check import (
    validate_calendar_tool_versions,
)

_HASH_CHUNK_SIZE = 1024 * 1024

type CalendarExternalInstallerClock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class CalendarExternalInstallResult:
    """Result of registering exact administrator-selected calendar tools."""

    success: bool
    already_installed: bool
    record: CalendarToolchainInstallationRecord | None
    issues: tuple[CalendarToolchainInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate external-install result consistency."""
        if not isinstance(self.success, bool):
            raise TypeError("success must be a boolean.")

        if not isinstance(self.already_installed, bool):
            raise TypeError("already_installed must be a boolean.")

        if self.success:
            if self.record is None:
                raise ValueError(
                    "A successful external registration must contain a record."
                )

            if self.issues:
                raise ValueError(
                    "A successful external registration must not contain issues."
                )

            return

        if self.already_installed:
            raise ValueError(
                "A failed external registration must not be already installed."
            )

        if self.record is not None:
            raise ValueError(
                "A failed external registration must not contain a record."
            )

        if not self.issues:
            raise ValueError(
                "A failed external registration must contain at least one issue."
            )


def install_external_calendar_toolchain(
    config: CalendarToolchainInstallerConfig,
    *,
    display_timezone: str,
    clock: CalendarExternalInstallerClock = lambda: datetime.now(UTC),
    fsync: bool = False,
    apply_ownership: CalendarOwnershipApplier = (ignore_calendar_ownership),
) -> CalendarExternalInstallResult:
    """Verify and register exact external khal and vdirsyncer executables."""
    if not isinstance(config, CalendarToolchainInstallerConfig):
        raise TypeError("config must be a CalendarToolchainInstallerConfig value.")

    if config.mode is not CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES:
        return _failure(
            code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
            message=(
                "The external calendar installer requires external-executables mode."
            ),
            field="mode",
        )

    validation = validate_calendar_toolchain_installer_config(config)

    if not validation.valid or validation.config is None:
        return CalendarExternalInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=validation.issues,
        )

    normalised = validation.config
    preflight_issues = run_calendar_toolchain_installer_preflight(normalised)

    if preflight_issues:
        return CalendarExternalInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=preflight_issues,
        )

    khal_executable = normalised.external_khal_executable
    vdirsyncer_executable = normalised.external_vdirsyncer_executable

    if khal_executable is None:
        return _failure(
            code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
            message="The external khal executable path is missing.",
            field="external_khal_executable",
        )

    if vdirsyncer_executable is None:
        return _failure(
            code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
            message="The external vdirsyncer executable path is missing.",
            field="external_vdirsyncer_executable",
        )

    khal_sha256, hash_issues = _hash_external_executable(
        khal_executable,
        field_name="external_khal_executable",
        tool_name="external khal",
    )

    if hash_issues or khal_sha256 is None:
        return _failed_issues(hash_issues)

    vdirsyncer_sha256, hash_issues = _hash_external_executable(
        vdirsyncer_executable,
        field_name="external_vdirsyncer_executable",
        tool_name="external vdirsyncer",
    )

    if hash_issues or vdirsyncer_sha256 is None:
        return _failed_issues(hash_issues)

    working_directory, directory_issue = _external_working_directory(normalised)

    if directory_issue is not None or working_directory is None:
        return _failed_issues(
            (
                directory_issue
                or CalendarToolchainInstallerIssue(
                    code=(CalendarToolchainInstallFailureCode.INVALID_ARGUMENT),
                    message=(
                        "The external calendar validation directory "
                        "could not be resolved."
                    ),
                    field="state_root_parent",
                    path=normalised.state_root.parent,
                ),
            )
        )

    versions = validate_calendar_tool_versions(
        khal_executable=khal_executable,
        expected_khal_version=normalised.khal_version,
        vdirsyncer_executable=vdirsyncer_executable,
        expected_vdirsyncer_version=normalised.vdirsyncer_version,
        working_directory=working_directory,
        timeout_seconds=normalised.timeout_seconds,
    )

    if not versions.passed:
        return _failed_issues(versions.issues)

    stable_hashes, stability_issues = _recheck_external_hashes(
        khal_executable=khal_executable,
        expected_khal_sha256=khal_sha256,
        vdirsyncer_executable=vdirsyncer_executable,
        expected_vdirsyncer_sha256=vdirsyncer_sha256,
    )

    if stability_issues or stable_hashes is None:
        return _failed_issues(stability_issues)

    khal_sha256, vdirsyncer_sha256 = stable_hashes
    existing = _inspect_existing_registration(
        normalised,
        khal_sha256=khal_sha256,
        vdirsyncer_sha256=vdirsyncer_sha256,
    )

    if existing is not None:
        if not existing.success:
            return existing

        runtime_result = _persist_runtime_and_configuration(
            normalised,
            display_timezone=display_timezone,
            fsync=fsync,
            apply_ownership=apply_ownership,
        )

        if runtime_result is not None:
            return runtime_result

        return existing

    smoke = run_calendar_toolchain_smoke_test(
        khal_executable=khal_executable,
        vdirsyncer_executable=vdirsyncer_executable,
        working_directory=working_directory,
        timeout_seconds=normalised.timeout_seconds,
    )

    if not smoke.passed:
        return _failed_issues(smoke.issues)

    stable_hashes, stability_issues = _recheck_external_hashes(
        khal_executable=khal_executable,
        expected_khal_sha256=khal_sha256,
        vdirsyncer_executable=vdirsyncer_executable,
        expected_vdirsyncer_sha256=vdirsyncer_sha256,
    )

    if stability_issues or stable_hashes is None:
        return _failed_issues(stability_issues)

    khal_sha256, vdirsyncer_sha256 = stable_hashes
    runtime_result = _persist_runtime_and_configuration(
        normalised,
        display_timezone=display_timezone,
        fsync=fsync,
        apply_ownership=apply_ownership,
    )

    if runtime_result is not None:
        return runtime_result

    stable_hashes, stability_issues = _recheck_external_hashes(
        khal_executable=khal_executable,
        expected_khal_sha256=khal_sha256,
        vdirsyncer_executable=vdirsyncer_executable,
        expected_vdirsyncer_sha256=vdirsyncer_sha256,
    )

    if stability_issues or stable_hashes is None:
        return _failed_issues(stability_issues)

    khal_sha256, vdirsyncer_sha256 = stable_hashes

    try:
        record = create_external_calendar_toolchain_installation_record(
            normalised,
            khal_executable_sha256=khal_sha256,
            vdirsyncer_executable_sha256=vdirsyncer_sha256,
            installed_at=clock(),
        )
    except (TypeError, ValueError) as error:
        return _failure(
            code=CalendarToolchainInstallFailureCode.RECORD_FAILED,
            message=(
                "The external calendar installation record could not be "
                f"created: {_error_detail(error)}."
            ),
            field="installation_record",
            path=normalised.installation_record,
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
        return _failed_issues(record_issues)

    return CalendarExternalInstallResult(
        success=True,
        already_installed=False,
        record=record,
        issues=(),
    )


def _inspect_existing_registration(
    config: CalendarToolchainInstallerConfig,
    *,
    khal_sha256: str,
    vdirsyncer_sha256: str,
) -> CalendarExternalInstallResult | None:
    """Return idempotent success or fail closed for an existing record."""
    destination = config.installation_record

    if not destination.exists() and not destination.is_symlink():
        return None

    record, issues = read_calendar_toolchain_installation_record(destination)

    if issues or record is None:
        return _failed_issues(issues)

    if not external_calendar_toolchain_installation_record_matches(
        record,
        config=config,
        khal_executable_sha256=khal_sha256,
        vdirsyncer_executable_sha256=vdirsyncer_sha256,
    ):
        return _failure(
            code=CalendarToolchainInstallFailureCode.RECORD_FAILED,
            message=(
                "The existing calendar installation record does not "
                "match the selected external executables."
            ),
            field="installation_record",
            path=destination,
        )

    return CalendarExternalInstallResult(
        success=True,
        already_installed=True,
        record=record,
        issues=(),
    )


def _persist_runtime_and_configuration(
    config: CalendarToolchainInstallerConfig,
    *,
    display_timezone: str,
    fsync: bool,
    apply_ownership: CalendarOwnershipApplier,
) -> CalendarExternalInstallResult | None:
    """Provision and persist only LEA-owned runtime state."""
    runtime = provision_calendar_toolchain_runtime_layout(
        config,
        apply_ownership=apply_ownership,
    )

    if not runtime.success or runtime.layout is None:
        return _failed_issues(runtime.issues)

    configuration = persist_calendar_toolchain_configuration(
        config,
        runtime.layout,
        display_timezone=display_timezone,
        fsync=fsync,
        apply_ownership=apply_ownership,
    )

    if not configuration.success:
        return _failed_issues(configuration.issues)

    return None


def _external_working_directory(
    config: CalendarToolchainInstallerConfig,
) -> tuple[Path | None, CalendarToolchainInstallerIssue | None]:
    """Require the existing real state parent used for disposable checks."""
    directory = config.state_root.parent

    try:
        if directory.is_symlink():
            return None, CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=(
                    "The external calendar validation directory must not "
                    "be a symbolic link."
                ),
                field="state_root_parent",
                path=directory,
            )

        if not directory.exists() or not directory.is_dir():
            return None, CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.DEPENDENCY_MISSING,
                message=(
                    "The external calendar validation directory does not "
                    "exist; the base LEA system layout must be provisioned "
                    "first."
                ),
                field="state_root_parent",
                path=directory,
            )

        if not os.access(directory, os.W_OK | os.X_OK):
            return None, CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.PERMISSION_DENIED,
                message=(
                    "The installer cannot create disposable calendar "
                    "validation data in the state parent."
                ),
                field="state_root_parent",
                path=directory,
            )
    except OSError as error:
        return None, CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.PERMISSION_DENIED,
            message=(
                "The external calendar validation directory could not be "
                f"inspected: {_error_detail(error)}."
            ),
            field="state_root_parent",
            path=directory,
        )

    return directory, None


def _recheck_external_hashes(
    *,
    khal_executable: Path,
    expected_khal_sha256: str,
    vdirsyncer_executable: Path,
    expected_vdirsyncer_sha256: str,
) -> tuple[
    tuple[str, str] | None,
    tuple[CalendarToolchainInstallerIssue, ...],
]:
    """Rehash both paths and reject changes across verification phases."""
    khal_sha256, issues = _hash_external_executable(
        khal_executable,
        field_name="external_khal_executable",
        tool_name="external khal",
    )

    if issues or khal_sha256 is None:
        return None, issues

    if khal_sha256 != expected_khal_sha256:
        return None, (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.CHECKSUM_MISMATCH,
                message=("The external khal executable changed during registration."),
                field="khal_executable_sha256",
                path=khal_executable,
            ),
        )

    vdirsyncer_sha256, issues = _hash_external_executable(
        vdirsyncer_executable,
        field_name="external_vdirsyncer_executable",
        tool_name="external vdirsyncer",
    )

    if issues or vdirsyncer_sha256 is None:
        return None, issues

    if vdirsyncer_sha256 != expected_vdirsyncer_sha256:
        return None, (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.CHECKSUM_MISMATCH,
                message=(
                    "The external vdirsyncer executable changed during registration."
                ),
                field="vdirsyncer_executable_sha256",
                path=vdirsyncer_executable,
            ),
        )

    return (khal_sha256, vdirsyncer_sha256), ()


def _hash_external_executable(
    path: Path,
    *,
    field_name: str,
    tool_name: str,
) -> tuple[str | None, tuple[CalendarToolchainInstallerIssue, ...]]:
    """Hash one exact non-symbolic regular executable using a no-follow FD."""
    if not isinstance(path, Path):
        raise TypeError("path must be a pathlib.Path value.")

    if not path.is_absolute():
        return None, (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=f"The {tool_name} executable path must be absolute.",
                field=field_name,
            ),
        )

    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    digest = hashlib.sha256()

    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)

        if not stat.S_ISREG(metadata.st_mode):
            return None, (
                CalendarToolchainInstallerIssue(
                    code=(CalendarToolchainInstallFailureCode.INVALID_ARGUMENT),
                    message=(f"The {tool_name} executable is not a regular file."),
                    field=field_name,
                    path=path,
                ),
            )

        if metadata.st_mode & 0o111 == 0:
            return None, (
                CalendarToolchainInstallerIssue(
                    code=(CalendarToolchainInstallFailureCode.PERMISSION_DENIED),
                    message=(f"The {tool_name} executable is not executable."),
                    field=field_name,
                    path=path,
                ),
            )

        while chunk := os.read(descriptor, _HASH_CHUNK_SIZE):
            digest.update(chunk)
    except FileNotFoundError:
        return None, (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.ARTEFACT_MISSING,
                message=f"The {tool_name} executable does not exist.",
                field=field_name,
                path=path,
            ),
        )
    except OSError as error:
        if error.errno == errno.ELOOP:
            return None, (
                CalendarToolchainInstallerIssue(
                    code=(CalendarToolchainInstallFailureCode.INVALID_ARGUMENT),
                    message=(
                        f"The {tool_name} executable must be a regular "
                        "non-symbolic file."
                    ),
                    field=field_name,
                    path=path,
                ),
            )

        return None, (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.PERMISSION_DENIED,
                message=(
                    f"The {tool_name} executable could not be read: "
                    f"{_error_detail(error)}."
                ),
                field=field_name,
                path=path,
            ),
        )
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)

    return digest.hexdigest(), ()


def _failed_issues(
    issues: tuple[CalendarToolchainInstallerIssue, ...],
) -> CalendarExternalInstallResult:
    """Create a failed result from one non-empty issue tuple."""
    if not issues:
        return _failure(
            code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
            message="The external calendar registration failed.",
            field="external_executables",
        )

    return CalendarExternalInstallResult(
        success=False,
        already_installed=False,
        record=None,
        issues=issues,
    )


def _failure(
    *,
    code: CalendarToolchainInstallFailureCode,
    message: str,
    field: str,
    path: Path | None = None,
) -> CalendarExternalInstallResult:
    """Create one structured external-registration failure."""
    return CalendarExternalInstallResult(
        success=False,
        already_installed=False,
        record=None,
        issues=(
            CalendarToolchainInstallerIssue(
                code=code,
                message=message,
                field=field,
                path=path,
            ),
        ),
    )


def _error_detail(error: BaseException) -> str:
    """Return deterministic diagnostic text."""
    strerror = getattr(error, "strerror", None)

    if isinstance(strerror, str) and strerror:
        return strerror

    rendered = str(error).strip()
    return rendered or type(error).__name__
