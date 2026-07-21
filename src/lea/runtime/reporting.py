"""Deterministic human-readable reporting for LEA runtime results."""

from pathlib import Path

from lea.runtime.contracts import (
    ConfigurationResult,
    RuntimeBootstrapResult,
    RuntimeConfig,
    RuntimeHealthResult,
    RuntimeInitialisationResult,
    RuntimeInspectionResult,
    RuntimeSetupResult,
    RuntimeSetupVerificationResult,
)


def format_runtime_config(
    config: RuntimeConfig,
) -> str:
    """Format one loaded runtime configuration."""
    paths = config.paths
    secrets = config.secrets

    lines = [
        "Runtime configuration",
        f"Schema version: {config.schema_version}",
        f"Profile: {config.profile.value}",
        f"Display timezone: {config.display_timezone}",
        f"Configuration file: {paths.config_file}",
        "",
        "Directories",
        f"State: {paths.state_dir}",
        f"Logs: {paths.log_dir}",
        f"Runtime: {paths.run_dir}",
        f"Audit: {paths.audit_dir}",
        f"Proposals: {paths.proposal_dir}",
        f"Knowledge: {paths.knowledge_dir}",
        f"Indexes: {paths.index_dir}",
        f"Adapters: {paths.adapter_dir}",
        f"Backups: {paths.backup_dir}",
        "",
        "Files",
        f"Audit file: {paths.audit_file}",
        f"Log file: {paths.log_file}",
        "",
        "Secret references",
        (f"Telegram token file: {_optional_path(secrets.telegram_token_file)}"),
    ]

    return _join_lines(lines)


def format_configuration_result(
    result: ConfigurationResult,
) -> str:
    """Format one runtime configuration-loading result."""
    if result.success:
        if result.config is None:
            raise ValueError("Successful configuration result contains no config.")

        return _join_sections(
            (
                "Configuration load: SUCCESS",
                format_runtime_config(result.config),
            )
        )

    lines = ["Configuration load: FAILED"]

    for issue in result.issues:
        lines.append(
            _format_issue(
                code=issue.code,
                message=issue.message,
                field=issue.field,
                path=issue.source_path,
            )
        )

    return _join_lines(lines)


def format_bootstrap_result(
    result: RuntimeBootstrapResult,
) -> str:
    """Format one runtime-directory bootstrap result."""
    mode = "DRY RUN" if result.dry_run else "LIVE"
    outcome = "SUCCESS" if result.success else "FAILED"

    lines = [
        f"Runtime bootstrap: {outcome}",
        f"Mode: {mode}",
    ]

    if not result.paths:
        lines.append("Paths: none")
    else:
        lines.append("Paths:")

        for path_result in result.paths:
            lines.append(
                "  "
                f"[{path_result.status.value}] "
                f"{path_result.path} — "
                f"{path_result.message}"
            )

    return _join_lines(lines)


def format_initialisation_result(
    result: RuntimeInitialisationResult,
) -> str:
    """Format one configuration-initialisation result."""
    mode = "DRY RUN" if result.dry_run else "LIVE"
    outcome = "SUCCESS" if result.success else "FAILED"

    return _join_lines(
        [
            f"Configuration initialisation: {outcome}",
            f"Mode: {mode}",
            f"Status: {result.status.value}",
            f"Destination: {result.destination}",
            f"Message: {result.message}",
        ]
    )


def format_health_result(
    result: RuntimeHealthResult,
) -> str:
    """Format one read-only runtime health result."""
    outcome = "HEALTHY" if result.healthy else "UNHEALTHY"

    lines = [f"Runtime health: {outcome}"]

    if not result.issues:
        lines.append("Checks: none")
    else:
        lines.append("Checks:")

        for issue in result.issues:
            lines.append(
                "  "
                f"[{issue.status.value}] "
                f"{
                    _format_issue(
                        code=issue.code,
                        message=issue.message,
                        field=issue.field,
                        path=issue.path,
                    )
                }"
            )

    return _join_lines(lines)


def format_setup_result(
    result: RuntimeSetupResult,
) -> str:
    """Format one coordinated runtime setup result."""
    outcome = "SUCCESS" if result.success else "FAILED"
    mode = "DRY RUN" if result.dry_run else "LIVE"

    sections = [
        _join_lines(
            [
                f"Runtime setup: {outcome}",
                f"Mode: {mode}",
            ]
        ),
        format_initialisation_result(result.initialisation),
    ]

    if result.bootstrap is None:
        sections.append("Runtime bootstrap: NOT RUN")
    else:
        sections.append(format_bootstrap_result(result.bootstrap))

    return _join_sections(tuple(sections))


def format_setup_verification_result(
    result: RuntimeSetupVerificationResult,
) -> str:
    """Format setup plus runtime-health verification."""
    verification = "VERIFIED" if result.verified else "NOT VERIFIED"

    sections = [
        _join_lines(
            [
                f"Runtime setup verification: {verification}",
                ("Mode: DRY RUN" if result.dry_run else "Mode: LIVE"),
            ]
        ),
        format_setup_result(result.setup),
    ]

    if result.health is None:
        sections.append("Runtime health: NOT RUN")
    else:
        sections.append(format_health_result(result.health))

    return _join_sections(tuple(sections))


def format_inspection_result(
    result: RuntimeInspectionResult,
) -> str:
    """Format one runtime inspection result."""
    outcome = "SUCCESS" if result.success else "FAILED"

    sections = [
        f"Runtime inspection: {outcome}",
        format_configuration_result(result.configuration),
    ]

    if result.health is None:
        sections.append("Runtime health: NOT REQUESTED")
    else:
        sections.append(format_health_result(result.health))

    return _join_sections(tuple(sections))


def _format_issue(
    *,
    code: str,
    message: str,
    field: str | None,
    path: Path | None,
) -> str:
    """Format one structured issue deterministically."""
    details = [f"{code}: {message}"]

    if field is not None:
        details.append(f"field={field}")

    if path is not None:
        details.append(f"path={path}")

    return " | ".join(details)


def _optional_path(
    path: Path | None,
) -> str:
    """Format an optional path reference."""
    if path is None:
        return "not configured"

    return str(path)


def _join_lines(
    lines: list[str],
) -> str:
    """Join report lines with exactly one trailing newline."""
    return "\n".join(lines) + "\n"


def _join_sections(
    sections: tuple[str, ...],
) -> str:
    """Join report sections with one blank line."""
    cleaned = tuple(section.rstrip("\n") for section in sections)

    return "\n\n".join(cleaned) + "\n"
