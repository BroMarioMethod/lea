"""Tests for Taskwarrior task deletion."""

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
    status: str = "deleted",
) -> str:
    """Return one valid Taskwarrior export payload."""
    return f"""
    [
      {{
        "uuid": "{uuid}",
        "description": "Deleted task",
        "status": "{status}",
        "entry": "20260721T172608Z",
        "modified": "20260721T180000Z"
      }}
    ]
    """


def test_delete_targets_exact_uuid_and_reads_back(
    tmp_path: Path,
) -> None:
    """Deletion should target one UUID and export it afterwards."""
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

    result = provider.delete_task(TASK_UUID)

    assert result.success is True
    assert result.task is not None
    assert result.task.uuid == TASK_UUID
    assert result.task.status is TaskStatus.DELETED
    assert runner.calls == [
        ((TASK_UUID, "delete"), "delete"),
        ((TASK_UUID, "export"), "delete_readback"),
    ]


def test_delete_rejects_non_canonical_uuid(
    tmp_path: Path,
) -> None:
    """Invalid UUIDs should fail without invoking Taskwarrior."""
    runner = QueueRunner([])
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )

    result = provider.delete_task("not-a-uuid")

    assert result.success is False
    assert result.task is None
    assert result.issues[0].code == "taskwarrior_task_uuid_invalid"
    assert result.issues[0].task_uuid is None
    assert runner.calls == []


def test_delete_preserves_runner_failure(
    tmp_path: Path,
) -> None:
    """Deletion process failures should remain structured."""
    runner = QueueRunner([failed_run(operation="delete")])
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )

    result = provider.delete_task(TASK_UUID)

    assert result.success is False
    assert result.task is None
    assert result.issues == failed_run(operation="delete").issues
    assert len(runner.calls) == 1


def test_delete_preserves_readback_runner_failure(
    tmp_path: Path,
) -> None:
    """Deletion read-back failures should remain structured."""
    runner = QueueRunner(
        [
            successful_run(),
            failed_run(operation="delete_readback"),
        ]
    )
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )

    result = provider.delete_task(TASK_UUID)

    assert result.success is False
    assert result.issues[0].operation == "delete_readback"


def test_delete_preserves_readback_parser_failure(
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

    result = provider.delete_task(TASK_UUID)

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_export_invalid_json"


def test_delete_requires_exactly_one_readback_task(
    tmp_path: Path,
) -> None:
    """Read-back must contain exactly the deleted task."""
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

    result = provider.delete_task(TASK_UUID)

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_mutation_readback_invalid"


def test_delete_rejects_readback_uuid_mismatch(
    tmp_path: Path,
) -> None:
    """Read-back must match the deleted UUID."""
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

    result = provider.delete_task(TASK_UUID)

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_mutation_readback_mismatch"


def test_delete_rejects_non_deleted_readback(
    tmp_path: Path,
) -> None:
    """Successful deletion must read back deleted state."""
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

    result = provider.delete_task(TASK_UUID)

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_delete_readback_status_invalid"
