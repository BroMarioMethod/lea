"""Tests for the Local CLI proposal-show command."""

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from lea.actions import ActionProposal
from lea.cli import LocalCliExitCode
from lea.cli.proposal_commands import (
    ProposalCommandDependencies,
    execute_proposal_show,
    render_proposal_show_result,
)
from lea.proposals import (
    MarkdownProposalRepository,
    ProposalReadResult,
    ProposalRepositoryIssue,
)
from lea.runtime import (
    ConfigurationResult,
    RuntimeProfile,
    isolated_test_runtime_config,
)

PROPOSAL_ID = "11111111-1111-4111-8111-111111111111"


class RecordingRepository:
    """Return one deterministic proposal-read result."""

    def __init__(self, result: ProposalReadResult) -> None:
        self.result = result
        self.calls = 0
        self.proposal_ids: list[str] = []

    def read(self, proposal_id: str) -> ProposalReadResult:
        self.calls += 1
        self.proposal_ids.append(proposal_id)
        return self.result


def _proposal() -> ActionProposal:
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={"description": "Test task", "priority": 2},
        source="test",
        created_at=datetime(2026, 7, 22, 12, 0, tzinfo=UTC),
        reason="Create one test task.",
    )


def _configuration(tmp_path: Path) -> ConfigurationResult:
    config = isolated_test_runtime_config(
        tmp_path / "runtime",
        display_timezone="Africa/Gaborone",
    )
    return ConfigurationResult(success=True, config=config, issues=())


def test_proposal_show_returns_canonical_json_and_localised_human_time(
    tmp_path: Path,
) -> None:
    proposal = _proposal()
    repository = RecordingRepository(
        ProposalReadResult(
            success=True,
            proposal=proposal,
            path=tmp_path / "runtime" / "proposals" / f"{PROPOSAL_ID}.md",
            issues=(),
        )
    )

    result = execute_proposal_show(
        config_path=tmp_path / "runtime" / "config" / "lea.toml",
        expected_profile=RuntimeProfile.TEST,
        proposal_id=PROPOSAL_ID,
        dependencies=ProposalCommandDependencies(
            load_configuration=lambda path: _configuration(tmp_path),
            create_repository=lambda config: cast(
                MarkdownProposalRepository,
                repository,
            ),
        ),
    )

    assert result.success is True
    assert repository.proposal_ids == [PROPOSAL_ID]
    assert isinstance(result.data, dict)

    data = cast(dict[str, object], result.data)
    proposal_data = cast(dict[str, object], data["proposal"])

    assert proposal_data["created_at"] == "2026-07-22T12:00:00+00:00"
    assert data["repository_verified"] is True

    rendered = render_proposal_show_result(result)
    assert "Created: 2026-07-22T14:00:00+02:00" in rendered
    assert "Repository: verified" in rendered
    assert '"description": "Test task"' in rendered


def test_invalid_proposal_id_fails_before_configuration_access() -> None:
    called = False

    def unexpected_loader(path: object) -> ConfigurationResult:
        nonlocal called
        called = True
        raise AssertionError

    result = execute_proposal_show(
        config_path=Path("/tmp/lea.toml"),
        expected_profile=None,
        proposal_id="../proposal",
        dependencies=ProposalCommandDependencies(
            load_configuration=unexpected_loader,
        ),
    )

    assert result.exit_code is LocalCliExitCode.VALIDATION_ERROR
    assert result.issues[0].code == "proposal_id_invalid"
    assert called is False


def test_uppercase_proposal_id_is_rejected_before_repository_access(
    tmp_path: Path,
) -> None:
    result = execute_proposal_show(
        config_path=tmp_path / "runtime" / "config" / "lea.toml",
        expected_profile=None,
        proposal_id="AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
        dependencies=ProposalCommandDependencies(
            load_configuration=lambda path: _configuration(tmp_path),
        ),
    )

    assert result.exit_code is LocalCliExitCode.VALIDATION_ERROR
    assert "canonical lower-case" in result.issues[0].message


def test_missing_proposal_maps_to_application_error(tmp_path: Path) -> None:
    repository = RecordingRepository(
        ProposalReadResult(
            success=False,
            proposal=None,
            path=tmp_path / "runtime" / "proposals" / f"{PROPOSAL_ID}.md",
            issues=(
                ProposalRepositoryIssue(
                    code="proposal_not_found",
                    message="The proposal document was not found.",
                    proposal_id=PROPOSAL_ID,
                    path=(tmp_path / "runtime" / "proposals" / f"{PROPOSAL_ID}.md"),
                ),
            ),
        )
    )

    result = execute_proposal_show(
        config_path=tmp_path / "runtime" / "config" / "lea.toml",
        expected_profile=None,
        proposal_id=PROPOSAL_ID,
        dependencies=ProposalCommandDependencies(
            load_configuration=lambda path: _configuration(tmp_path),
            create_repository=lambda config: cast(
                MarkdownProposalRepository,
                repository,
            ),
        ),
    )

    assert result.exit_code is LocalCliExitCode.APPLICATION_ERROR
    assert result.issues[0].code == "proposal_not_found"
