"""Local CLI calendar proposal-submission services."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from lea.actions import (
    ActionProposal,
    ConfirmationPolicy,
    generate_proposal_id,
    proposal_to_dict,
)
from lea.cli.contracts import CliIssue, CliResult, LocalCliExitCode
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


@dataclass(frozen=True, slots=True)
class CalendarProposalCommandDependencies:
    """Injected dependencies for deterministic proposal submission."""

    load_configuration: ConfigurationLoader = load_runtime_config
    create_repository: ProposalRepositoryFactory = runtime_proposal_repository
    proposal_id_source: ProposalIdSource = generate_proposal_id
    clock: Clock = lambda: datetime.now(UTC)


def execute_calendar_proposal(
    *,
    config_path: Path,
    expected_profile: RuntimeProfile | None,
    build_proposal: Callable[[str, datetime], ActionProposal],
    dependencies: CalendarProposalCommandDependencies | None = None,
) -> CliResult:
    """Build and persist one always-confirm calendar proposal."""
    resolved = dependencies or CalendarProposalCommandDependencies()
    configuration = resolved.load_configuration(config_path)
    if not configuration.success:
        return CliResult.failed(
            exit_code=LocalCliExitCode.CONFIGURATION_ERROR,
            issues=tuple(
                CliIssue(code=issue.code, message=issue.message, field=issue.field)
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
            build_proposal(resolved.proposal_id_source(), resolved.clock()),
            confirmation_policy=ConfirmationPolicy.ALWAYS,
        )
    except (TypeError, ValueError) as error:
        return _failure(
            LocalCliExitCode.VALIDATION_ERROR,
            "calendar_proposal_invalid",
            str(error),
        )
    written = resolved.create_repository(config).create(proposal)
    if not written.success:
        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=tuple(
                CliIssue(code=issue.code, message=issue.message, field=issue.field)
                for issue in written.issues
            ),
            data={"proposal": None},
        )
    return CliResult.succeeded(
        data={
            "message": "Calendar proposal created",
            "proposal": proposal_to_dict(proposal),
            "path": str(written.path),
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
