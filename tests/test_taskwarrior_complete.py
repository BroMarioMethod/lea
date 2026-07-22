"""Tests for Taskwarrior task completion."""

from collections.abc import Sequence
from pathlib import Path

from lea.adapters.taskwarrior import (
    TaskwarriorCliProvider,
    TaskwarriorCommandResult,
    TaskwarriorConfig,
    TaskwarriorRunResult,
)
from lea.tasks import TaskProviderIssue, TaskStatus

TASK_UUID = "11111111-1111-4111-8111-111111111111"
OTHER_UUID = "22222222-2222-4222-8222-222222222222"


class QueueRunner:
    """Return queued deterministic Taskwarrior results."""

    def __init__(
        self,
        results: Sequence[TaskwarriorRunResult],
    ) -> None:
        """Configure queued results."""
        self._results = list(results)
        self.calls: list[tuple[tuple[str, ...], str]] = []

    def run(
        self,
        arguments: Sequence[str],
        *,
        operation: str,
    ) -> TaskwarriorRunResult:
        """Record one invocation and return the next result."""
        self.calls.append((tuple(arguments), operation))
        return self._results.pop(0)


def make_config(tmp_path: Path) -> TaskwarriorConfig:
    """Return one explicit provider configuration."""
    return TaskwarriorConfig(
        executable=tmp_path / "bin" / "task",
        taskrc=tmp_path / "config" / "taskrc",
        data_dir=tmp_path / "data",
        home_dir=tmp_path / "home",
    )


def successful_run(
    stdout: str = "",
) -> TaskwarriorRunResult:
    """Return one successful captured command."""
    return TaskwarriorRunResult(
        success=True,
        command=TaskwarriorCommandResult(
            arguments=("/opt/task",),
            return_code=0,
            stdout=stdout,
            stderr="",
            duration_seconds=0.01,
        ),
        issues=(),
    )


def failed_run(
    *,
    operation: str,
) -> TaskwarriorRunResult:
    """Return one failed invocation."""
    return TaskwarriorRunResult(
        success=False,
        command=None,
        issues=(
            TaskProviderIssue(
                code="taskwarrior_process_failed",
                message="Taskwarrior failed.",
                provider="taskwarrior",
                operation=operation,
                return_code=1,
            ),
        ),
    )


def exported_task(
    *,
    uuid: str = TASK_UUID,
    status: str = "completed",
) -> str:
    """Return one valid Taskwarrior export payload."""
    return f"""
    [
      {{
        "uuid": "{uuid}",
        "description": "Completed task",
        "status": "{status}",
        "entry": "20260721T172608Z",
        "modified": "20260721T180000Z"
      }}
    ]
    """


def test_complete_targets_exact_uuid_and_reads_back(
    tmp_path: Path,
) -> None:
    """Completion should target one UUID and export it afterwards."""
    runner = QueueRunner(
        [
            successful_run(),
            successful_run(exported_task()),
        ]
    )
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )

    result = provider.complete_task(TASK_UUID)

    assert result.success is True
    assert result.task is not None
    assert result.task.uuid == TASK_UUID
    assert result.task.status is TaskStatus.COMPLETED
    assert runner.calls == [
        ((TASK_UUID, "done"), "complete"),
        ((TASK_UUID, "export"), "complete_readback"),
    ]


def test_complete_rejects_non_canonical_uuid(
    tmp_path: Path,
) -> None:
    """Invalid UUIDs should fail without invoking Taskwarrior."""
    runner = QueueRunner([])
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )

    result = provider.complete_task("not-a-uuid")

    assert result.success is False
    assert result.task is None
    assert result.issues[0].code == "taskwarrior_task_uuid_invalid"
    assert result.issues[0].task_uuid is None
    assert runner.calls == []


def test_complete_preserves_runner_failure(
    tmp_path: Path,
) -> None:
    """Completion process failures should remain structured."""
    runner = QueueRunner([failed_run(operation="complete")])
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )

    result = provider.complete_task(TASK_UUID)

    assert result.success is False
    assert result.task is None
    assert result.issues == failed_run(operation="complete").issues
    assert len(runner.calls) == 1


def test_complete_preserves_readback_runner_failure(
    tmp_path: Path,
) -> None:
    """Completion read-back failures should remain structured."""
    runner = QueueRunner(
        [
            successful_run(),
            failed_run(operation="complete_readback"),
        ]
    )
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )

    result = provider.complete_task(TASK_UUID)

    assert result.success is False
    assert result.issues[0].operation == "complete_readback"


def test_complete_preserves_readback_parser_failure(
    tmp_path: Path,
) -> None:
    """Malformed read-back JSON should remain structured."""
    runner = QueueRunner(
        [
            successful_run(),
            successful_run("{invalid json}"),
        ]
    )
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )

    result = provider.complete_task(TASK_UUID)

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_export_invalid_json"


def test_complete_requires_exactly_one_readback_task(
    tmp_path: Path,
) -> None:
    """Read-back must contain exactly the completed task."""
    runner = QueueRunner(
        [
            successful_run(),
            successful_run("[]"),
        ]
    )
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )

    result = provider.complete_task(TASK_UUID)

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_mutation_readback_invalid"


def test_complete_rejects_readback_uuid_mismatch(
    tmp_path: Path,
) -> None:
    """Read-back must match the completed UUID."""
    runner = QueueRunner(
        [
            successful_run(),
            successful_run(exported_task(uuid=OTHER_UUID)),
        ]
    )
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )

    result = provider.complete_task(TASK_UUID)

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_mutation_readback_mismatch"


def test_complete_rejects_non_completed_readback(
    tmp_path: Path,
) -> None:
    """Successful completion must read back completed state."""
    runner = QueueRunner(
        [
            successful_run(),
            successful_run(exported_task(status="pending")),
        ]
    )
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )

    result = provider.complete_task(TASK_UUID)

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_complete_readback_status_invalid"
