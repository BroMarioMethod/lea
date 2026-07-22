"""Tests for the Local CLI proposal-execution command."""

from datetime import UTC, datetime
from pathlib import Path

from lea.actions import ActionProposal, ActionStatus
from lea.audit import IntegrityJsonlAuditStore
from lea.cli import LocalCliExitCode
from lea.cli.proposal_commands import (
    ProposalCommandDependencies,
    execute_proposal_execute,
    render_proposal_execute_result,
)
from lea.cli.task_provider import TaskProviderDependencies
from lea.installers.taskwarrior import TaskwarriorInstallationRecord
from lea.orchestration import ActionOrchestrator
from lea.proposals import MarkdownProposalRepository
from lea.runtime import (
    ConfigurationResult,
    RuntimeProfile,
    isolated_test_runtime_config,
)
from lea.tasks import (
    TaskCreateRequest,
    TaskCreateResult,
    TaskListQuery,
    TaskListResult,
    TaskModifyRequest,
    TaskMutationResult,
    TaskProviderInspectionResult,
    TaskRecord,
    TaskStatus,
)

PROPOSAL_ID = "11111111-1111-4111-8111-111111111111"
TASK_UUID = "22222222-2222-4222-8222-222222222222"
EVENT_ID = "33333333-3333-4333-8333-333333333333"
STARTED_AT = datetime(2026, 7, 22, 15, 0, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 7, 22, 15, 0, 1, tzinfo=UTC)


class RecordingProvider:
    def __init__(self, result: TaskCreateResult) -> None:
        self.result = result
        self.requests: list[TaskCreateRequest] = []

    def inspect(self) -> TaskProviderInspectionResult:
        return TaskProviderInspectionResult(
            available=True, provider="test", version="1.0", issues=()
        )

    def create_task(self, request: TaskCreateRequest) -> TaskCreateResult:
        self.requests.append(request)
        return self.result

    def list_tasks(self, query: TaskListQuery) -> TaskListResult:
        raise AssertionError

    def modify_task(self, request: TaskModifyRequest) -> TaskMutationResult:
        raise AssertionError

    def complete_task(self, task_uuid: str) -> TaskMutationResult:
        raise AssertionError

    def delete_task(self, task_uuid: str) -> TaskMutationResult:
        raise AssertionError


def _configuration(tmp_path: Path) -> ConfigurationResult:
    config = isolated_test_runtime_config(tmp_path / "runtime")
    config.paths.proposal_dir.mkdir(parents=True)
    config.paths.audit_dir.mkdir(parents=True)
    return ConfigurationResult(success=True, config=config, issues=())


def _record(tmp_path: Path) -> TaskwarriorInstallationRecord:
    root = tmp_path / "taskwarrior"
    return TaskwarriorInstallationRecord(
        schema_version=1,
        component="taskwarrior",
        version="3.4.2",
        mode="local",
        platform="linux-aarch64",
        executable=root / "bin" / "task",
        taskrc=root / "taskrc",
        home=root / "home",
        data=root / "data",
        sha256="0" * 64,
        smoke_test="passed",
        installed_at=datetime(2026, 7, 22, tzinfo=UTC),
    )


def _dependencies(
    tmp_path: Path,
    provider: RecordingProvider,
    *,
    status: ActionStatus = ActionStatus.APPROVED,
) -> ProposalCommandDependencies:
    configuration = _configuration(tmp_path)
    assert configuration.config is not None
    config = configuration.config
    repository = MarkdownProposalRepository(config.paths.proposal_dir)
    proposal = ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={"description": "Execute proposal task"},
        status=status,
        source="test",
        created_at=datetime(2026, 7, 22, 10, 0, tzinfo=UTC),
    )
    assert repository.create(proposal).success is True
    timestamps = iter((STARTED_AT, COMPLETED_AT))
    return ProposalCommandDependencies(
        load_configuration=lambda path: configuration,
        create_repository=lambda runtime: repository,
        create_audit_store=lambda runtime: IntegrityJsonlAuditStore(
            config.paths.audit_file
        ),
        create_execution_orchestrator=lambda registry, store: ActionOrchestrator(
            registry, store, lambda: next(timestamps), lambda: EVENT_ID
        ),
        task_provider_dependencies=TaskProviderDependencies(
            load_configuration=lambda path: configuration,
            read_installation_record=lambda path: (_record(tmp_path), ()),
            create_provider=lambda provider_config: provider,
        ),
    )


def _provider() -> RecordingProvider:
    task = TaskRecord(
        uuid=TASK_UUID,
        description="Execute proposal task",
        status=TaskStatus.PENDING,
        entry=COMPLETED_AT,
    )
    return RecordingProvider(TaskCreateResult(success=True, task=task, issues=()))


def test_execute_persists_successful_execution(tmp_path: Path) -> None:
    provider = _provider()
    result = execute_proposal_execute(
        config_path=tmp_path / "lea.toml",
        expected_profile=RuntimeProfile.TEST,
        proposal_id=PROPOSAL_ID,
        dependencies=_dependencies(tmp_path, provider),
    )
    assert result.success is True
    assert result.exit_code is LocalCliExitCode.SUCCESS
    assert len(provider.requests) == 1
    assert isinstance(result.data, dict)
    assert result.data["audit_persisted"] is True
    assert result.data["proposal_persisted"] is True
    proposal = result.data["proposal"]
    assert isinstance(proposal, dict)
    assert proposal["status"] == "succeeded"
    assert "Proposal executed." in render_proposal_execute_result(result)


def test_execute_rejects_non_approved_proposal(tmp_path: Path) -> None:
    result = execute_proposal_execute(
        config_path=tmp_path / "lea.toml",
        expected_profile=None,
        proposal_id=PROPOSAL_ID,
        dependencies=_dependencies(
            tmp_path, _provider(), status=ActionStatus.AWAITING_CONFIRMATION
        ),
    )
    assert result.exit_code is LocalCliExitCode.APPLICATION_ERROR
    assert result.issues[0].code == "execution_rejected"
