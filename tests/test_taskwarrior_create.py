"""Tests for Taskwarrior task creation."""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from lea.adapters.taskwarrior import (
    TaskwarriorCliProvider,
    TaskwarriorCommandResult,
    TaskwarriorConfig,
    TaskwarriorRunResult,
)
from lea.tasks import (
    TaskCreateRequest,
    TaskProviderIssue,
)

TASK_UUID = "11111111-1111-4111-8111-111111111111"


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
    stdout: str,
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
    """Return one valid Taskwarrior export payload."""
    return f"""
    [
      {{
        "uuid": "{uuid}",
        "description": "Create adapter task",
        "status": "pending",
        "entry": "20260721T172608Z",
        "project": "lea",
        "priority": "H",
        "due": "20260722T120000Z",
        "tags": ["adapter", "urgent"]
      }}
    ]
    """


def test_create_builds_deterministic_arguments_and_reads_back(
    tmp_path: Path,
) -> None:
    """Creation should request a UUID then export that exact task."""
    runner = QueueRunner(
        [
            successful_run(f"{TASK_UUID}\n"),
            successful_run(exported_task()),
        ]
    )
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )
    request = TaskCreateRequest(
        description="Create adapter task",
        project="lea",
        due=datetime(
            2026,
            7,
            22,
            14,
            0,
            tzinfo=UTC,
        ),
        priority="H",
        tags=("urgent", "adapter"),
    )

    result = provider.create_task(request)

    assert result.success is True
    assert result.task is not None
    assert result.task.uuid == TASK_UUID
    assert result.task.tags == ("adapter", "urgent")
    assert runner.calls == [
        (
            (
                "rc.verbose:new-uuid",
                "add",
                "Create adapter task",
                "project:lea",
                "due:20260722T140000Z",
                "priority:H",
                "+adapter",
                "+urgent",
            ),
            "create",
        ),
        (
            (TASK_UUID, "export"),
            "create_readback",
        ),
    ]


def test_create_converts_due_to_utc(
    tmp_path: Path,
) -> None:
    """Creation should serialise due timestamps in UTC."""
    from datetime import timedelta, timezone

    runner = QueueRunner(
        [
            successful_run(f"{TASK_UUID}\n"),
            successful_run(exported_task()),
        ]
    )
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )
    request = TaskCreateRequest(
        description="Create adapter task",
        due=datetime(
            2026,
            7,
            22,
            14,
            0,
            tzinfo=timezone(timedelta(hours=2)),
        ),
    )

    result = provider.create_task(request)

    assert result.success is True
    assert "due:20260722T120000Z" in runner.calls[0][0]


def test_create_preserves_runner_failure(
    tmp_path: Path,
) -> None:
    """Creation process failures should remain structured."""
    runner = QueueRunner([failed_run(operation="create")])
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )

    result = provider.create_task(
        TaskCreateRequest(description="Test"),
    )

    assert result.success is False
    assert result.task is None
    assert result.issues == failed_run(operation="create").issues
    assert len(runner.calls) == 1


def test_create_rejects_missing_uuid(
    tmp_path: Path,
) -> None:
    """Creation must fail when Taskwarrior returns no UUID."""
    runner = QueueRunner([successful_run("")])
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )

    result = provider.create_task(
        TaskCreateRequest(description="Test"),
    )

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_create_uuid_invalid"
    assert len(runner.calls) == 1


def test_create_rejects_malformed_uuid(
    tmp_path: Path,
) -> None:
    """Creation must fail when Taskwarrior returns other text."""
    runner = QueueRunner([successful_run("Created task 1.\n")])
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )

    result = provider.create_task(
        TaskCreateRequest(description="Test"),
    )

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_create_uuid_invalid"


def test_create_preserves_readback_runner_failure(
    tmp_path: Path,
) -> None:
    """Exact read-back process failures should remain structured."""
    runner = QueueRunner(
        [
            successful_run(f"{TASK_UUID}\n"),
            failed_run(operation="create_readback"),
        ]
    )
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )

    result = provider.create_task(
        TaskCreateRequest(description="Test"),
    )

    assert result.success is False
    assert result.issues[0].operation == "create_readback"


def test_create_preserves_readback_parser_failure(
    tmp_path: Path,
) -> None:
    """Malformed read-back JSON should remain structured."""
    runner = QueueRunner(
        [
            successful_run(f"{TASK_UUID}\n"),
            successful_run("{invalid json}"),
        ]
    )
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )

    result = provider.create_task(
        TaskCreateRequest(description="Test"),
    )

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_export_invalid_json"


def test_create_requires_exactly_one_readback_task(
    tmp_path: Path,
) -> None:
    """Read-back must return exactly the created task."""
    runner = QueueRunner(
        [
            successful_run(f"{TASK_UUID}\n"),
            successful_run("[]"),
        ]
    )
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )

    result = provider.create_task(
        TaskCreateRequest(description="Test"),
    )

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_create_readback_invalid"


def test_create_rejects_readback_uuid_mismatch(
    tmp_path: Path,
) -> None:
    """Read-back must match the UUID emitted during creation."""
    other_uuid = "22222222-2222-4222-8222-222222222222"
    runner = QueueRunner(
        [
            successful_run(f"{TASK_UUID}\n"),
            successful_run(exported_task(uuid=other_uuid)),
        ]
    )
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )

    result = provider.create_task(
        TaskCreateRequest(description="Test"),
    )

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_create_readback_mismatch"


def test_create_accepts_taskwarrior_3_4_uuid_output(
    tmp_path: Path,
) -> None:
    """Taskwarrior 3.4.x creation output should expose its UUID."""
    runner = QueueRunner(
        [
            successful_run(f"Created task {TASK_UUID}.\n"),
            successful_run(exported_task()),
        ]
    )
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,
    )

    result = provider.create_task(
        TaskCreateRequest(description="Test"),
    )

    assert result.success is True
    assert result.task is not None
    assert result.task.uuid == TASK_UUID
