"""Tests for the Local CLI task-modify command."""

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from lea.cli import LocalCliExitCode
from lea.cli.task_commands import (
    TaskCommandDependencies,
    execute_task_modify,
    render_task_modify_result,
)
from lea.installers.taskwarrior import TaskwarriorInstallationRecord
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
    TaskProviderIssue,
    TaskRecord,
    TaskStatus,
)

TASK_UUID = "11111111-1111-4111-8111-111111111111"


class RecordingProvider:
    """Record provider-neutral task-modification calls."""

    def __init__(self, result: TaskMutationResult) -> None:
        self.result = result
        self.requests: list[TaskModifyRequest] = []

    def inspect(self) -> TaskProviderInspectionResult:
        return TaskProviderInspectionResult(
            available=True,
            provider="taskwarrior",
            version="3.4.2",
            issues=(),
        )

    def modify_task(
        self,
        request: TaskModifyRequest,
    ) -> TaskMutationResult:
        self.requests.append(request)
        return self.result

    def create_task(
        self,
        request: TaskCreateRequest,
    ) -> TaskCreateResult:
        raise AssertionError

    def list_tasks(self, query: TaskListQuery) -> TaskListResult:
        raise AssertionError

    def complete_task(self, task_uuid: str) -> TaskMutationResult:
        raise AssertionError

    def delete_task(self, task_uuid: str) -> TaskMutationResult:
        raise AssertionError


def _configuration(tmp_path: Path) -> ConfigurationResult:
    config = isolated_test_runtime_config(tmp_path / "runtime")
    return ConfigurationResult(success=True, config=config, issues=())


def _record(tmp_path: Path) -> TaskwarriorInstallationRecord:
    root = tmp_path / "runtime"
    return TaskwarriorInstallationRecord(
        schema_version=1,
        component="taskwarrior",
        version="3.4.2",
        mode="external-executable",
        platform="linux-aarch64",
        executable=root / "tools" / "task",
        sha256="a" * 64,
        taskrc=root / "taskrc",
        home=root / "home",
        data=root / "data",
        smoke_test="passed",
        installed_at=datetime(2026, 7, 22, tzinfo=UTC),
    )


def test_task_modify_preserves_request_and_returns_task(
    tmp_path: Path,
) -> None:
    task = TaskRecord(
        uuid=TASK_UUID,
        description="Updated CLI task",
        status=TaskStatus.PENDING,
        entry=datetime(2026, 7, 22, 12, 0, tzinfo=UTC),
        modified=datetime(2026, 7, 22, 13, 0, tzinfo=UTC),
        project="lea.updated",
        tags=("cli", "updated"),
        priority="M",
    )
    provider = RecordingProvider(TaskMutationResult(success=True, task=task, issues=()))
    request = TaskModifyRequest(
        task_uuid=TASK_UUID,
        description="Updated CLI task",
        project="lea.updated",
        priority="M",
        add_tags=("updated", "cli"),
        remove_tags=("create",),
    )

    result = execute_task_modify(
        config_path=tmp_path / "runtime" / "config" / "lea.toml",
        expected_profile=RuntimeProfile.TEST,
        request=request,
        dependencies=TaskCommandDependencies(
            load_configuration=lambda path: _configuration(tmp_path),
            read_installation_record=lambda path: (_record(tmp_path), ()),
            create_provider=lambda config: provider,
        ),
    )

    assert result.success is True
    assert provider.requests == [request]
    assert isinstance(result.data, dict)

    data = cast(dict[str, object], result.data)
    assert data["message"] == "Task modified"
    assert "Task modified" in render_task_modify_result(result)


def test_task_modify_failure_maps_to_application_error(
    tmp_path: Path,
) -> None:
    provider = RecordingProvider(
        TaskMutationResult(
            success=False,
            task=None,
            issues=(
                TaskProviderIssue(
                    code="taskwarrior_process_failed",
                    message="Taskwarrior failed.",
                    provider="taskwarrior",
                    operation="modify",
                ),
            ),
        )
    )

    result = execute_task_modify(
        config_path=tmp_path / "runtime" / "config" / "lea.toml",
        expected_profile=None,
        request=TaskModifyRequest(
            task_uuid=TASK_UUID,
            description="Updated CLI task",
        ),
        dependencies=TaskCommandDependencies(
            load_configuration=lambda path: _configuration(tmp_path),
            read_installation_record=lambda path: (_record(tmp_path), ()),
            create_provider=lambda config: provider,
        ),
    )

    assert result.exit_code is LocalCliExitCode.APPLICATION_ERROR
    assert result.data == {"task": None}
