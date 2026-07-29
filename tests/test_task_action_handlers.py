"""Tests for provider-neutral task action handlers."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from lea.actions import ActionHandler, ActionProposal, ActionStatus
from lea.tasks import (
    TaskActionHandlerError,
    TaskCreateRequest,
    TaskCreateResult,
    TaskListQuery,
    TaskListResult,
    TaskModifyRequest,
    TaskMutationResult,
    TaskProviderInspectionResult,
    TaskProviderIssue,
    TaskRecord,
    TaskStatus,
    complete_task_action_handler,
    create_task_action_handler,
    delete_task_action_handler,
    modify_task_action_handler,
    task_action_handler_registry,
)

PROPOSAL_ID = "11111111-1111-4111-8111-111111111111"
TASK_UUID = "22222222-2222-4222-8222-222222222222"


class RecordingProvider:
    """Record task action-handler provider calls."""

    def __init__(self) -> None:
        self.created: list[TaskCreateRequest] = []
        self.modified: list[TaskModifyRequest] = []
        self.completed: list[str] = []
        self.deleted: list[str] = []
        self.failure: TaskProviderIssue | None = None

    def inspect(self) -> TaskProviderInspectionResult:
        return TaskProviderInspectionResult(
            available=True,
            provider="test",
            version="1.0",
            issues=(),
        )

    def create_task(self, request: TaskCreateRequest) -> TaskCreateResult:
        self.created.append(request)
        if self.failure is not None:
            return TaskCreateResult(False, None, (self.failure,))
        return TaskCreateResult(True, _task(), ())

    def list_tasks(self, query: TaskListQuery) -> TaskListResult:
        raise AssertionError

    def modify_task(self, request: TaskModifyRequest) -> TaskMutationResult:
        self.modified.append(request)
        if self.failure is not None:
            return TaskMutationResult(False, None, (self.failure,))
        return TaskMutationResult(True, _task(), ())

    def complete_task(self, task_uuid: str) -> TaskMutationResult:
        self.completed.append(task_uuid)
        return TaskMutationResult(True, _task(status=TaskStatus.COMPLETED), ())

    def delete_task(self, task_uuid: str) -> TaskMutationResult:
        self.deleted.append(task_uuid)
        return TaskMutationResult(True, _task(status=TaskStatus.DELETED), ())


def _task(*, status: TaskStatus = TaskStatus.PENDING) -> TaskRecord:
    return TaskRecord(
        uuid=TASK_UUID,
        description="Provider task",
        status=status,
        entry=datetime(2026, 7, 22, 12, 0, tzinfo=UTC),
        project="lea",
        tags=("local_cli",),
        priority="M",
    )


def _proposal(action: str, parameters: dict[str, object]) -> ActionProposal:
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action=action,
        parameters=parameters,
        status=ActionStatus.EXECUTING,
        source="test",
        created_at=datetime(2026, 7, 22, 11, 0, tzinfo=UTC),
    )


def test_registry_contains_four_task_mutation_handlers() -> None:
    registry = task_action_handler_registry(RecordingProvider())

    assert len(registry) == 4
    assert "task.create" in registry
    assert "task.modify" in registry
    assert "task.complete" in registry
    assert "task.delete" in registry


def test_create_handler_builds_provider_neutral_request() -> None:
    provider = RecordingProvider()
    output = create_task_action_handler(provider)(
        _proposal(
            "task.create",
            {
                "description": "Create task",
                "project": "lea",
                "priority": "M",
                "tags": ["local-cli", "testing"],
            },
        )
    )

    assert provider.created == [
        TaskCreateRequest(
            description="Create task",
            project="lea",
            priority="M",
            tags=("local_cli", "testing"),
        )
    ]
    assert output is not None
    raw_task = output.get("task")
    assert isinstance(raw_task, dict)
    assert raw_task["uuid"] == TASK_UUID


def test_modify_handler_builds_provider_neutral_request() -> None:
    provider = RecordingProvider()
    modify_task_action_handler(provider)(
        _proposal(
            "task.modify",
            {
                "uuid": TASK_UUID,
                "description": "Updated task",
                "add_tags": ["updated"],
                "remove_tags": ["old"],
            },
        )
    )

    assert provider.modified == [
        TaskModifyRequest(
            task_uuid=TASK_UUID,
            description="Updated task",
            add_tags=("updated",),
            remove_tags=("old",),
        )
    ]


@pytest.mark.parametrize(
    ("factory", "attribute"),
    [
        (complete_task_action_handler, "completed"),
        (delete_task_action_handler, "deleted"),
    ],
)
def test_exact_uuid_handlers_call_provider(
    factory: Callable[[RecordingProvider], ActionHandler],
    attribute: str,
) -> None:
    provider = RecordingProvider()
    handler = factory(provider)
    handler(_proposal("task.complete", {"uuid": TASK_UUID}))

    assert getattr(provider, attribute) == [TASK_UUID]


def test_unknown_parameter_is_rejected_before_provider_call() -> None:
    provider = RecordingProvider()

    with pytest.raises(
        TaskActionHandlerError,
        match="task_action_parameter_unknown",
    ):
        create_task_action_handler(provider)(
            _proposal(
                "task.create",
                {
                    "description": "Create task",
                    "unexpected": True,
                },
            )
        )

    assert provider.created == []


def test_provider_failure_preserves_first_issue() -> None:
    provider = RecordingProvider()
    provider.failure = TaskProviderIssue(
        code="taskwarrior_process_failed",
        message="Taskwarrior failed.",
        provider="taskwarrior",
        operation="create",
    )

    with pytest.raises(
        TaskActionHandlerError,
        match="taskwarrior_process_failed: Taskwarrior failed",
    ):
        create_task_action_handler(provider)(
            _proposal("task.create", {"description": "Create task"})
        )


def test_create_handler_round_trips_due_timestamp() -> None:
    """Create proposals should restore provider-neutral due timestamps."""
    provider = RecordingProvider()
    due = datetime(2026, 7, 30, 15, 30, tzinfo=UTC)

    create_task_action_handler(provider)(
        _proposal(
            "task.create",
            {
                "description": "Create task",
                "due": due.isoformat(),
            },
        )
    )

    assert provider.created == [
        TaskCreateRequest(
            description="Create task",
            due=due,
        )
    ]


def test_modify_handler_round_trips_clear_flags() -> None:
    """Modify proposals should preserve explicit clearing operations."""
    provider = RecordingProvider()

    modify_task_action_handler(provider)(
        _proposal(
            "task.modify",
            {
                "uuid": TASK_UUID,
                "clear_due": True,
                "clear_priority": True,
            },
        )
    )

    assert provider.modified == [
        TaskModifyRequest(
            task_uuid=TASK_UUID,
            clear_due=True,
            clear_priority=True,
        )
    ]
