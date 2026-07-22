"""Tests for the Local CLI task-list command."""

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from lea.cli import LocalCliExitCode
from lea.cli.task_commands import (
    TaskCommandDependencies,
    execute_task_list,
    render_task_list_result,
)
from lea.installers.taskwarrior import TaskwarriorInstallationRecord
from lea.runtime import (
    ConfigurationIssue,
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
    """Record provider-neutral task-list calls."""

    def __init__(
        self,
        result: TaskListResult,
        *,
        available: bool = True,
    ) -> None:
        self.result = result
        self.available = available
        self.queries: list[TaskListQuery] = []

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

    def list_tasks(self, query: TaskListQuery) -> TaskListResult:
        self.queries.append(query)
        return self.result

    def create_task(
        self,
        request: TaskCreateRequest,
    ) -> TaskCreateResult:
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


def test_empty_task_list_is_successful(tmp_path: Path) -> None:
    provider = RecordingProvider(
        TaskListResult(
            success=True,
            tasks=(),
            issues=(),
        )
    )

    result = execute_task_list(
        config_path=tmp_path / "runtime" / "config" / "lea.toml",
        expected_profile=RuntimeProfile.TEST,
        query=TaskListQuery(),
        dependencies=_dependencies(tmp_path, provider),
    )

    assert result.success is True
    assert result.exit_code is LocalCliExitCode.SUCCESS
    assert result.data == {"tasks": []}
    assert render_task_list_result(result) == "No tasks found."


def test_task_list_preserves_query_and_serialises_tasks(
    tmp_path: Path,
) -> None:
    task = TaskRecord(
        uuid=TASK_UUID,
        description="Review LEA task list",
        status=TaskStatus.PENDING,
        entry=datetime(2026, 7, 22, 12, 0, tzinfo=UTC),
        project="lea",
        tags=("cli", "task"),
        priority="H",
    )
    provider = RecordingProvider(
        TaskListResult(
            success=True,
            tasks=(task,),
            issues=(),
        )
    )
    query = TaskListQuery(
        uuid=TASK_UUID,
        status=TaskStatus.PENDING,
        project="lea",
        tag="cli",
    )

    result = execute_task_list(
        config_path=tmp_path / "runtime" / "config" / "lea.toml",
        expected_profile=None,
        query=query,
        dependencies=_dependencies(tmp_path, provider),
    )

    assert provider.queries == [query]
    assert isinstance(result.data, dict)

    data = cast(dict[str, object], result.data)
    tasks = data["tasks"]
    assert isinstance(tasks, list)

    serialised = cast(dict[str, object], tasks[0])
    assert serialised["uuid"] == TASK_UUID
    assert serialised["tags"] == ["cli", "task"]


def test_configuration_failure_maps_to_exit_three(
    tmp_path: Path,
) -> None:
    result = execute_task_list(
        config_path=tmp_path / "missing.toml",
        expected_profile=None,
        query=TaskListQuery(),
        dependencies=TaskCommandDependencies(
            load_configuration=lambda path: ConfigurationResult(
                success=False,
                config=None,
                issues=(
                    ConfigurationIssue(
                        code="configuration_not_found",
                        message=("The runtime configuration file was not found."),
                        source_path=tmp_path / "missing.toml",
                    ),
                ),
            ),
        ),
    )

    assert result.exit_code is LocalCliExitCode.CONFIGURATION_ERROR


def test_profile_mismatch_maps_to_exit_three(
    tmp_path: Path,
) -> None:
    result = execute_task_list(
        config_path=tmp_path / "runtime" / "config" / "lea.toml",
        expected_profile=RuntimeProfile.SYSTEM,
        query=TaskListQuery(),
        dependencies=TaskCommandDependencies(
            load_configuration=lambda path: _configuration(tmp_path),
        ),
    )

    assert result.exit_code is LocalCliExitCode.CONFIGURATION_ERROR
    assert result.issues[0].code == "configuration_profile_mismatch"


def test_missing_installation_record_maps_to_provider_unavailable(
    tmp_path: Path,
) -> None:
    issue = type(
        "Issue",
        (),
        {
            "code": "taskwarrior_install_record_failed",
            "message": "The installation record does not exist.",
            "field": "installation_record",
        },
    )()

    result = execute_task_list(
        config_path=tmp_path / "runtime" / "config" / "lea.toml",
        expected_profile=None,
        query=TaskListQuery(),
        dependencies=TaskCommandDependencies(
            load_configuration=lambda path: _configuration(tmp_path),
            read_installation_record=lambda path: (None, (issue,)),
        ),
    )

    assert result.exit_code is LocalCliExitCode.PROVIDER_UNAVAILABLE


def test_unavailable_provider_maps_to_exit_eight(
    tmp_path: Path,
) -> None:
    provider = RecordingProvider(
        TaskListResult(
            success=True,
            tasks=(),
            issues=(),
        ),
        available=False,
    )

    result = execute_task_list(
        config_path=tmp_path / "runtime" / "config" / "lea.toml",
        expected_profile=None,
        query=TaskListQuery(),
        dependencies=_dependencies(tmp_path, provider),
    )

    assert result.exit_code is LocalCliExitCode.PROVIDER_UNAVAILABLE


def test_provider_list_failure_maps_to_application_error(
    tmp_path: Path,
) -> None:
    provider = RecordingProvider(
        TaskListResult(
            success=False,
            tasks=(),
            issues=(
                TaskProviderIssue(
                    code="taskwarrior_process_failed",
                    message="Taskwarrior failed.",
                    provider="taskwarrior",
                    operation="list",
                ),
            ),
        )
    )

    result = execute_task_list(
        config_path=tmp_path / "runtime" / "config" / "lea.toml",
        expected_profile=None,
        query=TaskListQuery(),
        dependencies=_dependencies(tmp_path, provider),
    )

    assert result.exit_code is LocalCliExitCode.APPLICATION_ERROR
    assert result.issues[0].code == "taskwarrior_process_failed"
