"""End-to-end regression tests for channel task proposal lifecycles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from lea.actions import ActionHandlerRegistry, ActionStatus, RiskLevel
from lea.adapters.taskwarrior import TaskwarriorConfig
from lea.audit import IntegrityJsonlAuditStore
from lea.channels import (
    ChannelIdentity,
    ChannelName,
    ChannelRequest,
    ChannelRequestType,
    ChannelResponseOutcome,
)
from lea.channels.application import (
    ChannelApplicationResult,
    DispatchingChannelApplication,
)
from lea.channels.handlers import (
    ChannelHandlerDependencies,
    build_default_channel_application,
)
from lea.cli.proposal_commands import ProposalCommandDependencies
from lea.cli.task_provider import TaskProviderDependencies
from lea.installers.taskwarrior import TaskwarriorInstallationRecord
from lea.orchestration import ActionOrchestrator
from lea.proposals import (
    MarkdownProposalRepository,
    ProposalSubmissionService,
)
from lea.runtime import (
    ConfigurationResult,
    RuntimeConfig,
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
    TaskProvider,
    TaskProviderInspectionResult,
    TaskRecord,
    TaskStatus,
)

PROPOSAL_ID = "11111111-1111-4111-8111-111111111111"
TASK_UUID = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2026, 7, 29, 10, 0, tzinfo=UTC)

PROPOSALS_READ = "Proposals.Read"
PROPOSALS_CONFIRM = "Proposals.Confirm"
EXECUTE_LOW = "Proposals.Execute.LowRisk"
EXECUTE_MEDIUM = "Proposals.Execute.MediumRisk"
EXECUTE_HIGH = "Proposals.Execute.HighRisk"


class IdentifierSequence:
    """Return deterministic canonical UUID strings."""

    def __init__(self, start: int) -> None:
        self._value = start

    def __call__(self) -> str:
        self._value += 1
        return f"{self._value:08x}-1111-4111-8111-{self._value:012x}"


class UtcSequence:
    """Return monotonically increasing UTC timestamps."""

    def __init__(self, start: datetime) -> None:
        self._start = start
        self._offset = 0

    def __call__(self) -> datetime:
        value = self._start + timedelta(seconds=self._offset)
        self._offset += 1
        return value


class RecordingTaskProvider:
    """Record every provider mutation and return canonical task results."""

    def __init__(self) -> None:
        self.created: list[TaskCreateRequest] = []
        self.modified: list[TaskModifyRequest] = []
        self.completed: list[str] = []
        self.deleted: list[str] = []

    @property
    def mutation_count(self) -> int:
        return (
            len(self.created)
            + len(self.modified)
            + len(self.completed)
            + len(self.deleted)
        )

    def inspect(self) -> TaskProviderInspectionResult:
        return TaskProviderInspectionResult(
            available=True,
            provider="test",
            version="1.0",
            issues=(),
        )

    def create_task(
        self,
        request: TaskCreateRequest,
    ) -> TaskCreateResult:
        self.created.append(request)
        return TaskCreateResult(
            success=True,
            task=_task(
                description=request.description,
                status=TaskStatus.PENDING,
                project=request.project,
                priority=request.priority,
                tags=request.tags,
            ),
            issues=(),
        )

    def list_tasks(
        self,
        query: TaskListQuery,
    ) -> TaskListResult:
        del query
        return TaskListResult(success=True, tasks=(), issues=())

    def modify_task(
        self,
        request: TaskModifyRequest,
    ) -> TaskMutationResult:
        self.modified.append(request)
        return TaskMutationResult(
            success=True,
            task=_task(
                description=request.description or "Modified task",
                status=TaskStatus.PENDING,
                project=request.project,
                priority=request.priority,
                tags=request.add_tags,
            ),
            issues=(),
        )

    def complete_task(
        self,
        task_uuid: str,
    ) -> TaskMutationResult:
        self.completed.append(task_uuid)
        return TaskMutationResult(
            success=True,
            task=_task(
                description="Completed task",
                status=TaskStatus.COMPLETED,
            ),
            issues=(),
        )

    def delete_task(
        self,
        task_uuid: str,
    ) -> TaskMutationResult:
        self.deleted.append(task_uuid)
        return TaskMutationResult(
            success=True,
            task=_task(
                description="Deleted task",
                status=TaskStatus.DELETED,
            ),
            issues=(),
        )


@dataclass(frozen=True, slots=True)
class LifecycleHarness:
    """Production-composed channel lifecycle dependencies."""

    application: DispatchingChannelApplication
    config: RuntimeConfig
    repository: MarkdownProposalRepository
    audit_store: IntegrityJsonlAuditStore
    provider: RecordingTaskProvider


def _task(
    *,
    description: str,
    status: TaskStatus,
    project: str | None = None,
    priority: str | None = None,
    tags: tuple[str, ...] = (),
) -> TaskRecord:
    return TaskRecord(
        uuid=TASK_UUID,
        description=description,
        status=status,
        entry=NOW,
        modified=NOW,
        project=project,
        priority=priority,
        tags=tags,
    )


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
        installed_at=NOW,
    )


def _harness(tmp_path: Path) -> LifecycleHarness:
    config = isolated_test_runtime_config(tmp_path / "runtime")
    config.paths.proposal_dir.mkdir(parents=True)
    config.paths.audit_dir.mkdir(parents=True)

    configuration = ConfigurationResult(
        success=True,
        config=config,
        issues=(),
    )
    repository = MarkdownProposalRepository(config.paths.proposal_dir)
    audit_store = IntegrityJsonlAuditStore(config.paths.audit_file)
    provider = RecordingTaskProvider()
    timestamps = UtcSequence(NOW)
    event_ids = IdentifierSequence(100)
    control_ids = IdentifierSequence(200)

    def load_configuration(_path: str | Path) -> ConfigurationResult:
        return configuration

    def create_repository(
        _runtime: RuntimeConfig,
    ) -> MarkdownProposalRepository:
        return repository

    def create_audit_store(
        _runtime: RuntimeConfig,
    ) -> IntegrityJsonlAuditStore:
        return IntegrityJsonlAuditStore(config.paths.audit_file)

    def create_orchestrator(
        store: IntegrityJsonlAuditStore,
    ) -> ActionOrchestrator:
        return ActionOrchestrator(
            ActionHandlerRegistry(),
            store,
            timestamps,
            event_ids,
        )

    def create_execution_orchestrator(
        registry: ActionHandlerRegistry,
        store: IntegrityJsonlAuditStore,
    ) -> ActionOrchestrator:
        return ActionOrchestrator(
            registry,
            store,
            timestamps,
            event_ids,
        )

    def read_installation_record(
        _path: Path,
    ) -> tuple[TaskwarriorInstallationRecord | None, tuple[object, ...]]:
        return (_record(tmp_path), ())

    def create_provider(
        _config: TaskwarriorConfig,
    ) -> TaskProvider:
        return provider

    proposal_dependencies = ProposalCommandDependencies(
        load_configuration=load_configuration,
        create_repository=create_repository,
        create_audit_store=create_audit_store,
        create_orchestrator=create_orchestrator,
        create_execution_orchestrator=create_execution_orchestrator,
        task_provider_dependencies=TaskProviderDependencies(
            load_configuration=load_configuration,
            read_installation_record=read_installation_record,
            create_provider=create_provider,
        ),
    )
    submission = ProposalSubmissionService(
        ActionOrchestrator(
            ActionHandlerRegistry(),
            audit_store,
            timestamps,
            event_ids,
        ),
        repository,
    )
    dependencies = ChannelHandlerDependencies(
        config_path=(tmp_path / "lea.toml").resolve(),
        expected_profile=RuntimeProfile.TEST,
        clock=timestamps,
        proposal_submitter=submission.submit,
        proposal_id_source=lambda: PROPOSAL_ID,
        control_id_source=control_ids,
        proposal_dependencies=proposal_dependencies,
    )

    return LifecycleHarness(
        application=build_default_channel_application(dependencies),
        config=config,
        repository=repository,
        audit_store=audit_store,
        provider=provider,
    )


def _request(
    command: str,
    arguments: list[str],
    *,
    capabilities: tuple[str, ...],
) -> ChannelRequest:
    return ChannelRequest(
        request_id=str(uuid4()),
        source_update_id=f"test:{uuid4()}",
        identity=ChannelIdentity(
            channel=ChannelName.TELEGRAM,
            user_id="123456789",
            conversation_id="123456789",
            role="owner",
            display_name="Owner",
            capabilities=capabilities,
        ),
        request_type=ChannelRequestType.COMMAND,
        command=command,
        parameters={"arguments": arguments},
        received_at=NOW,
    )


def _read_status(
    repository: MarkdownProposalRepository,
) -> ActionStatus:
    result = repository.read(PROPOSAL_ID)
    assert result.success is True
    assert result.proposal is not None
    return result.proposal.status


def _execute(
    harness: LifecycleHarness,
    *,
    capability: str,
) -> ChannelApplicationResult:
    return harness.application.handle(
        _request(
            "proposals.execute",
            [PROPOSAL_ID],
            capabilities=(PROPOSALS_READ, capability),
        )
    )


def _approve(harness: LifecycleHarness) -> None:
    result = harness.application.handle(
        _request(
            "proposals.approve",
            [PROPOSAL_ID],
            capabilities=(PROPOSALS_CONFIRM,),
        )
    )

    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.SUCCEEDED
    assert _read_status(harness.repository) is ActionStatus.APPROVED

    read_result = harness.repository.read(PROPOSAL_ID)
    assert read_result.success is True
    assert read_result.proposal is not None
    expected_capability = {
        RiskLevel.LOW: EXECUTE_LOW,
        RiskLevel.MEDIUM: EXECUTE_MEDIUM,
        RiskLevel.HIGH: EXECUTE_HIGH,
    }[read_result.proposal.risk_level]

    assert tuple(control.action for control in result.response.controls) == (
        "proposal.execute",
        "proposal.cancel",
    )
    assert tuple(
        control.required_capability for control in result.response.controls
    ) == (
        expected_capability,
        PROPOSALS_CONFIRM,
    )


def test_low_risk_create_requires_confirmation_then_execution(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)

    submitted = harness.application.handle(
        _request(
            "tasks.create",
            ["Lifecycle", "regression", "task"],
            capabilities=("Tasks.Write",),
        )
    )

    assert submitted.response is not None
    assert submitted.response.outcome is ChannelResponseOutcome.SUCCEEDED
    assert submitted.response.message == "Proposal awaiting confirmation."
    assert tuple(control.action for control in submitted.response.controls) == (
        "proposal.approve",
        "proposal.reject",
        "proposal.cancel",
    )
    assert _read_status(harness.repository) is (ActionStatus.AWAITING_CONFIRMATION)
    assert harness.provider.mutation_count == 0
    submission_audit_count = len(harness.audit_store.read_all())
    assert submission_audit_count > 0

    premature = _execute(harness, capability=EXECUTE_LOW)

    assert premature.response is not None
    assert premature.response.outcome is (ChannelResponseOutcome.APPLICATION_FAILED)
    assert premature.response.issue is not None
    assert premature.response.issue.code == "execution_rejected"
    assert harness.provider.mutation_count == 0

    _approve(harness)

    assert harness.provider.mutation_count == 0
    assert _read_status(harness.repository) is ActionStatus.APPROVED
    approval_audit_count = len(harness.audit_store.read_all())
    assert approval_audit_count > submission_audit_count

    executed = _execute(harness, capability=EXECUTE_LOW)

    assert executed.response is not None
    assert executed.response.outcome is ChannelResponseOutcome.SUCCEEDED
    assert harness.provider.created == [
        TaskCreateRequest(description="Lifecycle regression task")
    ]
    assert harness.provider.mutation_count == 1
    assert _read_status(harness.repository) is ActionStatus.SUCCEEDED
    assert len(harness.audit_store.read_all()) > approval_audit_count

    duplicate = _execute(harness, capability=EXECUTE_LOW)

    assert duplicate.response is not None
    assert duplicate.response.outcome is (ChannelResponseOutcome.APPLICATION_FAILED)
    assert duplicate.response.issue is not None
    assert duplicate.response.issue.code == "execution_rejected"
    assert harness.provider.mutation_count == 1


@pytest.mark.parametrize(
    (
        "command",
        "arguments",
        "exact_capability",
        "provider_attribute",
    ),
    [
        (
            "tasks.modify",
            [TASK_UUID, "Revised", "task"],
            EXECUTE_MEDIUM,
            "modified",
        ),
        (
            "tasks.complete",
            [TASK_UUID],
            EXECUTE_MEDIUM,
            "completed",
        ),
        (
            "tasks.delete",
            [TASK_UUID],
            EXECUTE_HIGH,
            "deleted",
        ),
    ],
)
def test_confirmed_mutations_enforce_risk_and_execute_once(
    tmp_path: Path,
    command: str,
    arguments: list[str],
    exact_capability: str,
    provider_attribute: str,
) -> None:
    harness = _harness(tmp_path)

    submitted = harness.application.handle(
        _request(
            command,
            arguments,
            capabilities=("Tasks.Write", "Tasks.Delete"),
        )
    )

    assert submitted.response is not None
    assert submitted.response.outcome is ChannelResponseOutcome.SUCCEEDED
    assert submitted.response.message == "Proposal awaiting confirmation."
    assert _read_status(harness.repository) is ActionStatus.AWAITING_CONFIRMATION
    assert harness.provider.mutation_count == 0
    submission_audit_count = len(harness.audit_store.read_all())
    assert submission_audit_count > 0

    premature = _execute(harness, capability=exact_capability)

    assert premature.response is not None
    assert premature.response.outcome is ChannelResponseOutcome.APPLICATION_FAILED
    assert premature.response.issue is not None
    assert premature.response.issue.code == "execution_rejected"
    assert harness.provider.mutation_count == 0

    _approve(harness)

    assert harness.provider.mutation_count == 0
    approval_audit_count = len(harness.audit_store.read_all())
    assert approval_audit_count > submission_audit_count

    denied = _execute(harness, capability=EXECUTE_LOW)

    assert denied.response is not None
    assert denied.response.outcome is ChannelResponseOutcome.NOT_AUTHORISED
    assert denied.response.issue is not None
    assert denied.response.issue.code == ("proposal_execution_capability_required")
    assert harness.provider.mutation_count == 0

    executed = _execute(harness, capability=exact_capability)

    assert executed.response is not None
    assert executed.response.outcome is ChannelResponseOutcome.SUCCEEDED
    assert harness.provider.mutation_count == 1
    assert len(getattr(harness.provider, provider_attribute)) == 1
    assert _read_status(harness.repository) is ActionStatus.SUCCEEDED
    assert len(harness.audit_store.read_all()) > approval_audit_count

    duplicate = _execute(harness, capability=exact_capability)

    assert duplicate.response is not None
    assert duplicate.response.outcome is ChannelResponseOutcome.APPLICATION_FAILED
    assert duplicate.response.issue is not None
    assert duplicate.response.issue.code == "execution_rejected"
    assert harness.provider.mutation_count == 1
