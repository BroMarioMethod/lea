"""Tests for the Local CLI proposal-list command."""

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from lea.actions import (
    ActionProposal,
    ActionStatus,
    ConfirmationPolicy,
    RiskLevel,
)
from lea.cli import LocalCliExitCode
from lea.cli.proposal_commands import (
    ProposalCommandDependencies,
    execute_proposal_list,
    render_proposal_list_result,
)
from lea.proposals import (
    MarkdownProposalRepository,
    ProposalListResult,
    ProposalRepositoryIssue,
)
from lea.runtime import (
    ConfigurationResult,
    RuntimeProfile,
    isolated_test_runtime_config,
)

FIRST_ID = "11111111-1111-4111-8111-111111111111"
SECOND_ID = "22222222-2222-4222-8222-222222222222"


class RecordingRepository:
    """Return one deterministic proposal-list result."""

    def __init__(self, result: ProposalListResult) -> None:
        self.result = result
        self.calls = 0

    def list_all(self) -> ProposalListResult:
        self.calls += 1
        return self.result


def _proposal(
    proposal_id: str,
    *,
    minute: int,
    action: str = "task.create",
    status: ActionStatus = ActionStatus.PROPOSED,
) -> ActionProposal:
    return ActionProposal(
        proposal_id=proposal_id,
        action=action,
        parameters={"description": proposal_id},
        status=status,
        risk_level=RiskLevel.MEDIUM,
        confirmation_policy=ConfirmationPolicy.WHEN_REQUIRED,
        source="test",
        created_at=datetime(2026, 7, 22, 12, minute, tzinfo=UTC),
    )


def _configuration(tmp_path: Path) -> ConfigurationResult:
    config = isolated_test_runtime_config(
        tmp_path / "runtime",
        display_timezone="Africa/Gaborone",
    )
    return ConfigurationResult(success=True, config=config, issues=())


def test_proposal_list_returns_newest_first_and_localises_human_time(
    tmp_path: Path,
) -> None:
    repository = RecordingRepository(
        ProposalListResult(
            success=True,
            proposals=(
                _proposal(FIRST_ID, minute=0),
                _proposal(SECOND_ID, minute=1),
            ),
            issues=(),
        )
    )

    result = execute_proposal_list(
        config_path=tmp_path / "runtime" / "config" / "lea.toml",
        expected_profile=RuntimeProfile.TEST,
        status=None,
        action_type=None,
        limit=None,
        dependencies=ProposalCommandDependencies(
            load_configuration=lambda path: _configuration(tmp_path),
            create_repository=lambda config: cast(
                MarkdownProposalRepository,
                repository,
            ),
        ),
    )

    assert result.success is True
    assert isinstance(result.data, dict)
    data = cast(dict[str, object], result.data)
    proposals = cast(list[dict[str, object]], data["proposals"])
    assert [proposal["proposal_id"] for proposal in proposals] == [
        SECOND_ID,
        FIRST_ID,
    ]
    assert "2026-07-22T14:01:00+02:00" in render_proposal_list_result(result)


def test_proposal_list_applies_exact_filters_and_limit(
    tmp_path: Path,
) -> None:
    third_id = "33333333-3333-4333-8333-333333333333"
    repository = RecordingRepository(
        ProposalListResult(
            success=True,
            proposals=(
                _proposal(FIRST_ID, minute=0, action="task.create"),
                _proposal(
                    SECOND_ID,
                    minute=1,
                    action="task.modify",
                    status=ActionStatus.APPROVED,
                ),
                _proposal(
                    third_id,
                    minute=2,
                    action="task.modify",
                    status=ActionStatus.APPROVED,
                ),
            ),
            issues=(),
        )
    )

    result = execute_proposal_list(
        config_path=tmp_path / "runtime" / "config" / "lea.toml",
        expected_profile=None,
        status=ActionStatus.APPROVED,
        action_type="task.modify",
        limit=1,
        dependencies=ProposalCommandDependencies(
            load_configuration=lambda path: _configuration(tmp_path),
            create_repository=lambda config: cast(
                MarkdownProposalRepository,
                repository,
            ),
        ),
    )

    data = cast(dict[str, object], result.data)
    proposals = cast(list[dict[str, object]], data["proposals"])
    assert [proposal["proposal_id"] for proposal in proposals] == [third_id]


def test_invalid_limit_fails_before_configuration_or_repository_access() -> None:
    called = False

    def unexpected_loader(path: object) -> ConfigurationResult:
        nonlocal called
        called = True
        raise AssertionError

    result = execute_proposal_list(
        config_path=Path("/tmp/lea.toml"),
        expected_profile=None,
        status=None,
        action_type=None,
        limit=0,
        dependencies=ProposalCommandDependencies(
            load_configuration=unexpected_loader,
        ),
    )

    assert result.exit_code is LocalCliExitCode.VALIDATION_ERROR
    assert called is False


def test_repository_failure_maps_to_application_error(tmp_path: Path) -> None:
    repository = RecordingRepository(
        ProposalListResult(
            success=False,
            proposals=(),
            issues=(
                ProposalRepositoryIssue(
                    code="proposal_read_failed",
                    message="The repository could not be read.",
                    path=tmp_path / "runtime" / "proposals",
                ),
            ),
        )
    )

    result = execute_proposal_list(
        config_path=tmp_path / "runtime" / "config" / "lea.toml",
        expected_profile=None,
        status=None,
        action_type=None,
        limit=None,
        dependencies=ProposalCommandDependencies(
            load_configuration=lambda path: _configuration(tmp_path),
            create_repository=lambda config: cast(
                MarkdownProposalRepository,
                repository,
            ),
        ),
    )

    assert result.exit_code is LocalCliExitCode.APPLICATION_ERROR
    assert result.issues[0].code == "proposal_read_failed"
