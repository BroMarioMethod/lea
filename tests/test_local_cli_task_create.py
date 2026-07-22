"""Tests for the Local CLI task-create command."""

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from lea.cli import CliResult, LocalCliExitCode
from lea.cli.task_commands import (
    TaskCommandDependencies,
    execute_task_create,
    render_task_create_result,
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
    """Record provider-neutral task-creation calls."""

    def __init__(
        self,
        result: TaskCreateResult,
        *,
        available: bool = True,
    ) -> None:
        self.result = result
        self.available = available
        self.requests: list[TaskCreateRequest] = []

    def inspect(self) -> TaskProviderInspectionResult:
        if self.available:
            return TaskProviderInspectionResult(
                available=True,
                provider="taskwarrior",
                version="3.4.2",
                issues=(),
            )

        return TaskProviderInspectionResult(
            available=False,
            provider="taskwarrior",
            version=None,
            issues=(
                TaskProviderIssue(
                    code="taskwarrior_process_failed",
                    message="Taskwarrior could not be inspected.",
                    provider="taskwarrior",
                    operation="inspect",
                ),
            ),
        )

    def create_task(
        self,
        request: TaskCreateRequest,
    ) -> TaskCreateResult:
        self.requests.append(request)
        return self.result

    def list_tasks(self, query: TaskListQuery) -> TaskListResult:
        raise AssertionError

    def modify_task(
        self,
        request: TaskModifyRequest,
    ) -> TaskMutationResult:
        raise AssertionError

    def complete_task(
        self,
        task_uuid: str,
    ) -> TaskMutationResult:
        raise AssertionError

    def delete_task(
        self,
        task_uuid: str,
    ) -> TaskMutationResult:
        raise AssertionError


def _configuration(tmp_path: Path) -> ConfigurationResult:
    config = isolated_test_runtime_config(tmp_path / "runtime")

    return ConfigurationResult(
        success=True,
        config=config,
        issues=(),
    )


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


def _dependencies(
    tmp_path: Path,
    provider: RecordingProvider,
) -> TaskCommandDependencies:
    return TaskCommandDependencies(
        load_configuration=lambda path: _configuration(tmp_path),
        read_installation_record=lambda path: (_record(tmp_path), ()),
        create_provider=lambda config: provider,
    )


def test_task_create_preserves_request_and_returns_task(
    tmp_path: Path,
) -> None:
    task = TaskRecord(
        uuid=TASK_UUID,
        description="Create CLI task",
        status=TaskStatus.PENDING,
        entry=datetime(2026, 7, 22, 12, 0, tzinfo=UTC),
        project="lea",
        tags=("cli", "create"),
        priority="H",
    )
    provider = RecordingProvider(
        TaskCreateResult(
            success=True,
            task=task,
            issues=(),
        )
    )
    request = TaskCreateRequest(
        description="Create CLI task",
        project="lea",
        priority="H",
        tags=("create", "cli"),
    )

    result = execute_task_create(
        config_path=tmp_path / "runtime" / "config" / "lea.toml",
        expected_profile=RuntimeProfile.TEST,
        request=request,
        dependencies=_dependencies(tmp_path, provider),
    )

    assert result.success is True
    assert result.exit_code is LocalCliExitCode.SUCCESS
    assert provider.requests == [request]
    assert isinstance(result.data, dict)

    data = cast(dict[str, object], result.data)
    raw_task = data["task"]
    assert isinstance(raw_task, dict)
    assert cast(dict[str, object], raw_task)["uuid"] == TASK_UUID
    assert "Task created" in render_task_create_result(result)


def test_task_create_failure_maps_to_application_error(
    tmp_path: Path,
) -> None:
    provider = RecordingProvider(
        TaskCreateResult(
            success=False,
            task=None,
            issues=(
                TaskProviderIssue(
                    code="taskwarrior_process_failed",
                    message="Taskwarrior failed.",
                    provider="taskwarrior",
                    operation="create",
                ),
            ),
        )
    )

    result = execute_task_create(
        config_path=tmp_path / "runtime" / "config" / "lea.toml",
        expected_profile=None,
        request=TaskCreateRequest(description="Create CLI task"),
        dependencies=_dependencies(tmp_path, provider),
    )

    assert result.exit_code is LocalCliExitCode.APPLICATION_ERROR
    assert result.data == {"task": None}
    assert result.issues[0].code == "taskwarrior_process_failed"


def test_task_create_unavailable_provider_maps_to_exit_eight(
    tmp_path: Path,
) -> None:
    provider = RecordingProvider(
        TaskCreateResult(
            success=False,
            task=None,
            issues=(
                TaskProviderIssue(
                    code="unused",
                    message="Unused.",
                ),
            ),
        ),
        available=False,
    )

    result = execute_task_create(
        config_path=tmp_path / "runtime" / "config" / "lea.toml",
        expected_profile=None,
        request=TaskCreateRequest(description="Create CLI task"),
        dependencies=_dependencies(tmp_path, provider),
    )

    assert result.exit_code is LocalCliExitCode.PROVIDER_UNAVAILABLE
    assert result.data == {"task": None}


def test_task_create_renderer_discloses_tag_normalisation() -> None:
    """Human output should disclose changed task tags."""
    result = CliResult.succeeded(
        data={
            "task": {
                "description": "Create CLI task",
                "due": None,
                "entry": "2026-07-22T12:00:00+00:00",
                "modified": None,
                "priority": None,
                "project": None,
                "status": "pending",
                "tags": ["local_cli"],
                "uuid": TASK_UUID,
            },
            "normalisations": [
                {
                    "field": "tag",
                    "input": "local-cli",
                    "value": "local_cli",
                }
            ],
        }
    )

    rendered = render_task_create_result(result)

    assert "Tag 'local-cli' was normalised to 'local_cli'." in rendered
