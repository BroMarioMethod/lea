"""Read-only Local CLI status command."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from lea.adapters.taskwarrior import TaskwarriorConfig, inspect_taskwarrior
from lea.cli.contracts import CliIssue, CliResult, JsonValue, LocalCliExitCode
from lea.installers.taskwarrior import (
    TaskwarriorInstallationRecord,
    read_taskwarrior_installation_record,
)
from lea.proposals import ProposalVerificationResult
from lea.runtime import (
    ConfigurationResult,
    RuntimeConfig,
    RuntimeHealthResult,
    RuntimeProfile,
    check_runtime_health,
    load_runtime_config,
    runtime_proposal_repository,
)
from lea.tasks import TaskProviderInspectionResult

ConfigurationLoader = Callable[[str | Path], ConfigurationResult]
RuntimeHealthChecker = Callable[[RuntimeConfig], RuntimeHealthResult]
ProposalVerifier = Callable[[RuntimeConfig], ProposalVerificationResult]
InstallationRecordReader = Callable[
    [Path],
    tuple[TaskwarriorInstallationRecord | None, tuple[object, ...]],
]
TaskProviderInspector = Callable[[TaskwarriorConfig], TaskProviderInspectionResult]

DEFAULT_RUNTIME_CONFIG = Path("/etc/lea/lea.toml")


@dataclass(frozen=True, slots=True)
class StatusDependencies:
    """Injected read-only dependencies for the status command."""

    load_configuration: ConfigurationLoader = load_runtime_config
    check_health: RuntimeHealthChecker = check_runtime_health
    verify_proposals: ProposalVerifier | None = None
    read_installation_record: InstallationRecordReader = (
        read_taskwarrior_installation_record
    )
    inspect_provider: TaskProviderInspector = inspect_taskwarrior


def execute_status(
    *,
    config_path: Path,
    expected_profile: RuntimeProfile | None,
    dependencies: StatusDependencies | None = None,
) -> CliResult:
    """Inspect configured runtime and provider state without mutation."""
    resolved_dependencies = dependencies or StatusDependencies()
    configuration = resolved_dependencies.load_configuration(config_path)

    if not configuration.success:
        return CliResult.failed(
            exit_code=LocalCliExitCode.CONFIGURATION_ERROR,
            issues=tuple(
                CliIssue(
                    code=issue.code,
                    message=issue.message,
                    field=issue.field,
                )
                for issue in configuration.issues
            ),
            data={
                "configuration": {
                    "available": False,
                    "path": str(config_path),
                    "profile": None,
                },
                "proposal_repository": None,
                "runtime": None,
                "task_provider": None,
            },
        )

    config = configuration.config

    if config is None:
        return _internal_failure(
            "Successful configuration loading returned no runtime configuration."
        )

    if expected_profile is not None and config.profile is not expected_profile:
        return CliResult.failed(
            exit_code=LocalCliExitCode.CONFIGURATION_ERROR,
            issues=(
                CliIssue(
                    code="configuration_profile_mismatch",
                    message=(
                        "The loaded runtime profile does not match "
                        "the requested profile."
                    ),
                    field="profile",
                ),
            ),
            data={
                "configuration": {
                    "available": True,
                    "path": str(config.paths.config_file),
                    "profile": config.profile.value,
                },
                "proposal_repository": None,
                "runtime": None,
                "task_provider": None,
            },
        )

    health = resolved_dependencies.check_health(config)
    verify_proposals = resolved_dependencies.verify_proposals or _verify_proposals
    proposals = verify_proposals(config)

    record, record_issues = resolved_dependencies.read_installation_record(
        config.component_records.taskwarrior
    )

    provider: TaskProviderInspectionResult | None = None
    provider_issues: tuple[CliIssue, ...] = ()

    if record is None:
        provider_issues = tuple(
            CliIssue(
                code=str(getattr(issue, "code", "taskwarrior_install_record_failed")),
                message=str(
                    getattr(
                        issue,
                        "message",
                        "The Taskwarrior installation record could not be loaded.",
                    )
                ),
                field=getattr(issue, "field", None),
            )
            for issue in record_issues
        )
    else:
        provider = resolved_dependencies.inspect_provider(
            TaskwarriorConfig(
                executable=record.executable,
                taskrc=record.taskrc,
                data_dir=record.data,
                home_dir=record.home,
            )
        )
        provider_issues = tuple(
            CliIssue(
                code=issue.code,
                message=issue.message,
                field=issue.field,
            )
            for issue in provider.issues
        )

    runtime_issues = tuple(
        CliIssue(
            code=issue.code,
            message=issue.message,
            field=issue.field,
        )
        for issue in health.issues
        if issue.status.value != "passed"
    )
    proposal_issues = tuple(
        CliIssue(
            code=issue.code,
            message=issue.message,
            field=issue.field,
        )
        for issue in proposals.issues
    )
    issues = (*runtime_issues, *proposal_issues, *provider_issues)

    provider_available = provider is not None and provider.available

    data: dict[str, JsonValue] = {
        "configuration": {
            "available": True,
            "path": str(config.paths.config_file),
            "profile": config.profile.value,
        },
        "runtime": {
            "healthy": health.healthy,
            "warning_count": sum(
                issue.status.value == "warning" for issue in health.issues
            ),
            "failure_count": sum(
                issue.status.value == "failed" for issue in health.issues
            ),
        },
        "proposal_repository": {
            "available": proposals.valid,
            "checked_documents": proposals.checked_documents,
        },
        "task_provider": {
            "available": provider_available,
            "provider": "taskwarrior",
            "version": provider.version if provider is not None else None,
            "installation_record": str(config.component_records.taskwarrior),
        },
    }

    if not provider_available:
        return CliResult.failed(
            exit_code=LocalCliExitCode.PROVIDER_UNAVAILABLE,
            issues=issues
            or (
                CliIssue(
                    code="provider_unavailable",
                    message="The configured task provider is unavailable.",
                ),
            ),
            data=cast(JsonValue, data),
        )

    if not health.healthy or not proposals.valid:
        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=issues,
            data=cast(JsonValue, data),
        )

    return CliResult.succeeded(
        data=cast(JsonValue, data),
        issues=issues,
    )


def render_status_result(result: CliResult) -> str:
    """Render one stable human-readable status report."""
    data = result.data

    if not isinstance(data, dict):
        return _render_issues_only(result)

    configuration = _mapping(data.get("configuration"))
    runtime = _mapping(data.get("runtime"))
    proposals = _mapping(data.get("proposal_repository"))
    provider = _mapping(data.get("task_provider"))

    lines = [
        "LEA status",
        "",
        f"Configuration: {_availability(configuration)}",
        f"  Path: {_display(configuration.get('path'))}",
        f"  Profile: {_display(configuration.get('profile'))}",
        f"Runtime health: {_healthy(runtime)}",
        f"Proposal repository: {_availability(proposals)}",
        (f"  Checked documents: {_display(proposals.get('checked_documents'))}"),
        f"Task provider: {_availability(provider)}",
        f"  Provider: {_display(provider.get('provider'))}",
        f"  Version: {_display(provider.get('version'))}",
        (f"  Installation record: {_display(provider.get('installation_record'))}"),
    ]

    if result.issues:
        lines.extend(["", "Issues:"])
        lines.extend(f"  {issue.code}: {issue.message}" for issue in result.issues)

    return "\n".join(lines)


def _verify_proposals(config: RuntimeConfig) -> ProposalVerificationResult:
    """Verify the configured proposal repository without mutation."""
    return runtime_proposal_repository(config).verify()


def _availability(data: dict[str, object]) -> str:
    """Render one availability flag."""
    return "AVAILABLE" if data.get("available") is True else "UNAVAILABLE"


def _healthy(data: dict[str, object]) -> str:
    """Render one runtime health flag."""
    if not data:
        return "NOT CHECKED"
    return "HEALTHY" if data.get("healthy") is True else "UNHEALTHY"


def _mapping(value: object) -> dict[str, object]:
    """Return a mapping-shaped status section."""
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    return {}


def _display(value: object) -> str:
    """Render one optional status value."""
    if value is None:
        return "not available"
    return str(value)


def _render_issues_only(result: CliResult) -> str:
    """Render a status result without structured component data."""
    if not result.issues:
        return "LEA status is unavailable."
    return "\n".join(f"{issue.code}: {issue.message}" for issue in result.issues)


def _internal_failure(message: str) -> CliResult:
    """Construct one deterministic internal failure."""
    return CliResult.failed(
        exit_code=LocalCliExitCode.INTERNAL_ERROR,
        issues=(
            CliIssue(
                code="internal_error",
                message=message,
            ),
        ),
    )
