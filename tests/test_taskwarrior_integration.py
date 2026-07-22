"""Real Taskwarrior 3.4.x integration tests."""

import os
from pathlib import Path

import pytest

from lea.adapters.taskwarrior import (
    TaskwarriorCliProvider,
    TaskwarriorConfig,
)
from lea.tasks import (
    TaskCreateRequest,
    TaskListQuery,
    TaskModifyRequest,
    TaskStatus,
)

_DEFAULT_EXECUTABLE = Path("/opt/lea-tools/taskwarrior/3.4.2/bin/task")


def _taskwarrior_executable() -> Path:
    """Return the configured real Taskwarrior executable."""
    configured = os.environ.get("LEA_TEST_TASKWARRIOR_EXECUTABLE")
    return Path(configured) if configured is not None else _DEFAULT_EXECUTABLE


def _require_real_taskwarrior() -> Path:
    """Skip when the real Taskwarrior binary is unavailable."""
    executable = _taskwarrior_executable()

    if not executable.is_file():
        pytest.skip(f"Taskwarrior executable not found: {executable}")

    if not os.access(executable, os.X_OK):
        pytest.skip(f"Taskwarrior executable is not executable: {executable}")

    return executable


def _provider(tmp_path: Path) -> TaskwarriorCliProvider:
    """Create one fully isolated real Taskwarrior provider."""
    executable = _require_real_taskwarrior()
    taskrc = tmp_path / "config" / "taskrc"
    data_dir = tmp_path / "data"
    home_dir = tmp_path / "home"
    working_dir = tmp_path / "working"

    taskrc.parent.mkdir(parents=True)
    data_dir.mkdir()
    home_dir.mkdir()
    working_dir.mkdir()

    taskrc.write_text(
        ("confirmation=no\nhooks=0\nverbose=nothing\n"),
        encoding="utf-8",
    )

    return TaskwarriorCliProvider(
        TaskwarriorConfig(
            executable=executable,
            taskrc=taskrc,
            data_dir=data_dir,
            home_dir=home_dir,
            working_dir=working_dir,
            timeout_seconds=10.0,
        )
    )


def test_real_taskwarrior_inspection(
    tmp_path: Path,
) -> None:
    """The configured real Taskwarrior 3.4.x should pass inspection."""
    result = _provider(tmp_path).inspect()

    assert result.available is True
    assert result.provider == "taskwarrior"
    assert result.version is not None
    assert result.version.startswith("3.4.")
    assert result.issues == ()


def test_real_taskwarrior_full_lifecycle(
    tmp_path: Path,
) -> None:
    """Create, list, modify and complete one real isolated task."""
    provider = _provider(tmp_path)

    created = provider.create_task(
        TaskCreateRequest(
            description="LEA integration lifecycle task",
            project="lea.integration",
            priority="H",
            tags=("integration", "lifecycle"),
        )
    )

    assert created.success is True
    assert created.task is not None
    task_uuid = created.task.uuid
    assert created.task.status is TaskStatus.PENDING

    listed = provider.list_tasks(TaskListQuery(uuid=task_uuid))

    assert listed.success is True
    assert len(listed.tasks) == 1
    assert listed.tasks[0].uuid == task_uuid

    modified = provider.modify_task(
        TaskModifyRequest(
            task_uuid=task_uuid,
            description="LEA integration lifecycle updated",
            project="lea.integration.updated",
            priority="M",
            add_tags=("updated",),
            remove_tags=("lifecycle",),
        )
    )

    assert modified.success is True
    assert modified.task is not None
    assert modified.task.description == "LEA integration lifecycle updated"
    assert modified.task.project == "lea.integration.updated"
    assert modified.task.priority == "M"
    assert modified.task.tags == ("integration", "updated")

    completed = provider.complete_task(task_uuid)

    assert completed.success is True
    assert completed.task is not None
    assert completed.task.uuid == task_uuid
    assert completed.task.status is TaskStatus.COMPLETED


def test_real_taskwarrior_delete(
    tmp_path: Path,
) -> None:
    """Delete one exact real isolated task."""
    provider = _provider(tmp_path)

    created = provider.create_task(
        TaskCreateRequest(
            description="LEA integration deletion task",
            tags=("integration", "delete"),
        )
    )

    assert created.success is True
    assert created.task is not None

    deleted = provider.delete_task(created.task.uuid)

    assert deleted.success is True
    assert deleted.task is not None
    assert deleted.task.uuid == created.task.uuid
    assert deleted.task.status is TaskStatus.DELETED
