"""Read-only runtime health checking for LEA."""

import os
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lea.runtime.contracts import (
    RuntimeConfig,
    RuntimeHealthIssue,
    RuntimeHealthResult,
    RuntimeHealthStatus,
)


def check_runtime_health(
    config: RuntimeConfig,
) -> RuntimeHealthResult:
    """Inspect one configured runtime without mutating it."""
    issues: list[RuntimeHealthIssue] = []

    _check_configuration_file(
        config.paths.config_file,
        issues,
    )

    for field_name, path in _required_directories(config):
        _check_directory(
            path,
            field=field_name,
            require_read=True,
            require_write=True,
            issues=issues,
        )

    _check_parent_directory(
        config.paths.audit_file,
        field="paths.audit_file",
        issues=issues,
    )
    _check_parent_directory(
        config.paths.log_file,
        field="paths.log_file",
        issues=issues,
    )

    _check_secret_file(
        config.secrets.telegram_token_file,
        field="secrets.telegram_token_file",
        issues=issues,
    )

    _check_timezone(
        config.display_timezone,
        issues,
    )

    _check_path_separation(
        config,
        issues,
    )

    return RuntimeHealthResult(
        healthy=not any(issue.status is RuntimeHealthStatus.FAILED for issue in issues),
        issues=tuple(issues),
    )


def _required_directories(
    config: RuntimeConfig,
) -> tuple[tuple[str, Path], ...]:
    """Return required runtime directories with field names."""
    paths = config.paths

    return (
        ("paths.state_dir", paths.state_dir),
        ("paths.log_dir", paths.log_dir),
        ("paths.run_dir", paths.run_dir),
        ("paths.audit_dir", paths.audit_dir),
        ("paths.proposal_dir", paths.proposal_dir),
        ("paths.knowledge_dir", paths.knowledge_dir),
        ("paths.index_dir", paths.index_dir),
        ("paths.adapter_dir", paths.adapter_dir),
        ("paths.backup_dir", paths.backup_dir),
    )


def _check_configuration_file(
    path: Path,
    issues: list[RuntimeHealthIssue],
) -> None:
    """Check that the configuration source remains readable."""
    if not path.exists():
        issues.append(
            RuntimeHealthIssue(
                code="configuration_not_found",
                message="The runtime configuration file is missing.",
                status=RuntimeHealthStatus.FAILED,
                path=path,
                field="paths.config_file",
            )
        )
        return

    if not path.is_file():
        issues.append(
            RuntimeHealthIssue(
                code="configuration_not_readable",
                message=("The runtime configuration path is not a regular file."),
                status=RuntimeHealthStatus.FAILED,
                path=path,
                field="paths.config_file",
            )
        )
        return

    if not os.access(path, os.R_OK):
        issues.append(
            RuntimeHealthIssue(
                code="configuration_not_readable",
                message=("The runtime configuration file is not readable."),
                status=RuntimeHealthStatus.FAILED,
                path=path,
                field="paths.config_file",
            )
        )
        return

    issues.append(
        RuntimeHealthIssue(
            code="configuration_readable",
            message="The runtime configuration file is readable.",
            status=RuntimeHealthStatus.PASSED,
            path=path,
            field="paths.config_file",
        )
    )


def _check_directory(
    path: Path,
    *,
    field: str,
    require_read: bool,
    require_write: bool,
    issues: list[RuntimeHealthIssue],
) -> None:
    """Check one required runtime directory."""
    if not path.exists():
        issues.append(
            RuntimeHealthIssue(
                code="runtime_path_missing",
                message="The required runtime directory is missing.",
                status=RuntimeHealthStatus.FAILED,
                path=path,
                field=field,
            )
        )
        return

    if not path.is_dir():
        issues.append(
            RuntimeHealthIssue(
                code="runtime_path_not_directory",
                message=("The configured runtime path is not a directory."),
                status=RuntimeHealthStatus.FAILED,
                path=path,
                field=field,
            )
        )
        return

    if require_read and not os.access(path, os.R_OK):
        issues.append(
            RuntimeHealthIssue(
                code="runtime_path_not_readable",
                message=("The runtime directory is not readable."),
                status=RuntimeHealthStatus.FAILED,
                path=path,
                field=field,
            )
        )

    if require_write and not os.access(path, os.W_OK):
        issues.append(
            RuntimeHealthIssue(
                code="runtime_path_not_writable",
                message=("The runtime directory is not writable."),
                status=RuntimeHealthStatus.FAILED,
                path=path,
                field=field,
            )
        )

    if (not require_read or os.access(path, os.R_OK)) and (
        not require_write or os.access(path, os.W_OK)
    ):
        issues.append(
            RuntimeHealthIssue(
                code="runtime_path_available",
                message=(
                    "The runtime directory is available with the required access."
                ),
                status=RuntimeHealthStatus.PASSED,
                path=path,
                field=field,
            )
        )


def _check_parent_directory(
    file_path: Path,
    *,
    field: str,
    issues: list[RuntimeHealthIssue],
) -> None:
    """Check the configured parent for a runtime output file."""
    parent = file_path.parent

    if not parent.exists():
        issues.append(
            RuntimeHealthIssue(
                code="runtime_path_missing",
                message=("The configured output-file parent directory is missing."),
                status=RuntimeHealthStatus.FAILED,
                path=parent,
                field=field,
            )
        )
        return

    if not parent.is_dir():
        issues.append(
            RuntimeHealthIssue(
                code="runtime_path_not_directory",
                message=("The configured output-file parent is not a directory."),
                status=RuntimeHealthStatus.FAILED,
                path=parent,
                field=field,
            )
        )
        return

    if not os.access(parent, os.W_OK):
        issues.append(
            RuntimeHealthIssue(
                code="runtime_path_not_writable",
                message=("The configured output-file parent is not writable."),
                status=RuntimeHealthStatus.FAILED,
                path=parent,
                field=field,
            )
        )
        return

    issues.append(
        RuntimeHealthIssue(
            code="runtime_file_parent_available",
            message=("The configured output-file parent is available."),
            status=RuntimeHealthStatus.PASSED,
            path=parent,
            field=field,
        )
    )


def _check_secret_file(
    path: Path | None,
    *,
    field: str,
    issues: list[RuntimeHealthIssue],
) -> None:
    """Check optional secret-file presence without reading it."""
    if path is None:
        issues.append(
            RuntimeHealthIssue(
                code="secret_file_not_configured",
                message="The optional secret file is not configured.",
                status=RuntimeHealthStatus.WARNING,
                field=field,
            )
        )
        return

    if not path.exists():
        issues.append(
            RuntimeHealthIssue(
                code="secret_file_missing",
                message="The configured secret file is missing.",
                status=RuntimeHealthStatus.WARNING,
                path=path,
                field=field,
            )
        )
        return

    if not path.is_file():
        issues.append(
            RuntimeHealthIssue(
                code="secret_file_invalid",
                message=("The configured secret path is not a regular file."),
                status=RuntimeHealthStatus.FAILED,
                path=path,
                field=field,
            )
        )
        return

    issues.append(
        RuntimeHealthIssue(
            code="secret_file_present",
            message="The configured secret file is present.",
            status=RuntimeHealthStatus.PASSED,
            path=path,
            field=field,
        )
    )


def _check_timezone(
    display_timezone: str,
    issues: list[RuntimeHealthIssue],
) -> None:
    """Confirm that the display timezone remains available."""
    try:
        ZoneInfo(display_timezone)
    except ZoneInfoNotFoundError:
        issues.append(
            RuntimeHealthIssue(
                code="invalid_timezone",
                message=("The configured display timezone is not available."),
                status=RuntimeHealthStatus.FAILED,
                field="display_timezone",
            )
        )
        return

    issues.append(
        RuntimeHealthIssue(
            code="timezone_available",
            message="The configured display timezone is available.",
            status=RuntimeHealthStatus.PASSED,
            field="display_timezone",
        )
    )


def _check_path_separation(
    config: RuntimeConfig,
    issues: list[RuntimeHealthIssue],
) -> None:
    """Check important runtime path-separation rules."""
    paths = config.paths

    persistent_directories = (
        paths.state_dir,
        paths.log_dir,
        paths.audit_dir,
        paths.proposal_dir,
        paths.knowledge_dir,
        paths.index_dir,
        paths.adapter_dir,
        paths.backup_dir,
    )

    invalid = any(
        directory.is_relative_to(paths.run_dir) for directory in persistent_directories
    )

    if invalid:
        issues.append(
            RuntimeHealthIssue(
                code="invalid_path_relationship",
                message=(
                    "Persistent runtime directories must not be "
                    "inside the run directory."
                ),
                status=RuntimeHealthStatus.FAILED,
                field="paths",
            )
        )
        return

    issues.append(
        RuntimeHealthIssue(
            code="runtime_path_separation_valid",
            message="Runtime path separation is valid.",
            status=RuntimeHealthStatus.PASSED,
            field="paths",
        )
    )
