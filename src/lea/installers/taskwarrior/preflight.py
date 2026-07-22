"""Non-destructive Taskwarrior installer preflight checks."""

import hashlib
import os
from pathlib import Path

from lea.installers.taskwarrior.contracts import (
    TaskwarriorInstallerConfig,
    TaskwarriorInstallerIssue,
    TaskwarriorInstallFailureCode,
)


def calculate_sha256(path: Path) -> str:
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


def verify_expected_sha256(
    path: Path,
    expected_sha256: str,
) -> tuple[TaskwarriorInstallerIssue, ...]:
    """Verify one artefact against its expected checksum."""
    if not isinstance(path, Path):
        raise TypeError("path must be a pathlib.Path value.")

    if not isinstance(expected_sha256, str):
        raise TypeError("expected_sha256 must be a string.")

    if not path.is_absolute():
        return (
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
                message="The artefact path must be absolute.",
                field="artefact_path",
            ),
        )

    if not path.exists():
        return (
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.ARTEFACT_MISSING,
                message="The Taskwarrior artefact does not exist.",
                field="artefact_path",
                path=path,
            ),
        )

    if not path.is_file():
        return (
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
                message="The Taskwarrior artefact is not a regular file.",
                field="artefact_path",
                path=path,
            ),
        )

    actual_sha256 = calculate_sha256(path)

    if actual_sha256 != expected_sha256:
        return (
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.CHECKSUM_MISMATCH,
                message=(
                    "The Taskwarrior artefact checksum did not match "
                    "the expected SHA-256 value."
                ),
                field="expected_sha256",
                path=path,
            ),
        )

    return ()


def check_directory_parent_writable(
    path: Path,
    *,
    field_name: str,
) -> tuple[TaskwarriorInstallerIssue, ...]:
    """Check whether one path can be created or written safely."""
    if not isinstance(path, Path):
        raise TypeError("path must be a pathlib.Path value.")

    if not field_name.strip():
        raise ValueError("field_name must be non-empty.")

    if not path.is_absolute():
        return (
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
                message=f"{field_name} must be an absolute path.",
                field=field_name,
            ),
        )

    existing = path

    if existing.exists() and not existing.is_dir():
        existing = existing.parent

    while not existing.exists() and existing != existing.parent:
        existing = existing.parent

    if not existing.exists():
        return (
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.PERMISSION_DENIED,
                message=(f"No existing parent directory was found for {field_name}."),
                field=field_name,
                path=path,
            ),
        )

    if not existing.is_dir():
        return (
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
                message=(
                    f"The nearest existing parent for {field_name} is not a directory."
                ),
                field=field_name,
                path=existing,
            ),
        )

    if not os.access(existing, os.W_OK | os.X_OK):
        return (
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.PERMISSION_DENIED,
                message=(
                    f"The installer cannot write to the parent directory "
                    f"for {field_name}."
                ),
                field=field_name,
                path=existing,
            ),
        )

    return ()


def run_taskwarrior_installer_preflight(
    config: TaskwarriorInstallerConfig,
) -> tuple[TaskwarriorInstallerIssue, ...]:
    """Run non-destructive checks for one installer configuration."""
    issues: list[TaskwarriorInstallerIssue] = []

    for field_name, path in (
        ("tools_root", config.tools_root),
        ("configuration_dir", config.configuration_dir),
        ("state_root", config.state_root),
        ("installation_record", config.installation_record),
    ):
        issues.extend(
            check_directory_parent_writable(
                path,
                field_name=field_name,
            )
        )

    if config.artefact_path is not None and config.expected_sha256 is not None:
        issues.extend(
            verify_expected_sha256(
                config.artefact_path,
                config.expected_sha256,
            )
        )

    if config.source_archive is not None and config.expected_sha256 is not None:
        issues.extend(
            verify_expected_sha256(
                config.source_archive,
                config.expected_sha256,
            )
        )

    return tuple(issues)
