"""Tests for the Local CLI proposal-cancellation command."""

from datetime import UTC, datetime
from pathlib import Path

from lea.actions import ActionHandlerRegistry, ActionProposal, ActionStatus
from lea.audit import IntegrityJsonlAuditStore
from lea.cli import LocalCliExitCode
from lea.cli.proposal_commands import (
    ProposalCommandDependencies,
    execute_proposal_cancel,
    render_proposal_cancel_result,
)
from lea.orchestration import ActionOrchestrator
from lea.proposals import MarkdownProposalRepository
from lea.runtime import (
    ConfigurationResult,
    RuntimeProfile,
    isolated_test_runtime_config,
)

PROPOSAL_ID = "11111111-1111-4111-8111-111111111111"
EVENT_ID = "55555555-5555-4555-8555-555555555555"
DECIDED_AT = datetime(2026, 7, 22, 14, 0, tzinfo=UTC)


def _proposal(
    *, status: ActionStatus = ActionStatus.AWAITING_CONFIRMATION
) -> ActionProposal:
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.modify",
        parameters={"uuid": "66666666-6666-4666-8666-666666666666"},
        status=status,
        source="test",
        created_at=datetime(2026, 7, 22, 10, 0, tzinfo=UTC),
        reason="Modify one test task.",
    )


def _configuration(tmp_path: Path) -> ConfigurationResult:
    config = isolated_test_runtime_config(tmp_path / "runtime")
    config.paths.proposal_dir.mkdir(parents=True)
    config.paths.audit_dir.mkdir(parents=True)
    return ConfigurationResult(success=True, config=config, issues=())


def _dependencies(
    tmp_path: Path,
    *,
    status: ActionStatus = ActionStatus.AWAITING_CONFIRMATION,
) -> ProposalCommandDependencies:
    configuration = _configuration(tmp_path)
    assert configuration.config is not None
    config = configuration.config
    repository = MarkdownProposalRepository(config.paths.proposal_dir)
    assert repository.create(_proposal(status=status)).success is True

    return ProposalCommandDependencies(
        load_configuration=lambda path: configuration,
        create_repository=lambda runtime: repository,
        create_audit_store=lambda runtime: IntegrityJsonlAuditStore(
            config.paths.audit_file
        ),
        create_orchestrator=lambda store: ActionOrchestrator(
            ActionHandlerRegistry(),
            store,
            lambda: DECIDED_AT,
            lambda: EVENT_ID,
        ),
    )


def test_cancel_persists_audit_and_replacement(tmp_path: Path) -> None:
    result = execute_proposal_cancel(
        config_path=tmp_path / "lea.toml",
        expected_profile=RuntimeProfile.TEST,
        proposal_id=PROPOSAL_ID,
        actor="Marius",
        reason="No longer required.",
        dependencies=_dependencies(tmp_path),
    )

    assert result.success is True
    assert isinstance(result.data, dict)

    proposal_data = result.data.get("proposal")
    assert isinstance(proposal_data, dict)

    assert proposal_data["status"] == "cancelled"
    assert result.data["audit_persisted"] is True
    assert result.data["proposal_persisted"] is True
    assert result.data["actor"] == "Marius"
    assert result.data["reason"] == "No longer required."
    assert "Proposal cancelled." in render_proposal_cancel_result(result)


def test_cancel_allows_omitted_reason(tmp_path: Path) -> None:
    result = execute_proposal_cancel(
        config_path=tmp_path / "lea.toml",
        expected_profile=None,
        proposal_id=PROPOSAL_ID,
        actor="Marius",
        reason=None,
        dependencies=_dependencies(tmp_path),
    )

    assert result.success is True
    assert isinstance(result.data, dict)
    assert result.data["reason"] is None


def test_cancel_rejects_blank_actor_before_configuration() -> None:
    called = False

    def unexpected_loader(path: object) -> ConfigurationResult:
        nonlocal called
        called = True
        raise AssertionError

    result = execute_proposal_cancel(
        config_path=Path("/tmp/lea.toml"),
        expected_profile=None,
        proposal_id=PROPOSAL_ID,
        actor="   ",
        reason=None,
        dependencies=ProposalCommandDependencies(
            load_configuration=unexpected_loader,
        ),
    )

    assert result.exit_code is LocalCliExitCode.VALIDATION_ERROR
    assert result.issues[0].code == "proposal_actor_invalid"
    assert called is False


def test_cancel_rejects_blank_supplied_reason() -> None:
    result = execute_proposal_cancel(
        config_path=Path("/tmp/lea.toml"),
        expected_profile=None,
        proposal_id=PROPOSAL_ID,
        actor="Marius",
        reason="   ",
    )

    assert result.exit_code is LocalCliExitCode.VALIDATION_ERROR
    assert result.issues[0].code == "proposal_reason_invalid"


def test_cancel_rejects_invalid_proposal_state(tmp_path: Path) -> None:
    result = execute_proposal_cancel(
        config_path=tmp_path / "lea.toml",
        expected_profile=None,
        proposal_id=PROPOSAL_ID,
        actor="Marius",
        reason=None,
        dependencies=_dependencies(tmp_path, status=ActionStatus.APPROVED),
    )

    assert result.exit_code is LocalCliExitCode.APPLICATION_ERROR
    assert result.issues[0].code == "confirmation_decision_rejected"
