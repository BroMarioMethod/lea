"""Local CLI task command services."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from lea.adapters.taskwarrior import (
    TaskwarriorCliProvider,
    TaskwarriorConfig,
)
from lea.cli.contracts import (
    CliIssue,
    CliResult,
    JsonValue,
    LocalCliExitCode,
)
from lea.installers.taskwarrior import (
    TaskwarriorInstallationRecord,
    read_taskwarrior_installation_record,
)
from lea.runtime import (
    ConfigurationResult,
    RuntimeProfile,
    load_runtime_config,
)
from lea.tasks import (
    TaskCreateRequest,
    TaskCreateResult,
    TaskListQuery,
    TaskListResult,
    TaskModifyRequest,
    TaskMutationResult,
    TaskProvider,
    TaskProviderIssue,
    TaskRecord,
)

ConfigurationLoader = Callable[[str | Path], ConfigurationResult]
InstallationRecordReader = Callable[
    [Path],
    tuple[TaskwarriorInstallationRecord | None, tuple[object, ...]],
]
TaskProviderFactory = Callable[[TaskwarriorConfig], TaskProvider]


@dataclass(frozen=True, slots=True)
class TaskCommandDependencies:
    """Injected dependencies for Local CLI task commands."""

    load_configuration: ConfigurationLoader = load_runtime_config
    read_installation_record: InstallationRecordReader = (
        read_taskwarrior_installation_record
    )
    create_provider: TaskProviderFactory = TaskwarriorCliProvider


def execute_task_list(
    *,
    config_path: Path,
    expected_profile: RuntimeProfile | None,
    query: TaskListQuery,
    dependencies: TaskCommandDependencies | None = None,
) -> CliResult:
    """List tasks through the configured provider-neutral boundary."""
    provider_result = _load_task_provider(
        config_path=config_path,
        expected_profile=expected_profile,
        dependencies=dependencies,
    )

    if isinstance(provider_result, CliResult):
        return _with_task_list_data(provider_result)

    return _map_task_list_result(provider_result.list_tasks(query))


def execute_task_create(
    *,
    config_path: Path,
    expected_profile: RuntimeProfile | None,
    request: TaskCreateRequest,
    dependencies: TaskCommandDependencies | None = None,
) -> CliResult:
    """Create one task through the configured provider-neutral boundary."""
    provider_result = _load_task_provider(
        config_path=config_path,
        expected_profile=expected_profile,
        dependencies=dependencies,
    )

    if isinstance(provider_result, CliResult):
        return _with_task_data(provider_result)

    return _map_task_create_result(provider_result.create_task(request))


def execute_task_modify(
    *,
    config_path: Path,
    expected_profile: RuntimeProfile | None,
    request: TaskModifyRequest,
    dependencies: TaskCommandDependencies | None = None,
) -> CliResult:
    """Modify one task through the configured provider-neutral boundary."""
    provider_result = _load_task_provider(
        config_path=config_path,
        expected_profile=expected_profile,
        dependencies=dependencies,
    )

    if isinstance(provider_result, CliResult):
        return _with_task_data(provider_result)

    return _map_task_mutation_result(
        provider_result.modify_task(request),
        success_message="Task modified",
    )


def execute_task_complete(
    *,
    config_path: Path,
    expected_profile: RuntimeProfile | None,
    task_uuid: str,
    dependencies: TaskCommandDependencies | None = None,
) -> CliResult:
    """Complete one task through the configured provider-neutral boundary."""
    provider_result = _load_task_provider(
        config_path=config_path,
        expected_profile=expected_profile,
        dependencies=dependencies,
    )

    if isinstance(provider_result, CliResult):
        return _with_task_data(provider_result)

    return _map_task_mutation_result(
        provider_result.complete_task(task_uuid),
        success_message="Task completed",
    )


def render_task_list_result(result: CliResult) -> str:
    """Render one stable human-readable task list."""
    data = result.data

    if not isinstance(data, dict):
        return _render_issues(result)

    tasks = data.get("tasks")

    if not isinstance(tasks, list):
        return _render_issues(result)

    if not tasks:
        return "No tasks found." if result.success else _render_issues(result)

    lines = [
        "Tasks",
        "",
        "UUID                                 Status     Description",
    ]

    for raw_task in tasks:
        if not isinstance(raw_task, dict):
            continue

        task = cast(dict[str, object], raw_task)
        lines.extend(_render_task_lines(task))

    return "\n".join(lines)


def render_task_create_result(result: CliResult) -> str:
    """Render one stable human-readable task-creation result."""
    data = result.data

    if not isinstance(data, dict):
        return _render_issues(result)

    raw_task = data.get("task")

    if not isinstance(raw_task, dict):
        return _render_issues(result)

    task = cast(dict[str, object], raw_task)
    lines = ["Task created", ""]
    lines.extend(_render_task_lines(task))
    return "\n".join(lines)


def _load_task_provider(
    *,
    config_path: Path,
    expected_profile: RuntimeProfile | None,
    dependencies: TaskCommandDependencies | None,
) -> TaskProvider | CliResult:
    """Load and inspect the configured provider without storage discovery."""
    resolved = dependencies or TaskCommandDependencies()
    configuration = resolved.load_configuration(config_path)

    if not configuration.success:
        return CliResult.failed(
            exit_code=LocalCliExitCode.CONFIGURATION_ERROR,
            issues=tuple(
                CliIssue(
                    code=issue.code,
                    message=issue.message,
                    field=issue.field,
                )
                for issue in configuration.issues
            ),
        )

    config = configuration.config

    if config is None:
        return _internal_failure(
            "Successful configuration loading returned no runtime configuration."
        )

    if expected_profile is not None and config.profile is not expected_profile:
        return CliResult.failed(
            exit_code=LocalCliExitCode.CONFIGURATION_ERROR,
            issues=(
                CliIssue(
                    code="configuration_profile_mismatch",
                    message=(
                        "The loaded runtime profile does not match "
                        "the requested profile."
                    ),
                    field="profile",
                ),
            ),
        )

    record, record_issues = resolved.read_installation_record(
        config.component_records.taskwarrior
    )

    if record is None:
        return CliResult.failed(
            exit_code=LocalCliExitCode.PROVIDER_UNAVAILABLE,
            issues=_installation_record_issues(record_issues),
        )

    provider = resolved.create_provider(_provider_config(record))
    inspection = provider.inspect()

    if not inspection.available:
        return CliResult.failed(
            exit_code=LocalCliExitCode.PROVIDER_UNAVAILABLE,
            issues=tuple(
                CliIssue(
                    code=issue.code,
                    message=issue.message,
                    field=issue.field,
                )
                for issue in inspection.issues
            ),
        )

    return provider


def _map_task_list_result(result: TaskListResult) -> CliResult:
    """Map one provider task-list result to the Local CLI contract."""
    if not result.success:
        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=_provider_issues(result.issues),
            data={"tasks": []},
        )

    return CliResult.succeeded(
        data={"tasks": [_task_to_json(task) for task in result.tasks]},
    )


def _map_task_mutation_result(
    result: TaskMutationResult,
    *,
    success_message: str,
) -> CliResult:
    """Map one provider task-mutation result to the Local CLI contract."""
    if not result.success:
        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=_provider_issues(result.issues),
            data={"task": None},
        )

    task = result.task

    if task is None:
        return _with_task_data(
            _internal_failure("Successful task mutation returned no task.")
        )

    return CliResult.succeeded(
        data={
            "message": success_message,
            "task": _task_to_json(task),
        },
    )


def render_task_complete_result(result: CliResult) -> str:
    """Render one stable human-readable task-completion result."""
    return _render_task_mutation_result(
        result,
        default_heading="Task completed",
    )


def render_task_modify_result(result: CliResult) -> str:
    """Render one stable human-readable task-modification result."""
    data = result.data

    if not isinstance(data, dict):
        return _render_issues(result)

    raw_task = data.get("task")

    if not isinstance(raw_task, dict):
        return _render_issues(result)

    return _render_task_mutation_result(
        result,
        default_heading="Task modified",
    )


def _render_task_mutation_result(
    result: CliResult,
    *,
    default_heading: str,
) -> str:
    """Render one stable human-readable task mutation."""
    data = result.data

    if not isinstance(data, dict):
        return _render_issues(result)

    raw_task = data.get("task")

    if not isinstance(raw_task, dict):
        return _render_issues(result)

    task = cast(dict[str, object], raw_task)
    message = data.get("message")
    heading = str(message) if message is not None else default_heading
    lines = [heading, ""]
    lines.extend(_render_task_lines(task))
    return "\n".join(lines)


def _map_task_create_result(result: TaskCreateResult) -> CliResult:
    """Map one provider task-creation result to the Local CLI contract."""
    if not result.success:
        return CliResult.failed(
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
            issues=_provider_issues(result.issues),
            data={"task": None},
        )

    task = result.task

    if task is None:
        return _with_task_data(
            _internal_failure("Successful task creation returned no task.")
        )

    return CliResult.succeeded(
        data={"task": _task_to_json(task)},
    )


def _task_to_json(task: TaskRecord) -> JsonValue:
    """Serialise one canonical task record."""
    return {
        "description": task.description,
        "due": task.due.isoformat() if task.due is not None else None,
        "entry": task.entry.isoformat(),
        "modified": (task.modified.isoformat() if task.modified is not None else None),
        "priority": task.priority,
        "project": task.project,
        "status": task.status.value,
        "tags": list(task.tags),
        "uuid": task.uuid,
    }


def _render_task_lines(task: dict[str, object]) -> list[str]:
    """Render one task and its optional details."""
    lines = [
        (
            f"{task.get('uuid', '')!s:<36} "
            f"{task.get('status', '')!s:<10} "
            f"{task.get('description', '')!s}"
        )
    ]
    details: list[str] = []

    if task.get("project") is not None:
        details.append(f"project={task['project']}")

    tags = task.get("tags")
    if isinstance(tags, list) and tags:
        details.append("tags=" + ",".join(str(tag) for tag in tags))

    if task.get("priority") is not None:
        details.append(f"priority={task['priority']}")

    if task.get("due") is not None:
        details.append(f"due={task['due']}")

    if details:
        lines.append("  " + " | ".join(details))

    return lines


def _provider_issues(
    issues: tuple[TaskProviderIssue, ...],
) -> tuple[CliIssue, ...]:
    """Map provider issues to Local CLI issues."""
    return tuple(
        CliIssue(
            code=str(issue.code),
            message=str(issue.message),
            field=getattr(issue, "field", None),
        )
        for issue in issues
    )


def _installation_record_issues(
    issues: tuple[object, ...],
) -> tuple[CliIssue, ...]:
    """Map installer-record issues to Local CLI issues."""
    mapped = tuple(
        CliIssue(
            code=str(
                getattr(
                    issue,
                    "code",
                    "taskwarrior_install_record_failed",
                )
            ),
            message=str(
                getattr(
                    issue,
                    "message",
                    ("The Taskwarrior installation record could not be loaded."),
                )
            ),
            field=getattr(issue, "field", None),
        )
        for issue in issues
    )

    if mapped:
        return mapped

    return (
        CliIssue(
            code="taskwarrior_install_record_failed",
            message=("The Taskwarrior installation record could not be loaded."),
        ),
    )


def _provider_config(
    record: TaskwarriorInstallationRecord,
) -> TaskwarriorConfig:
    """Construct one provider configuration from a validated record."""
    return TaskwarriorConfig(
        executable=record.executable,
        taskrc=record.taskrc,
        data_dir=record.data,
        home_dir=record.home,
    )


def _with_task_list_data(result: CliResult) -> CliResult:
    """Attach the stable task-list failure data shape."""
    if result.success:
        return result

    return CliResult.failed(
        exit_code=result.exit_code,
        issues=result.issues,
        data={"tasks": []},
    )


def _with_task_data(result: CliResult) -> CliResult:
    """Attach the stable task-creation failure data shape."""
    if result.success:
        return result

    return CliResult.failed(
        exit_code=result.exit_code,
        issues=result.issues,
        data={"task": None},
    )


def _render_issues(result: CliResult) -> str:
    """Render task-command issues when no task data is available."""
    if not result.issues:
        return "Task command failed."

    return "\n".join(f"{issue.code}: {issue.message}" for issue in result.issues)


def _internal_failure(message: str) -> CliResult:
    """Construct one deterministic internal failure."""
    return CliResult.failed(
        exit_code=LocalCliExitCode.INTERNAL_ERROR,
        issues=(
            CliIssue(
                code="internal_error",
                message=message,
            ),
        ),
    )
