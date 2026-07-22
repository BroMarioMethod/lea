"""Tests for Taskwarrior task modification."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from lea.adapters.taskwarrior import (
    TaskwarriorCliProvider,
    TaskwarriorCommandResult,
    TaskwarriorConfig,
    TaskwarriorRunResult,
)
from lea.tasks import (
    TaskModifyRequest,
    TaskProviderIssue,
)

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
) -> str:
    """Return one valid modified Taskwarrior export payload."""
    return f"""
    [
      {{
        "uuid": "{uuid}",
        "description": "Updated task",
        "status": "pending",
        "entry": "20260721T172608Z",
        "modified": "20260721T180000Z",
        "project": "lea",
        "priority": "H",
        "due": "20260722T120000Z",
        "tags": ["adapter", "urgent"]
      }}
    ]
    """


def test_modify_builds_deterministic_arguments_and_reads_back(
    tmp_path: Path,
) -> None:
    """Modification should target one UUID and read it back."""
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
    request = TaskModifyRequest(
        task_uuid=TASK_UUID,
        description="Updated task",
        project="lea",
        due=datetime(
            2026,
            7,
            22,
            14,
            0,
            tzinfo=timezone(timedelta(hours=2)),
        ),
        priority="H",
        add_tags=("urgent", "adapter"),
        remove_tags=("old", "later"),
    )

    result = provider.modify_task(request)

    assert result.success is True
    assert result.task is not None
    assert result.task.uuid == TASK_UUID
    assert runner.calls == [
        (
            (
                TASK_UUID,
                "modify",
                "description:Updated task",
                "project:lea",
                "due:20260722T120000Z",
                "priority:H",
                "+adapter",
                "+urgent",
                "-later",
                "-old",
            ),
            "modify",
        ),
        (
            (TASK_UUID, "export"),
            "modify_readback",
        ),
    ]


def test_modify_can_clear_due_and_priority(
    tmp_path: Path,
) -> None:
    """Clear operations should use empty Taskwarrior attributes."""
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

    result = provider.modify_task(
        TaskModifyRequest(
            task_uuid=TASK_UUID,
            clear_due=True,
            clear_priority=True,
        )
    )

    assert result.success is True
    assert runner.calls[0] == (
        (
            TASK_UUID,
            "modify",
            "due:",
            "priority:",
        ),
        "modify",
    )


def test_modify_preserves_runner_failure(
    tmp_path: Path,
) -> None:
    """Modification failures should remain structured."""
    runner = QueueRunner([failed_run(operation="modify")])
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )

    result = provider.modify_task(
        TaskModifyRequest(
            task_uuid=TASK_UUID,
            description="Updated",
        )
    )

    assert result.success is False
    assert result.task is None
    assert result.issues == failed_run(operation="modify").issues
    assert len(runner.calls) == 1


def test_modify_preserves_readback_runner_failure(
    tmp_path: Path,
) -> None:
    """Read-back process failures should remain structured."""
    runner = QueueRunner(
        [
            successful_run(),
            failed_run(operation="modify_readback"),
        ]
    )
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )

    result = provider.modify_task(
        TaskModifyRequest(
            task_uuid=TASK_UUID,
            description="Updated",
        )
    )

    assert result.success is False
    assert result.issues[0].operation == "modify_readback"


def test_modify_preserves_readback_parser_failure(
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

    result = provider.modify_task(
        TaskModifyRequest(
            task_uuid=TASK_UUID,
            description="Updated",
        )
    )

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_export_invalid_json"


def test_modify_requires_exactly_one_readback_task(
    tmp_path: Path,
) -> None:
    """Read-back must return exactly the modified task."""
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

    result = provider.modify_task(
        TaskModifyRequest(
            task_uuid=TASK_UUID,
            description="Updated",
        )
    )

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_mutation_readback_invalid"


def test_modify_rejects_readback_uuid_mismatch(
    tmp_path: Path,
) -> None:
    """Read-back must match the requested UUID."""
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

    result = provider.modify_task(
        TaskModifyRequest(
            task_uuid=TASK_UUID,
            description="Updated",
        )
    )

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_mutation_readback_mismatch"
    assert result.issues[0].task_uuid == TASK_UUID


def test_modify_returns_immutable_readback_task(
    tmp_path: Path,
) -> None:
    """Successful modification should return canonical parsed state."""
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

    result = provider.modify_task(
        TaskModifyRequest(
            task_uuid=TASK_UUID,
            description="Updated",
        )
    )

    assert result.success is True
    assert result.task is not None
    assert result.task.modified == datetime(
        2026,
        7,
        21,
        18,
        0,
        tzinfo=UTC,
    )
    assert result.task.tags == ("adapter", "urgent")
