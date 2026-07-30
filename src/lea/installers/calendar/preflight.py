"""Non-destructive calendar toolchain installer preflight checks."""

import hashlib
import os
from pathlib import Path

from lea.installers.calendar.contracts import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
)
from lea.installers.calendar.validation import (
    is_valid_calendar_sha256,
    validate_calendar_executable_path,
)


def calculate_calendar_sha256(path: Path) -> str:
    """Calculate one file's lower-case SHA-256 digest."""
    if not isinstance(path, Path):
        raise TypeError("path must be a pathlib.Path value.")

    if not path.is_absolute():
        raise ValueError("path must be absolute.")

    digest = hashlib.sha256()

    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def verify_calendar_sha256(
    path: Path,
    expected_sha256: str,
    *,
    field_name: str,
    checksum_field: str,
    artefact_name: str,
) -> tuple[CalendarToolchainInstallerIssue, ...]:
    """Verify one exact calendar installer artefact and checksum."""
    if not isinstance(path, Path):
        raise TypeError("path must be a pathlib.Path value.")

    if not isinstance(expected_sha256, str):
        raise TypeError("expected_sha256 must be a string.")

    for argument_name, value in (
        ("field_name", field_name),
        ("checksum_field", checksum_field),
        ("artefact_name", artefact_name),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{argument_name} must be non-empty.")

    if not path.is_absolute():
        return (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=f"The {artefact_name} path must be absolute.",
                field=field_name,
            ),
        )

    if not is_valid_calendar_sha256(expected_sha256):
        return (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=(
                    f"The expected {artefact_name} checksum must be "
                    "lower-case SHA-256 text."
                ),
                field=checksum_field,
                path=path,
            ),
        )

    try:
        if not path.exists():
            return (
                CalendarToolchainInstallerIssue(
                    code=CalendarToolchainInstallFailureCode.ARTEFACT_MISSING,
                    message=f"The {artefact_name} does not exist.",
                    field=field_name,
                    path=path,
                ),
            )

        if path.is_symlink() or not path.is_file():
            return (
                CalendarToolchainInstallerIssue(
                    code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                    message=(
                        f"The {artefact_name} must be a regular non-symbolic file."
                    ),
                    field=field_name,
                    path=path,
                ),
            )

        actual_sha256 = calculate_calendar_sha256(path)
    except OSError:
        return (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.PERMISSION_DENIED,
                message=f"The {artefact_name} could not be read.",
                field=field_name,
                path=path,
            ),
        )

    if actual_sha256 != expected_sha256:
        return (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.CHECKSUM_MISMATCH,
                message=f"The {artefact_name} checksum did not match.",
                field=checksum_field,
                path=path,
            ),
        )

    return ()


def check_calendar_directory_parent_writable(
    path: Path,
    *,
    field_name: str,
) -> tuple[CalendarToolchainInstallerIssue, ...]:
    """Check whether one managed path can be created or replaced safely."""
    if not isinstance(path, Path):
        raise TypeError("path must be a pathlib.Path value.")

    if not isinstance(field_name, str) or not field_name.strip():
        raise ValueError("field_name must be non-empty.")

    if not path.is_absolute():
        return (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=f"{field_name} must be an absolute path.",
                field=field_name,
            ),
        )

    try:
        if path.is_symlink():
            return (
                CalendarToolchainInstallerIssue(
                    code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                    message=f"{field_name} must not be a symbolic link.",
                    field=field_name,
                    path=path,
                ),
            )

        existing = path

        if existing.exists() and not existing.is_dir():
            existing = existing.parent

        while not existing.exists() and existing != existing.parent:
            existing = existing.parent

        if not existing.exists():
            return (
                CalendarToolchainInstallerIssue(
                    code=CalendarToolchainInstallFailureCode.PERMISSION_DENIED,
                    message=(
                        f"No existing parent directory was found for {field_name}."
                    ),
                    field=field_name,
                    path=path,
                ),
            )

        if existing.is_symlink() or not existing.is_dir():
            return (
                CalendarToolchainInstallerIssue(
                    code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                    message=(
                        f"The nearest existing parent for {field_name} "
                        "must be a real directory."
                    ),
                    field=field_name,
                    path=existing,
                ),
            )

        if not os.access(existing, os.W_OK | os.X_OK):
            return (
                CalendarToolchainInstallerIssue(
                    code=CalendarToolchainInstallFailureCode.PERMISSION_DENIED,
                    message=(
                        "The installer cannot write to and search the parent "
                        f"directory for {field_name}."
                    ),
                    field=field_name,
                    path=existing,
                ),
            )
    except OSError:
        return (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.PERMISSION_DENIED,
                message=(
                    f"The parent directory for {field_name} could not be inspected."
                ),
                field=field_name,
                path=path,
            ),
        )

    return ()


def run_calendar_toolchain_installer_preflight(
    config: CalendarToolchainInstallerConfig,
) -> tuple[CalendarToolchainInstallerIssue, ...]:
    """Run volatile filesystem checks immediately before installation."""
    if not isinstance(config, CalendarToolchainInstallerConfig):
        raise TypeError("config must be a CalendarToolchainInstallerConfig value.")

    issues: list[CalendarToolchainInstallerIssue] = []

    for field_name, path in (
        ("tools_root", config.tools_root),
        ("configuration_dir", config.configuration_dir),
        ("state_root", config.state_root),
        ("installation_record", config.installation_record),
    ):
        issues.extend(
            check_calendar_directory_parent_writable(
                path,
                field_name=field_name,
            )
        )

    if config.mode in (
        CalendarToolchainInstallMode.VERIFIED_NETWORK,
        CalendarToolchainInstallMode.BUNDLED_WHEELHOUSE,
    ):
        _extend_executable_issues(
            config.uv_executable,
            field_name="uv_executable",
            tool_name="uv",
            issues=issues,
        )
        _extend_executable_issues(
            config.python_executable,
            field_name="python_executable",
            tool_name="Python",
            issues=issues,
        )
        _extend_checksum_issues(
            config.requirements_lock,
            config.expected_lock_sha256,
            field_name="requirements_lock",
            checksum_field="expected_lock_sha256",
            artefact_name="calendar requirements lock",
            issues=issues,
        )

    if config.mode is CalendarToolchainInstallMode.BUNDLED_WHEELHOUSE:
        _extend_checksum_issues(
            config.wheelhouse_archive,
            config.expected_wheelhouse_sha256,
            field_name="wheelhouse_archive",
            checksum_field="expected_wheelhouse_sha256",
            artefact_name="calendar wheelhouse archive",
            issues=issues,
        )

    if config.mode is CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES:
        _extend_executable_issues(
            config.external_khal_executable,
            field_name="external_khal_executable",
            tool_name="external khal",
            issues=issues,
        )
        _extend_executable_issues(
            config.external_vdirsyncer_executable,
            field_name="external_vdirsyncer_executable",
            tool_name="external vdirsyncer",
            issues=issues,
        )

    return tuple(issues)


def _extend_executable_issues(
    path: Path | None,
    *,
    field_name: str,
    tool_name: str,
    issues: list[CalendarToolchainInstallerIssue],
) -> None:
    """Append current executable-path issues."""
    if path is None:
        issues.append(
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=f"The {tool_name} executable path is missing.",
                field=field_name,
            )
        )
        return

    issues.extend(
        validate_calendar_executable_path(
            path,
            field_name=field_name,
            tool_name=tool_name,
        )
    )


def _extend_checksum_issues(
    path: Path | None,
    expected_sha256: str | None,
    *,
    field_name: str,
    checksum_field: str,
    artefact_name: str,
    issues: list[CalendarToolchainInstallerIssue],
) -> None:
    """Append current exact-file and checksum issues."""
    if path is None:
        issues.append(
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=f"The {artefact_name} path is missing.",
                field=field_name,
            )
        )
        return

    if expected_sha256 is None:
        issues.append(
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=f"The expected {artefact_name} checksum is missing.",
                field=checksum_field,
                path=path,
            )
        )
        return

    issues.extend(
        verify_calendar_sha256(
            path,
            expected_sha256,
            field_name=field_name,
            checksum_field=checksum_field,
            artefact_name=artefact_name,
        )
    )
