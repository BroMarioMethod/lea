"""Local CLI proposal commands."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from lea.actions import (
    ActionHandlerRegistry,
    ActionStatus,
    ConfirmationDecision,
    action_execution_result_to_dict,
    proposal_to_dict,
)
from lea.audit import IntegrityJsonlAuditStore, generate_event_id
from lea.cli.contracts import CliIssue, CliResult, JsonValue, LocalCliExitCode
from lea.cli.task_provider import (
    TaskProviderDependencies,
    load_task_provider,
)
from lea.orchestration import ActionOrchestrator, OrchestrationOutcome
from lea.proposals import (
    MarkdownProposalRepository,
    ProposalListResult,
    ProposalReadResult,
)
from lea.runtime import (
    ConfigurationResult,
    RuntimeConfig,
    RuntimeProfile,
    load_runtime_config,
    localise_utc_timestamp,
    runtime_proposal_repository,
)
from lea.tasks import task_action_handler_registry

ConfigurationLoader = Callable[[str | Path], ConfigurationResult]
ProposalRepositoryFactory = Callable[[RuntimeConfig], MarkdownProposalRepository]

AuditStoreFactory = Callable[[RuntimeConfig], IntegrityJsonlAuditStore]
OrchestratorFactory = Callable[[IntegrityJsonlAuditStore], ActionOrchestrator]
ExecutionOrchestratorFactory = Callable[
    [ActionHandlerRegistry, IntegrityJsonlAuditStore],
    ActionOrchestrator,
]


def _runtime_audit_store(config: RuntimeConfig) -> IntegrityJsonlAuditStore:
    return IntegrityJsonlAuditStore(config.paths.audit_file, create_parents=False)


def _runtime_orchestrator(
    audit_store: IntegrityJsonlAuditStore,
) -> ActionOrchestrator:
    return ActionOrchestrator(
        ActionHandlerRegistry(),
        audit_store,
        lambda: datetime.now(UTC),
        generate_event_id,
    )


def _runtime_execution_orchestrator(
    registry: ActionHandlerRegistry,
    audit_store: IntegrityJsonlAuditStore,
) -> ActionOrchestrator:
    return ActionOrchestrator(
        registry,
        audit_store,
        lambda: datetime.now(UTC),
        generate_event_id,
    )


@dataclass(frozen=True, slots=True)
class ProposalCommandDependencies:
    """Injected read-only dependencies for proposal commands."""

    load_configuration: ConfigurationLoader = load_runtime_config
    create_repository: ProposalRepositoryFactory = runtime_proposal_repository
    create_audit_store: AuditStoreFactory = _runtime_audit_store
    create_orchestrator: OrchestratorFactory = _runtime_orchestrator
    create_execution_orchestrator: ExecutionOrchestratorFactory = (
        _runtime_execution_orchestrator
    )
    task_provider_dependencies: TaskProviderDependencies | None = None


def execute_proposal_list(
    *,
    config_path: Path,
    expected_profile: RuntimeProfile | None,
    status: ActionStatus | None,
    action_type: str | None,
    limit: int | None,
    dependencies: ProposalCommandDependencies | None = None,
) -> CliResult:
    """List persistent proposals through the configured repository."""
    if limit is not None and limit < 1:
        return CliResult.failed(
            exit_code=LocalCliExitCode.VALIDATION_ERROR,
            issues=(
                CliIssue(
                    code="proposal_limit_invalid",
                    message="--limit must be a positive integer.",
                    field="limit",
                ),
            ),
            data={"proposals": []},
        )

    resolved = dependencies or ProposalCommandDependencies()
    configuration = resolved.load_configuration(config_path)

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
            data={"proposals": []},
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
            data={"proposals": []},
        )

    repository_result = resolved.create_repository(config).list_all()

    if not repository_result.success:
        return _map_repository_failure(repository_result)

    proposals = tuple(reversed(repository_result.proposals))

    if status is not None:
        proposals = tuple(
            proposal for proposal in proposals if proposal.status is status
        )

    if action_type is not None:
        proposals = tuple(
            proposal for proposal in proposals if proposal.action == action_type
        )

    if limit is not None:
        proposals = proposals[:limit]

    return CliResult.succeeded(
        data=cast(
            JsonValue,
            {
                "display_timezone": config.display_timezone,
                "proposals": [proposal_to_dict(proposal) for proposal in proposals],
            },
        )
    )


def execute_proposal_show(
    *,
    config_path: Path,
    expected_profile: RuntimeProfile | None,
    proposal_id: str,
    dependencies: ProposalCommandDependencies | None = None,
) -> CliResult:
    """Read one exact persistent proposal."""
    validation = _validate_proposal_id(proposal_id)

    if validation is not None:
        return validation

    resolved = dependencies or ProposalCommandDependencies()
    configuration = resolved.load_configuration(config_path)

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
            data={"proposal": None},
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
            data={"proposal": None},
        )

    result = resolved.create_repository(config).read(proposal_id)

    if not result.success:
        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=tuple(
                CliIssue(
                    code=issue.code,
                    message=issue.message,
                    field=issue.field,
                )
                for issue in result.issues
            ),
            data={"proposal": None},
        )

    proposal = result.proposal

    if proposal is None:
        return _internal_failure("Successful proposal reading returned no proposal.")

    return CliResult.succeeded(
        data=cast(
            JsonValue,
            {
                "display_timezone": config.display_timezone,
                "proposal": proposal_to_dict(proposal),
                "repository_verified": True,
            },
        )
    )


def execute_proposal_execute(
    *,
    config_path: Path,
    expected_profile: RuntimeProfile | None,
    proposal_id: str,
    dependencies: ProposalCommandDependencies | None = None,
) -> CliResult:
    """Execute one persistent approved proposal."""
    validation = _validate_proposal_id(proposal_id)
    if validation is not None:
        return validation

    resolved = dependencies or ProposalCommandDependencies()
    configuration = resolved.load_configuration(config_path)
    if not configuration.success:
        return _configuration_failure(configuration)

    config = configuration.config
    if config is None:
        return _internal_failure(
            "Successful configuration loading returned no runtime configuration."
        )

    if expected_profile is not None and config.profile is not expected_profile:
        return _profile_mismatch_failure()

    repository = resolved.create_repository(config)
    read_result = repository.read(proposal_id)
    if not read_result.success:
        return _map_proposal_read_failure(read_result)

    proposal = read_result.proposal
    if proposal is None:
        return _internal_failure("Successful proposal reading returned no proposal.")

    if proposal.status is not ActionStatus.APPROVED:
        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=(
                CliIssue(
                    code="execution_rejected",
                    message="Only approved proposals may be executed.",
                    field="status",
                ),
            ),
            data={
                "proposal": proposal_to_dict(proposal),
                "execution": None,
                "audit_persisted": False,
                "proposal_persisted": False,
            },
        )

    provider_result = load_task_provider(
        config_path=config_path,
        expected_profile=expected_profile,
        dependencies=resolved.task_provider_dependencies,
    )
    if isinstance(provider_result, CliResult):
        return CliResult.failed(
            exit_code=provider_result.exit_code,
            issues=provider_result.issues,
            data={
                "proposal": proposal_to_dict(proposal),
                "execution": None,
                "audit_persisted": False,
                "proposal_persisted": False,
            },
        )

    try:
        registry = task_action_handler_registry(provider_result)
        audit_store = resolved.create_audit_store(config)
        orchestrator = resolved.create_execution_orchestrator(registry, audit_store)
        orchestration = orchestrator.execute(proposal)
    except Exception:
        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=(
                CliIssue(
                    code="proposal_execution_failed",
                    message="The proposal execution workflow could not complete.",
                ),
            ),
            data={
                "proposal": proposal_to_dict(proposal),
                "execution": None,
                "audit_persisted": False,
                "proposal_persisted": False,
            },
        )

    execution = orchestration.execution
    audit_persisted = bool(orchestration.persisted_events)

    if execution is None or not audit_persisted:
        issue = orchestration.issue
        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=(
                CliIssue(
                    code=issue.code if issue is not None else "execution_rejected",
                    message=(
                        issue.message
                        if issue is not None
                        else "The proposal could not be executed."
                    ),
                ),
            ),
            data={
                "proposal": proposal_to_dict(orchestration.proposal),
                "execution": (
                    action_execution_result_to_dict(execution)
                    if execution is not None
                    else None
                ),
                "audit_persisted": audit_persisted,
                "proposal_persisted": False,
            },
        )

    execution_data = action_execution_result_to_dict(execution)
    replacement = repository.replace(
        orchestration.proposal,
        expected_status=ActionStatus.APPROVED,
    )

    if not replacement.success:
        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=(
                CliIssue(
                    code="proposal_execution_partial_persistence",
                    message=(
                        "The execution audit event was persisted, but the "
                        "proposal document could not be replaced."
                    ),
                ),
                *tuple(
                    CliIssue(
                        code=issue.code,
                        message=issue.message,
                        field=issue.field,
                    )
                    for issue in replacement.issues
                ),
            ),
            data={
                "proposal": proposal_to_dict(orchestration.proposal),
                "execution": execution_data,
                "audit_persisted": True,
                "proposal_persisted": False,
            },
        )

    data = {
        "proposal": proposal_to_dict(orchestration.proposal),
        "execution": execution_data,
        "audit_persisted": True,
        "proposal_persisted": True,
    }

    if orchestration.proposal.status is ActionStatus.SUCCEEDED:
        return CliResult.succeeded(data=cast(JsonValue, data))

    recorded_execution = execution.execution
    error = recorded_execution.error if recorded_execution is not None else None
    return CliResult.failed(
        exit_code=LocalCliExitCode.APPLICATION_ERROR,
        issues=(
            CliIssue(
                code=(
                    error.code
                    if error is not None
                    else "proposal_execution_action_failed"
                ),
                message=(
                    error.message
                    if error is not None
                    else "The proposal action failed during execution."
                ),
            ),
        ),
        data=cast(JsonValue, data),
    )


def render_proposal_execute_result(result: CliResult) -> str:
    """Render one stable human-readable proposal execution result."""
    data = result.data
    if not isinstance(data, dict):
        return _render_issues(result)

    proposal = data.get("proposal")
    if not isinstance(proposal, dict):
        return _render_issues(result)

    execution = data.get("execution")
    error_code: object | None = None

    if isinstance(execution, dict):
        recorded_execution = execution.get("execution")
        if isinstance(recorded_execution, dict):
            error = recorded_execution.get("error")
            if isinstance(error, dict):
                error_code = error.get("code")

    heading = "Proposal executed." if result.success else "Proposal execution failed."
    lines = [
        heading,
        f"Proposal ID: {proposal.get('proposal_id', 'not available')}",
        f"Status: {proposal.get('status', 'not available')}",
        f"Audit persisted: {str(data.get('audit_persisted')).lower()}",
        f"Proposal persisted: {str(data.get('proposal_persisted')).lower()}",
    ]

    if error_code is not None:
        lines.append(f"Error: {error_code}")

    return "\n".join(lines)


def execute_proposal_approve(
    *,
    config_path: Path,
    expected_profile: RuntimeProfile | None,
    proposal_id: str,
    actor: str,
    reason: str | None,
    dependencies: ProposalCommandDependencies | None = None,
) -> CliResult:
    validation = _validate_proposal_id(proposal_id)
    if validation is not None:
        return validation

    if not actor.strip():
        return CliResult.failed(
            exit_code=LocalCliExitCode.VALIDATION_ERROR,
            issues=(
                CliIssue(
                    code="proposal_actor_invalid",
                    message="--actor must be a non-empty string.",
                    field="actor",
                ),
            ),
            data={"proposal": None},
        )

    if reason is not None and not reason.strip():
        return CliResult.failed(
            exit_code=LocalCliExitCode.VALIDATION_ERROR,
            issues=(
                CliIssue(
                    code="proposal_reason_invalid",
                    message="--reason must be non-empty when provided.",
                    field="reason",
                ),
            ),
            data={"proposal": None},
        )

    resolved = dependencies or ProposalCommandDependencies()
    configuration = resolved.load_configuration(config_path)
    if not configuration.success:
        return _configuration_failure(configuration)

    config = configuration.config
    if config is None:
        return _internal_failure(
            "Successful configuration loading returned no runtime configuration."
        )

    if expected_profile is not None and config.profile is not expected_profile:
        return _profile_mismatch_failure()

    repository = resolved.create_repository(config)
    read_result = repository.read(proposal_id)
    if not read_result.success:
        return _map_proposal_read_failure(read_result)

    proposal = read_result.proposal
    if proposal is None:
        return _internal_failure("Successful proposal reading returned no proposal.")

    try:
        audit_store = resolved.create_audit_store(config)
        orchestrator = resolved.create_orchestrator(audit_store)
        confirmation = orchestrator.confirm(
            proposal,
            ConfirmationDecision.APPROVED,
            actor.strip(),
            reason=reason.strip() if reason is not None else None,
        )
    except Exception:
        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=(
                CliIssue(
                    code="proposal_approval_failed",
                    message="The proposal approval workflow could not complete.",
                ),
            ),
            data={"proposal": None},
        )

    if confirmation.outcome is not OrchestrationOutcome.APPROVED:
        issue = confirmation.issue
        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=(
                CliIssue(
                    code=issue.code
                    if issue is not None
                    else "proposal_approval_rejected",
                    message=(
                        issue.message
                        if issue is not None
                        else "The proposal could not be approved."
                    ),
                ),
            ),
            data={"proposal": None},
        )

    replacement = repository.replace(
        confirmation.proposal,
        expected_status=ActionStatus.AWAITING_CONFIRMATION,
    )
    if not replacement.success:
        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=(
                CliIssue(
                    code="proposal_approval_partial_persistence",
                    message=(
                        "The approval audit event was persisted, but the "
                        "proposal document could not be replaced."
                    ),
                ),
                *tuple(
                    CliIssue(
                        code=issue.code,
                        message=issue.message,
                        field=issue.field,
                    )
                    for issue in replacement.issues
                ),
            ),
            data={
                "proposal": proposal_to_dict(confirmation.proposal),
                "audit_persisted": True,
                "proposal_persisted": False,
            },
        )

    decision = confirmation.decision_application
    record = decision.record if decision is not None else None
    return CliResult.succeeded(
        data={
            "proposal": proposal_to_dict(confirmation.proposal),
            "audit_persisted": True,
            "proposal_persisted": True,
            "actor": record.actor if record is not None else actor.strip(),
            "reason": record.reason if record is not None else reason,
            "decided_at": (
                record.decided_at.isoformat() if record is not None else None
            ),
        }
    )


def render_proposal_approve_result(result: CliResult) -> str:
    if not result.success:
        return _render_issues(result)

    data = result.data
    if not isinstance(data, dict):
        return _render_issues(result)

    proposal = data.get("proposal")
    if not isinstance(proposal, dict):
        return _render_issues(result)

    return "\n".join(
        [
            "Proposal approved.",
            f"Proposal ID: {proposal.get('proposal_id', 'not available')}",
            f"Status: {proposal.get('status', 'not available')}",
            f"Actor: {data.get('actor', 'not available')}",
            f"Reason: {data.get('reason') or 'not provided'}",
            f"Audit persisted: {str(data.get('audit_persisted')).lower()}",
            f"Proposal persisted: {str(data.get('proposal_persisted')).lower()}",
        ]
    )


def execute_proposal_reject(
    *,
    config_path: Path,
    expected_profile: RuntimeProfile | None,
    proposal_id: str,
    actor: str,
    reason: str | None,
    dependencies: ProposalCommandDependencies | None = None,
) -> CliResult:
    """Reject one persistent proposal awaiting confirmation."""
    validation = _validate_proposal_id(proposal_id)
    if validation is not None:
        return validation

    if not actor.strip():
        return CliResult.failed(
            exit_code=LocalCliExitCode.VALIDATION_ERROR,
            issues=(
                CliIssue(
                    code="proposal_actor_invalid",
                    message="--actor must be a non-empty string.",
                    field="actor",
                ),
            ),
            data={"proposal": None},
        )

    if reason is not None and not reason.strip():
        return CliResult.failed(
            exit_code=LocalCliExitCode.VALIDATION_ERROR,
            issues=(
                CliIssue(
                    code="proposal_reason_invalid",
                    message="--reason must be non-empty when provided.",
                    field="reason",
                ),
            ),
            data={"proposal": None},
        )

    resolved = dependencies or ProposalCommandDependencies()
    configuration = resolved.load_configuration(config_path)
    if not configuration.success:
        return _configuration_failure(configuration)

    config = configuration.config
    if config is None:
        return _internal_failure(
            "Successful configuration loading returned no runtime configuration."
        )

    if expected_profile is not None and config.profile is not expected_profile:
        return _profile_mismatch_failure()

    repository = resolved.create_repository(config)
    read_result = repository.read(proposal_id)
    if not read_result.success:
        return _map_proposal_read_failure(read_result)

    proposal = read_result.proposal
    if proposal is None:
        return _internal_failure("Successful proposal reading returned no proposal.")

    try:
        audit_store = resolved.create_audit_store(config)
        orchestrator = resolved.create_orchestrator(audit_store)
        confirmation = orchestrator.confirm(
            proposal,
            ConfirmationDecision.REJECTED,
            actor.strip(),
            reason=reason.strip() if reason is not None else None,
        )
    except Exception:
        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=(
                CliIssue(
                    code="proposal_rejection_failed",
                    message="The proposal rejection workflow could not complete.",
                ),
            ),
            data={"proposal": None},
        )

    if confirmation.outcome is not OrchestrationOutcome.REJECTED:
        issue = confirmation.issue
        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=(
                CliIssue(
                    code=(
                        issue.code
                        if issue is not None
                        else "proposal_rejection_rejected"
                    ),
                    message=(
                        issue.message
                        if issue is not None
                        else "The proposal could not be rejected."
                    ),
                ),
            ),
            data={"proposal": None},
        )

    replacement = repository.replace(
        confirmation.proposal,
        expected_status=ActionStatus.AWAITING_CONFIRMATION,
    )
    if not replacement.success:
        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=(
                CliIssue(
                    code="proposal_rejection_partial_persistence",
                    message=(
                        "The rejection audit event was persisted, but the "
                        "proposal document could not be replaced."
                    ),
                ),
                *tuple(
                    CliIssue(
                        code=issue.code,
                        message=issue.message,
                        field=issue.field,
                    )
                    for issue in replacement.issues
                ),
            ),
            data={
                "proposal": proposal_to_dict(confirmation.proposal),
                "audit_persisted": True,
                "proposal_persisted": False,
            },
        )

    decision = confirmation.decision_application
    record = decision.record if decision is not None else None
    return CliResult.succeeded(
        data={
            "proposal": proposal_to_dict(confirmation.proposal),
            "audit_persisted": True,
            "proposal_persisted": True,
            "actor": record.actor if record is not None else actor.strip(),
            "reason": record.reason if record is not None else reason,
            "decided_at": (
                record.decided_at.isoformat() if record is not None else None
            ),
        }
    )


def render_proposal_reject_result(result: CliResult) -> str:
    """Render one stable human-readable proposal rejection result."""
    if not result.success:
        return _render_issues(result)

    data = result.data
    if not isinstance(data, dict):
        return _render_issues(result)

    proposal = data.get("proposal")
    if not isinstance(proposal, dict):
        return _render_issues(result)

    return "\n".join(
        [
            "Proposal rejected.",
            f"Proposal ID: {proposal.get('proposal_id', 'not available')}",
            f"Status: {proposal.get('status', 'not available')}",
            f"Actor: {data.get('actor', 'not available')}",
            f"Reason: {data.get('reason') or 'not provided'}",
            f"Audit persisted: {str(data.get('audit_persisted')).lower()}",
            f"Proposal persisted: {str(data.get('proposal_persisted')).lower()}",
        ]
    )


def execute_proposal_cancel(
    *,
    config_path: Path,
    expected_profile: RuntimeProfile | None,
    proposal_id: str,
    actor: str,
    reason: str | None,
    dependencies: ProposalCommandDependencies | None = None,
) -> CliResult:
    """Cancel one persistent proposal awaiting confirmation."""
    validation = _validate_proposal_id(proposal_id)
    if validation is not None:
        return validation

    if not actor.strip():
        return CliResult.failed(
            exit_code=LocalCliExitCode.VALIDATION_ERROR,
            issues=(
                CliIssue(
                    code="proposal_actor_invalid",
                    message="--actor must be a non-empty string.",
                    field="actor",
                ),
            ),
            data={"proposal": None},
        )

    if reason is not None and not reason.strip():
        return CliResult.failed(
            exit_code=LocalCliExitCode.VALIDATION_ERROR,
            issues=(
                CliIssue(
                    code="proposal_reason_invalid",
                    message="--reason must be non-empty when provided.",
                    field="reason",
                ),
            ),
            data={"proposal": None},
        )

    resolved = dependencies or ProposalCommandDependencies()
    configuration = resolved.load_configuration(config_path)
    if not configuration.success:
        return _configuration_failure(configuration)

    config = configuration.config
    if config is None:
        return _internal_failure(
            "Successful configuration loading returned no runtime configuration."
        )

    if expected_profile is not None and config.profile is not expected_profile:
        return _profile_mismatch_failure()

    repository = resolved.create_repository(config)
    read_result = repository.read(proposal_id)
    if not read_result.success:
        return _map_proposal_read_failure(read_result)

    proposal = read_result.proposal
    if proposal is None:
        return _internal_failure("Successful proposal reading returned no proposal.")

    try:
        audit_store = resolved.create_audit_store(config)
        orchestrator = resolved.create_orchestrator(audit_store)
        confirmation = orchestrator.confirm(
            proposal,
            ConfirmationDecision.CANCELLED,
            actor.strip(),
            reason=reason.strip() if reason is not None else None,
        )
    except Exception:
        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=(
                CliIssue(
                    code="proposal_cancellation_failed",
                    message="The proposal cancellation workflow could not complete.",
                ),
            ),
            data={"proposal": None},
        )

    if confirmation.outcome is not OrchestrationOutcome.CANCELLED:
        issue = confirmation.issue
        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=(
                CliIssue(
                    code=(
                        issue.code
                        if issue is not None
                        else "proposal_cancellation_rejected"
                    ),
                    message=(
                        issue.message
                        if issue is not None
                        else "The proposal could not be cancelled."
                    ),
                ),
            ),
            data={"proposal": None},
        )

    replacement = repository.replace(
        confirmation.proposal,
        expected_status=ActionStatus.AWAITING_CONFIRMATION,
    )
    if not replacement.success:
        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=(
                CliIssue(
                    code="proposal_cancellation_partial_persistence",
                    message=(
                        "The cancellation audit event was persisted, but the "
                        "proposal document could not be replaced."
                    ),
                ),
                *tuple(
                    CliIssue(
                        code=issue.code,
                        message=issue.message,
                        field=issue.field,
                    )
                    for issue in replacement.issues
                ),
            ),
            data={
                "proposal": proposal_to_dict(confirmation.proposal),
                "audit_persisted": True,
                "proposal_persisted": False,
            },
        )

    decision = confirmation.decision_application
    record = decision.record if decision is not None else None
    return CliResult.succeeded(
        data={
            "proposal": proposal_to_dict(confirmation.proposal),
            "audit_persisted": True,
            "proposal_persisted": True,
            "actor": record.actor if record is not None else actor.strip(),
            "reason": record.reason if record is not None else reason,
            "decided_at": (
                record.decided_at.isoformat() if record is not None else None
            ),
        }
    )


def render_proposal_cancel_result(result: CliResult) -> str:
    """Render one stable human-readable proposal cancellation result."""
    if not result.success:
        return _render_issues(result)

    data = result.data
    if not isinstance(data, dict):
        return _render_issues(result)

    proposal = data.get("proposal")
    if not isinstance(proposal, dict):
        return _render_issues(result)

    return "\n".join(
        [
            "Proposal cancelled.",
            f"Proposal ID: {proposal.get('proposal_id', 'not available')}",
            f"Status: {proposal.get('status', 'not available')}",
            f"Actor: {data.get('actor', 'not available')}",
            f"Reason: {data.get('reason') or 'not provided'}",
            f"Audit persisted: {str(data.get('audit_persisted')).lower()}",
            f"Proposal persisted: {str(data.get('proposal_persisted')).lower()}",
        ]
    )


def render_proposal_show_result(result: CliResult) -> str:
    """Render one stable human-readable proposal detail view."""
    data = result.data

    if not isinstance(data, dict):
        return _render_issues(result)

    raw_proposal = data.get("proposal")
    display_timezone = data.get("display_timezone")

    if not isinstance(raw_proposal, dict):
        return _render_issues(result)

    if not isinstance(display_timezone, str):
        return _render_issues(result)

    proposal = cast(dict[str, object], raw_proposal)
    raw_created_at = proposal.get("created_at")

    if isinstance(raw_created_at, str):
        canonical = datetime.fromisoformat(raw_created_at)
        localised = localise_utc_timestamp(
            canonical,
            display_timezone=display_timezone,
        )
        created_at = localised.isoformat(timespec="seconds")
    else:
        created_at = "not available"

    parameters = proposal.get("parameters")
    if isinstance(parameters, dict):
        import json

        rendered_parameters = json.dumps(
            parameters,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    else:
        rendered_parameters = "not available"

    reason = proposal.get("reason")
    reason_text = "not provided" if reason is None else str(reason)

    verified = "verified" if data.get("repository_verified") is True else "not verified"

    return "\n".join(
        [
            "Proposal",
            "",
            f"Proposal ID: {proposal.get('proposal_id', 'not available')}",
            f"Action: {proposal.get('action', 'not available')}",
            f"Status: {proposal.get('status', 'not available')}",
            f"Risk level: {proposal.get('risk_level', 'not available')}",
            (
                "Confirmation policy: "
                f"{proposal.get('confirmation_policy', 'not available')}"
            ),
            f"Source: {proposal.get('source', 'not available')}",
            f"Created: {created_at}",
            f"Repository: {verified}",
            f"Reason: {reason_text}",
            "",
            "Parameters:",
            rendered_parameters,
        ]
    )


def _validate_proposal_id(proposal_id: str) -> CliResult | None:
    """Validate one canonical lower-case proposal UUID."""
    from uuid import UUID

    try:
        parsed = UUID(proposal_id)
    except ValueError:
        return CliResult.failed(
            exit_code=LocalCliExitCode.VALIDATION_ERROR,
            issues=(
                CliIssue(
                    code="proposal_id_invalid",
                    message="proposal_id must be a valid UUID.",
                    field="proposal_id",
                ),
            ),
            data={"proposal": None},
        )

    if str(parsed) != proposal_id:
        return CliResult.failed(
            exit_code=LocalCliExitCode.VALIDATION_ERROR,
            issues=(
                CliIssue(
                    code="proposal_id_invalid",
                    message=("proposal_id must use canonical lower-case UUID format."),
                    field="proposal_id",
                ),
            ),
            data={"proposal": None},
        )

    return None


def render_proposal_list_result(result: CliResult) -> str:
    """Render one stable human-readable proposal list."""
    data = result.data

    if not isinstance(data, dict):
        return _render_issues(result)

    proposals = data.get("proposals")

    if not isinstance(proposals, list):
        return _render_issues(result)

    if not proposals:
        return "No proposals found." if result.success else _render_issues(result)

    display_timezone = data.get("display_timezone")

    if not isinstance(display_timezone, str):
        return _render_issues(result)

    lines = [
        "Proposals",
        "",
        (
            "Created                    Status                 "
            "Action                Proposal ID"
        ),
    ]

    for raw_proposal in proposals:
        if not isinstance(raw_proposal, dict):
            continue

        proposal = cast(dict[str, object], raw_proposal)
        lines.append(
            _render_proposal_summary(
                proposal,
                display_timezone=display_timezone,
            )
        )

    return "\n".join(lines)


def _render_proposal_summary(
    proposal: dict[str, object],
    *,
    display_timezone: str,
) -> str:
    """Render one proposal summary row."""
    raw_created_at = proposal.get("created_at")

    if not isinstance(raw_created_at, str):
        created_at = "not available"
    else:
        canonical = datetime.fromisoformat(raw_created_at)
        localised = localise_utc_timestamp(
            canonical,
            display_timezone=display_timezone,
        )
        created_at = localised.isoformat(timespec="seconds")

    status = str(proposal.get("status", "not available"))
    action = str(proposal.get("action", "not available"))
    proposal_id = str(proposal.get("proposal_id", "not available"))

    return f"{created_at:<26} {status:<22} {action:<21} {proposal_id}"


def _map_repository_failure(result: ProposalListResult) -> CliResult:
    """Map repository listing failures into Local CLI results."""
    return CliResult.failed(
        exit_code=LocalCliExitCode.APPLICATION_ERROR,
        issues=tuple(
            CliIssue(
                code=issue.code,
                message=issue.message,
                field=issue.field,
            )
            for issue in result.issues
        ),
        data={"proposals": []},
    )


def _configuration_failure(configuration: ConfigurationResult) -> CliResult:
    return CliResult.failed(
        exit_code=LocalCliExitCode.CONFIGURATION_ERROR,
        issues=tuple(
            CliIssue(code=issue.code, message=issue.message, field=issue.field)
            for issue in configuration.issues
        ),
        data={"proposal": None},
    )


def _profile_mismatch_failure() -> CliResult:
    return CliResult.failed(
        exit_code=LocalCliExitCode.CONFIGURATION_ERROR,
        issues=(
            CliIssue(
                code="configuration_profile_mismatch",
                message=(
                    "The loaded runtime profile does not match the requested profile."
                ),
                field="profile",
            ),
        ),
        data={"proposal": None},
    )


def _map_proposal_read_failure(result: ProposalReadResult) -> CliResult:
    return CliResult.failed(
        exit_code=LocalCliExitCode.APPLICATION_ERROR,
        issues=tuple(
            CliIssue(code=issue.code, message=issue.message, field=issue.field)
            for issue in result.issues
        ),
        data={"proposal": None},
    )


def _render_issues(result: CliResult) -> str:
    """Render proposal command issues."""
    if not result.issues:
        return "Proposal listing is unavailable."

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
        data={"proposals": []},
    )
