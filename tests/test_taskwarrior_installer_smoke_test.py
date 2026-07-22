"""Tests for isolated staged Taskwarrior lifecycle validation."""

import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from lea.adapters.taskwarrior import TaskwarriorConfig
from lea.installers.taskwarrior import (
    TaskwarriorInstallFailureCode,
    TaskwarriorStagedBinary,
    validate_staged_taskwarrior_binary,
)
from lea.tasks import (
    TaskCreateRequest,
    TaskCreateResult,
    TaskListQuery,
    TaskListResult,
    TaskModifyRequest,
    TaskMutationResult,
    TaskRecord,
    TaskStatus,
)

FIRST_UUID = "11111111-1111-4111-8111-111111111111"
SECOND_UUID = "22222222-2222-4222-8222-222222222222"
ENTRY = datetime(2026, 7, 21, 17, 26, 8, tzinfo=UTC)


def make_staged_binary(
    tmp_path: Path,
    *,
    version: str = "3.4.2",
) -> TaskwarriorStagedBinary:
    """Create one staged executable that supports `_version`."""
    staging_root = tmp_path / "stage"
    executable = staging_root / "bin" / "task"
    executable.parent.mkdir(parents=True)
    executable.write_text(
        f"#!/bin/sh\nprintf '%s\\n' '{version}'\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

    return TaskwarriorStagedBinary(
        staging_root=staging_root,
        executable=executable,
        sha256="a" * 64,
    )


def task_record(
    *,
    uuid: str,
    description: str,
    status: TaskStatus = TaskStatus.PENDING,
    tags: tuple[str, ...] = (),
) -> TaskRecord:
    """Return one provider-neutral task record."""
    return TaskRecord(
        uuid=uuid,
        description=description,
        status=status,
        entry=ENTRY,
        project="lea.install",
        tags=tags,
    )


class SuccessfulProvider:
    """Return a successful deterministic lifecycle."""

    configs: ClassVar[list[TaskwarriorConfig]] = []

    def __init__(self, config: TaskwarriorConfig) -> None:
        """Record isolated configuration."""
        self.config = config
        self.create_count = 0
        type(self).configs.append(config)

    def create_task(
        self,
        request: TaskCreateRequest,
    ) -> TaskCreateResult:
        """Create deterministic first and second tasks."""
        self.create_count += 1
        uuid = FIRST_UUID if self.create_count == 1 else SECOND_UUID

        return TaskCreateResult(
            success=True,
            task=task_record(
                uuid=uuid,
                description=request.description,
                tags=request.tags,
            ),
            issues=(),
        )

    def list_tasks(
        self,
        query: TaskListQuery,
    ) -> TaskListResult:
        """Return the exact first task."""
        assert query.uuid == FIRST_UUID

        return TaskListResult(
            success=True,
            tasks=(
                task_record(
                    uuid=FIRST_UUID,
                    description=("LEA Taskwarrior installer smoke test"),
                    tags=("lea_smoke_test",),
                ),
            ),
            issues=(),
        )

    def modify_task(
        self,
        request: TaskModifyRequest,
    ) -> TaskMutationResult:
        """Return the expected modified first task."""
        return TaskMutationResult(
            success=True,
            task=task_record(
                uuid=request.task_uuid,
                description=("LEA Taskwarrior installer smoke test modified"),
                tags=("lea_smoke_test", "modified"),
            ),
            issues=(),
        )

    def complete_task(
        self,
        task_uuid: str,
    ) -> TaskMutationResult:
        """Return the completed first task."""
        return TaskMutationResult(
            success=True,
            task=task_record(
                uuid=task_uuid,
                description=("LEA Taskwarrior installer smoke test modified"),
                status=TaskStatus.COMPLETED,
            ),
            issues=(),
        )

    def delete_task(
        self,
        task_uuid: str,
    ) -> TaskMutationResult:
        """Return the deleted second task."""
        return TaskMutationResult(
            success=True,
            task=task_record(
                uuid=task_uuid,
                description=("LEA Taskwarrior installer deletion smoke test"),
                status=TaskStatus.DELETED,
            ),
            issues=(),
        )


class FailingCreateProvider(SuccessfulProvider):
    """Fail the first lifecycle mutation."""

    def create_task(
        self,
        request: TaskCreateRequest,
    ) -> TaskCreateResult:
        """Return a failed creation result."""
        from lea.tasks import TaskProviderIssue

        return TaskCreateResult(
            success=False,
            task=None,
            issues=(
                TaskProviderIssue(
                    code="test_create_failed",
                    message="Creation failed.",
                ),
            ),
        )


def test_smoke_test_passes_complete_lifecycle(
    tmp_path: Path,
) -> None:
    """A valid staged executable and lifecycle should pass."""
    SuccessfulProvider.configs.clear()
    staged = make_staged_binary(tmp_path)

    result = validate_staged_taskwarrior_binary(
        staged,
        provider_factory=SuccessfulProvider,  # type: ignore[arg-type]
    )

    assert result.passed is True
    assert result.version == "3.4.2"
    assert result.issues == ()

    config = SuccessfulProvider.configs[-1]
    temporary_root = config.home_dir.parent
    assert config.executable == staged.executable
    assert config.taskrc.name == "taskrc"
    assert not temporary_root.exists()


def test_smoke_test_rejects_unsupported_version(
    tmp_path: Path,
) -> None:
    """Unsupported staged versions should fail before lifecycle calls."""
    staged = make_staged_binary(
        tmp_path,
        version="2.6.2",
    )

    result = validate_staged_taskwarrior_binary(
        staged,
        provider_factory=SuccessfulProvider,  # type: ignore[arg-type]
    )

    assert result.passed is False
    assert result.version is None
    assert result.issues[0].code is TaskwarriorInstallFailureCode.SMOKE_TEST_FAILED


def test_smoke_test_reports_lifecycle_failure(
    tmp_path: Path,
) -> None:
    """Provider lifecycle failures should block installation."""
    staged = make_staged_binary(tmp_path)

    result = validate_staged_taskwarrior_binary(
        staged,
        provider_factory=FailingCreateProvider,  # type: ignore[arg-type]
    )

    assert result.passed is False
    assert "failed task creation" in result.issues[0].message


def test_smoke_test_removes_temporary_data_after_failure(
    tmp_path: Path,
) -> None:
    """Disposable task data should be removed on ordinary failure."""
    FailingCreateProvider.configs.clear()
    staged = make_staged_binary(tmp_path)

    validate_staged_taskwarrior_binary(
        staged,
        provider_factory=FailingCreateProvider,  # type: ignore[arg-type]
    )

    config = FailingCreateProvider.configs[-1]
    assert not config.home_dir.parent.exists()
    assert staged.staging_root.exists()
    assert staged.executable.exists()
