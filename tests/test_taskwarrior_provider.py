"""Tests for the read-only Taskwarrior CLI provider."""

from datetime import UTC, datetime
from pathlib import Path

from lea.adapters.taskwarrior import (
    TaskwarriorCliProvider,
    TaskwarriorCommandResult,
    TaskwarriorConfig,
    TaskwarriorRunResult,
)
from lea.tasks import (
    TaskListQuery,
    TaskProvider,
    TaskProviderIssue,
    TaskStatus,
)

TASK_UUID = "11111111-1111-4111-8111-111111111111"


class RecordingRunner:
    """Record deterministic provider invocations."""

    def __init__(
        self,
        result: TaskwarriorRunResult,
    ) -> None:
        """Configure one fixed runner result."""
        self.result = result
        self.calls: list[tuple[tuple[str, ...], str]] = []

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        operation: str,
    ) -> TaskwarriorRunResult:
        """Record and return one fixed result."""
        self.calls.append((arguments, operation))
        return self.result


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
            arguments=("/opt/task", "export"),
            return_code=0,
            stdout=stdout,
            stderr="",
            duration_seconds=0.01,
        ),
        issues=(),
    )


def failed_run() -> TaskwarriorRunResult:
    """Return one failed captured invocation."""
    return TaskwarriorRunResult(
        success=False,
        command=None,
        issues=(
            TaskProviderIssue(
                code="taskwarrior_process_failed",
                message="Taskwarrior failed.",
                provider="taskwarrior",
                operation="list",
                return_code=1,
            ),
        ),
    )


def test_provider_satisfies_task_provider_protocol(
    tmp_path: Path,
) -> None:
    """The adapter should expose the complete provider interface."""
    runner = RecordingRunner(successful_run("[]"))
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )

    assert isinstance(provider, TaskProvider)


def test_default_list_uses_pending_filter(
    tmp_path: Path,
) -> None:
    """Default provider listing should export pending tasks."""
    runner = RecordingRunner(successful_run("[]"))
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )

    result = provider.list_tasks(TaskListQuery())

    assert result.success is True
    assert result.tasks == ()
    assert runner.calls == [
        (("status:pending", "export"), "list"),
    ]


def test_list_builds_filters_in_deterministic_order(
    tmp_path: Path,
) -> None:
    """Supported exact filters should have stable argument order."""
    runner = RecordingRunner(successful_run("[]"))
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )
    query = TaskListQuery(
        uuid=TASK_UUID,
        status=TaskStatus.COMPLETED,
        project="lea project",
        tag="urgent",
    )

    result = provider.list_tasks(query)

    assert result.success is True
    assert runner.calls == [
        (
            (
                TASK_UUID,
                "status:completed",
                "project:lea project",
                "+urgent",
                "export",
            ),
            "list",
        ),
    ]


def test_list_can_export_without_status_filter(
    tmp_path: Path,
) -> None:
    """An explicit None status should not add a status filter."""
    runner = RecordingRunner(successful_run("[]"))
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )

    result = provider.list_tasks(
        TaskListQuery(status=None),
    )

    assert result.success is True
    assert runner.calls == [
        (("export",), "list"),
    ]


def test_list_parses_exported_tasks(
    tmp_path: Path,
) -> None:
    """Provider listing should reconstruct immutable task records."""
    payload = f"""
    [
      {{
        "uuid": "{TASK_UUID}",
        "description": "Review adapter",
        "status": "pending",
        "entry": "20260721T172608Z",
        "project": "lea",
        "tags": ["adapter", "task"]
      }}
    ]
    """
    runner = RecordingRunner(successful_run(payload))
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )

    result = provider.list_tasks(TaskListQuery())

    assert result.success is True
    assert len(result.tasks) == 1
    task = result.tasks[0]
    assert task.uuid == TASK_UUID
    assert task.description == "Review adapter"
    assert task.entry == datetime(
        2026,
        7,
        21,
        17,
        26,
        8,
        tzinfo=UTC,
    )
    assert task.project == "lea"
    assert task.tags == ("adapter", "task")


def test_list_preserves_runner_failure(
    tmp_path: Path,
) -> None:
    """Process failures should remain structured provider failures."""
    runner = RecordingRunner(failed_run())
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )

    result = provider.list_tasks(TaskListQuery())

    assert result.success is False
    assert result.tasks == ()
    assert result.issues == failed_run().issues


def test_list_preserves_parser_failure(
    tmp_path: Path,
) -> None:
    """Malformed export data should remain a structured failure."""
    runner = RecordingRunner(successful_run("{invalid json}"))
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )

    result = provider.list_tasks(TaskListQuery())

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_export_invalid_json"


def test_delete_is_read_only(
    tmp_path: Path,
) -> None:
    """Deletion should remain disabled without invoking Taskwarrior."""
    runner = RecordingRunner(successful_run("[]"))
    provider = TaskwarriorCliProvider(
        make_config(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )

    delete = provider.delete_task(TASK_UUID)

    assert delete.success is False
    assert delete.issues[0].operation == "delete"
    assert runner.calls == []
