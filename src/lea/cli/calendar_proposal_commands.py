"""Local CLI calendar proposal-submission services."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from lea.actions import (
    ActionHandlerRegistry,
    ActionProposal,
    ActionStatus,
    ConfirmationPolicy,
    generate_proposal_id,
    proposal_to_dict,
)
from lea.audit import IntegrityJsonlAuditStore, generate_event_id
from lea.cli.contracts import CliIssue, CliResult, LocalCliExitCode
from lea.orchestration import ActionOrchestrator, OrchestrationOutcome
from lea.proposals import MarkdownProposalRepository
from lea.runtime import (
    ConfigurationResult,
    RuntimeConfig,
    RuntimeProfile,
    load_runtime_config,
    runtime_proposal_repository,
)

ConfigurationLoader = Callable[[str | Path], ConfigurationResult]
ProposalRepositoryFactory = Callable[[RuntimeConfig], MarkdownProposalRepository]
ProposalIdSource = Callable[[], str]
Clock = Callable[[], datetime]


def _runtime_audit_store(
    config: RuntimeConfig,
) -> IntegrityJsonlAuditStore:
    """Create the canonical integrity-protected runtime audit store."""
    return IntegrityJsonlAuditStore(config.paths.audit_file)


def _runtime_orchestrator(
    audit_store: IntegrityJsonlAuditStore,
) -> ActionOrchestrator:
    """Create the non-executing proposal-submission orchestrator."""
    return ActionOrchestrator(
        ActionHandlerRegistry(),
        audit_store,
        lambda: datetime.now(UTC),
        generate_event_id,
    )


@dataclass(frozen=True, slots=True)
class CalendarProposalCommandDependencies:
    """Injected dependencies for deterministic proposal submission."""

    load_configuration: ConfigurationLoader = load_runtime_config
    create_repository: ProposalRepositoryFactory = runtime_proposal_repository
    proposal_id_source: ProposalIdSource = generate_proposal_id
    clock: Clock = lambda: datetime.now(UTC)
    create_audit_store: Callable[
        [RuntimeConfig],
        IntegrityJsonlAuditStore,
    ] = _runtime_audit_store
    create_orchestrator: Callable[
        [IntegrityJsonlAuditStore],
        ActionOrchestrator,
    ] = _runtime_orchestrator


def execute_calendar_proposal(
    *,
    config_path: Path,
    expected_profile: RuntimeProfile | None,
    build_proposal: Callable[[str, datetime], ActionProposal],
    dependencies: CalendarProposalCommandDependencies | None = None,
) -> CliResult:
    """Submit and persist one always-confirm calendar proposal."""
    resolved = dependencies or CalendarProposalCommandDependencies()
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
        return _failure(
            LocalCliExitCode.INTERNAL_ERROR,
            "internal_error",
            "Successful configuration loading returned no runtime configuration.",
        )

    if expected_profile is not None and config.profile is not expected_profile:
        return _failure(
            LocalCliExitCode.CONFIGURATION_ERROR,
            "configuration_profile_mismatch",
            "The loaded runtime profile does not match the requested profile.",
            field="profile",
        )

    try:
        proposal = replace(
            build_proposal(
                resolved.proposal_id_source(),
                resolved.clock(),
            ),
            confirmation_policy=ConfirmationPolicy.ALWAYS,
        )
    except (TypeError, ValueError) as error:
        return _failure(
            LocalCliExitCode.VALIDATION_ERROR,
            "calendar_proposal_invalid",
            str(error),
        )

    try:
        audit_store = resolved.create_audit_store(config)
        orchestrator = resolved.create_orchestrator(audit_store)
        submission = orchestrator.submit(proposal)
    except Exception:
        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=(
                CliIssue(
                    code="calendar_proposal_submission_failed",
                    message=(
                        "The calendar proposal submission workflow could not complete."
                    ),
                ),
            ),
            data={
                "proposal": proposal_to_dict(proposal),
                "audit_persisted": False,
                "proposal_persisted": False,
            },
        )

    audit_persisted = bool(submission.persisted_events)

    if (
        submission.outcome is not OrchestrationOutcome.CONFIRMATION_REQUIRED
        or submission.proposal.status is not ActionStatus.AWAITING_CONFIRMATION
        or not audit_persisted
    ):
        issue = submission.issue

        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=(
                CliIssue(
                    code=(
                        issue.code
                        if issue is not None
                        else "calendar_proposal_submission_rejected"
                    ),
                    message=(
                        issue.message
                        if issue is not None
                        else (
                            "The calendar proposal did not enter "
                            "awaiting-confirmation state."
                        )
                    ),
                ),
            ),
            data={
                "proposal": proposal_to_dict(submission.proposal),
                "audit_persisted": audit_persisted,
                "proposal_persisted": False,
            },
        )

    written = resolved.create_repository(config).create(submission.proposal)

    if not written.success:
        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=(
                CliIssue(
                    code=("calendar_proposal_submission_partial_persistence"),
                    message=(
                        "The submission audit events were persisted, "
                        "but the proposal document could not be created."
                    ),
                ),
                *tuple(
                    CliIssue(
                        code=issue.code,
                        message=issue.message,
                        field=issue.field,
                    )
                    for issue in written.issues
                ),
            ),
            data={
                "proposal": proposal_to_dict(submission.proposal),
                "audit_persisted": True,
                "proposal_persisted": False,
            },
        )

    return CliResult.succeeded(
        data={
            "message": "Calendar proposal created",
            "proposal": proposal_to_dict(submission.proposal),
            "path": str(written.path),
            "audit_persisted": True,
            "proposal_persisted": True,
        }
    )


def render_calendar_proposal_result(result: CliResult) -> str:
    """Render one stable proposal-submission result."""
    if not result.success:
        return "\n".join(issue.message for issue in result.issues)
    proposal = result.data.get("proposal") if isinstance(result.data, dict) else None
    if not isinstance(proposal, dict):
        return "Calendar proposal could not be rendered."
    return "\n".join(
        (
            "Calendar proposal created",
            "",
            f"ID: {proposal['proposal_id']}",
            f"Action: {proposal['action']}",
            "Approval and explicit execution are required.",
        )
    )


def _failure(
    exit_code: LocalCliExitCode,
    code: str,
    message: str,
    *,
    field: str | None = None,
) -> CliResult:
    return CliResult.failed(
        exit_code=exit_code,
        issues=(CliIssue(code=code, message=message, field=field),),
        data={"proposal": None},
    )
