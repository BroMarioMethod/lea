"""Taskwarrior CLI task provider."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from lea.adapters.taskwarrior.contracts import (
    TaskwarriorConfig,
    TaskwarriorRunResult,
)
from lea.adapters.taskwarrior.inspection import inspect_taskwarrior
from lea.adapters.taskwarrior.parser import parse_taskwarrior_export
from lea.adapters.taskwarrior.runner import TaskwarriorRunner
from lea.tasks import (
    TaskCreateRequest,
    TaskCreateResult,
    TaskListQuery,
    TaskListResult,
    TaskModifyRequest,
    TaskMutationResult,
    TaskProviderInspectionResult,
    TaskProviderIssue,
    TaskStatus,
)

_PROVIDER = "taskwarrior"
_TASKWARRIOR_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"


class _TaskwarriorRunner(Protocol):
    """Minimal runner interface required by the provider."""

    def run(
        self,
        arguments: Sequence[str],
        *,
        operation: str,
    ) -> TaskwarriorRunResult:
        """Run one Taskwarrior command."""
        ...


class TaskwarriorCliProvider:
    """Provider-neutral access through the Taskwarrior CLI."""

    def __init__(
        self,
        config: TaskwarriorConfig,
        *,
        runner: _TaskwarriorRunner | None = None,
    ) -> None:
        """Configure one isolated Taskwarrior CLI provider."""
        self._config = config
        self._runner = runner if runner is not None else TaskwarriorRunner(config)

    @property
    def config(self) -> TaskwarriorConfig:
        """Return the immutable provider configuration."""
        return self._config

    def inspect(self) -> TaskProviderInspectionResult:
        """Inspect provider availability and compatibility."""
        return inspect_taskwarrior(self._config)

    def list_tasks(
        self,
        query: TaskListQuery,
    ) -> TaskListResult:
        """List tasks matching supported exact filters."""
        run_result = self._runner.run(
            _build_list_arguments(query),
            operation="list",
        )

        if not run_result.success:
            return TaskListResult(
                success=False,
                tasks=(),
                issues=run_result.issues,
            )

        command = run_result.command

        if command is None:
            return _list_failure(
                code="taskwarrior_process_failed",
                message=("Taskwarrior listing succeeded without a command result."),
            )

        return parse_taskwarrior_export(command.stdout)

    def create_task(
        self,
        request: TaskCreateRequest,
    ) -> TaskCreateResult:
        """Create one task and read back its canonical provider state."""
        run_result = self._runner.run(
            _build_create_arguments(request),
            operation="create",
        )

        if not run_result.success:
            return TaskCreateResult(
                success=False,
                task=None,
                issues=run_result.issues,
            )

        command = run_result.command

        if command is None:
            return _create_failure(
                code="taskwarrior_create_failed",
                message=("Taskwarrior creation succeeded without a command result."),
            )

        task_uuid = command.stdout.strip()

        if not _is_canonical_uuid(task_uuid):
            return _create_failure(
                code="taskwarrior_create_uuid_invalid",
                message=("Taskwarrior did not return one canonical task UUID."),
            )

        return self._read_created_task(task_uuid)

    def modify_task(
        self,
        request: TaskModifyRequest,
    ) -> TaskMutationResult:
        """Modify one exact task and read back canonical provider state."""
        run_result = self._runner.run(
            _build_modify_arguments(request),
            operation="modify",
        )

        if not run_result.success:
            return TaskMutationResult(
                success=False,
                task=None,
                issues=run_result.issues,
            )

        if run_result.command is None:
            return _mutation_failure(
                code="taskwarrior_modify_failed",
                message=(
                    "Taskwarrior modification succeeded without a command result."
                ),
                operation="modify",
                task_uuid=request.task_uuid,
            )

        return self._read_mutated_task(
            request.task_uuid,
            operation="modify",
        )

    def complete_task(
        self,
        task_uuid: str,
    ) -> TaskMutationResult:
        """Complete one exact task and read back canonical provider state."""
        if not _is_canonical_uuid(task_uuid):
            return _mutation_failure(
                code="taskwarrior_task_uuid_invalid",
                message="The task UUID is not canonical.",
                operation="complete",
                task_uuid=None,
            )

        run_result = self._runner.run(
            (task_uuid, "done"),
            operation="complete",
        )

        if not run_result.success:
            return TaskMutationResult(
                success=False,
                task=None,
                issues=run_result.issues,
            )

        if run_result.command is None:
            return _mutation_failure(
                code="taskwarrior_complete_failed",
                message=("Taskwarrior completion succeeded without a command result."),
                operation="complete",
                task_uuid=task_uuid,
            )

        result = self._read_mutated_task(
            task_uuid,
            operation="complete",
        )

        if not result.success or result.task is None:
            return result

        if result.task.status is not TaskStatus.COMPLETED:
            return _mutation_failure(
                code="taskwarrior_complete_readback_status_invalid",
                message=("Taskwarrior read-back did not return a completed task."),
                operation="complete",
                task_uuid=task_uuid,
            )

        return result

    def delete_task(
        self,
        task_uuid: str,
    ) -> TaskMutationResult:
        """Delete one exact task and read back canonical provider state."""
        if not _is_canonical_uuid(task_uuid):
            return _mutation_failure(
                code="taskwarrior_task_uuid_invalid",
                message="The task UUID is not canonical.",
                operation="delete",
                task_uuid=None,
            )

        run_result = self._runner.run(
            (task_uuid, "delete"),
            operation="delete",
        )

        if not run_result.success:
            return TaskMutationResult(
                success=False,
                task=None,
                issues=run_result.issues,
            )

        if run_result.command is None:
            return _mutation_failure(
                code="taskwarrior_delete_failed",
                message=("Taskwarrior deletion succeeded without a command result."),
                operation="delete",
                task_uuid=task_uuid,
            )

        result = self._read_mutated_task(
            task_uuid,
            operation="delete",
        )

        if not result.success or result.task is None:
            return result

        if result.task.status is not TaskStatus.DELETED:
            return _mutation_failure(
                code="taskwarrior_delete_readback_status_invalid",
                message=("Taskwarrior read-back did not return a deleted task."),
                operation="delete",
                task_uuid=task_uuid,
            )

        return result

    def _read_created_task(
        self,
        task_uuid: str,
    ) -> TaskCreateResult:
        """Read back one newly created task."""
        read_result = self._runner.run(
            (task_uuid, "export"),
            operation="create_readback",
        )

        if not read_result.success:
            return TaskCreateResult(
                success=False,
                task=None,
                issues=read_result.issues,
            )

        read_command = read_result.command

        if read_command is None:
            return _create_failure(
                code="taskwarrior_create_readback_failed",
                message=("Taskwarrior read-back succeeded without a command result."),
                task_uuid=task_uuid,
            )

        parsed = parse_taskwarrior_export(read_command.stdout)

        if not parsed.success:
            return TaskCreateResult(
                success=False,
                task=None,
                issues=parsed.issues,
            )

        if len(parsed.tasks) != 1:
            return _create_failure(
                code="taskwarrior_create_readback_invalid",
                message=("Taskwarrior read-back did not return exactly one task."),
                task_uuid=task_uuid,
            )

        task = parsed.tasks[0]

        if task.uuid != task_uuid:
            return _create_failure(
                code="taskwarrior_create_readback_mismatch",
                message=("Taskwarrior read-back returned a different task UUID."),
                task_uuid=task_uuid,
            )

        return TaskCreateResult(
            success=True,
            task=task,
            issues=(),
        )

    def _read_mutated_task(
        self,
        task_uuid: str,
        *,
        operation: str,
    ) -> TaskMutationResult:
        """Read back one exact mutated task."""
        read_result = self._runner.run(
            (task_uuid, "export"),
            operation=f"{operation}_readback",
        )

        if not read_result.success:
            return TaskMutationResult(
                success=False,
                task=None,
                issues=read_result.issues,
            )

        read_command = read_result.command

        if read_command is None:
            return _mutation_failure(
                code="taskwarrior_mutation_readback_failed",
                message=("Taskwarrior read-back succeeded without a command result."),
                operation=operation,
                task_uuid=task_uuid,
            )

        parsed = parse_taskwarrior_export(read_command.stdout)

        if not parsed.success:
            return TaskMutationResult(
                success=False,
                task=None,
                issues=parsed.issues,
            )

        if len(parsed.tasks) != 1:
            return _mutation_failure(
                code="taskwarrior_mutation_readback_invalid",
                message=("Taskwarrior read-back did not return exactly one task."),
                operation=operation,
                task_uuid=task_uuid,
            )

        task = parsed.tasks[0]

        if task.uuid != task_uuid:
            return _mutation_failure(
                code="taskwarrior_mutation_readback_mismatch",
                message=("Taskwarrior read-back returned a different task UUID."),
                operation=operation,
                task_uuid=task_uuid,
            )

        return TaskMutationResult(
            success=True,
            task=task,
            issues=(),
        )


def _build_list_arguments(
    query: TaskListQuery,
) -> tuple[str, ...]:
    """Build deterministic exact Taskwarrior export arguments."""
    arguments: list[str] = []

    if query.uuid is not None:
        arguments.append(query.uuid)

    if query.status is not None:
        arguments.append(f"status:{query.status.value}")

    if query.project is not None:
        arguments.append(f"project:{query.project}")

    if query.tag is not None:
        arguments.append(f"+{query.tag}")

    arguments.append("export")
    return tuple(arguments)


def _build_create_arguments(
    request: TaskCreateRequest,
) -> tuple[str, ...]:
    """Build deterministic Taskwarrior creation arguments."""
    arguments = [
        "rc.verbose:new-uuid",
        "add",
        request.description,
    ]

    if request.project is not None:
        arguments.append(f"project:{request.project}")

    if request.due is not None:
        arguments.append(f"due:{_format_taskwarrior_timestamp(request.due)}")

    if request.priority is not None:
        arguments.append(f"priority:{request.priority}")

    arguments.extend(f"+{tag}" for tag in request.tags)
    return tuple(arguments)


def _build_modify_arguments(
    request: TaskModifyRequest,
) -> tuple[str, ...]:
    """Build deterministic exact Taskwarrior modification arguments."""
    arguments = [
        request.task_uuid,
        "modify",
    ]

    if request.description is not None:
        arguments.append(f"description:{request.description}")

    if request.project is not None:
        arguments.append(f"project:{request.project}")

    if request.due is not None:
        arguments.append(f"due:{_format_taskwarrior_timestamp(request.due)}")
    elif request.clear_due:
        arguments.append("due:")

    if request.priority is not None:
        arguments.append(f"priority:{request.priority}")
    elif request.clear_priority:
        arguments.append("priority:")

    arguments.extend(f"+{tag}" for tag in request.add_tags)
    arguments.extend(f"-{tag}" for tag in request.remove_tags)
    return tuple(arguments)


def _format_taskwarrior_timestamp(value: datetime) -> str:
    """Serialise one validated aware datetime in Taskwarrior UTC form."""
    return value.astimezone(UTC).strftime(_TASKWARRIOR_TIMESTAMP_FORMAT)


def _is_canonical_uuid(value: str) -> bool:
    """Return whether a value is one canonical lower-case UUID."""
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _create_failure(
    *,
    code: str,
    message: str,
    task_uuid: str | None = None,
) -> TaskCreateResult:
    """Construct one deterministic failed task creation."""
    return TaskCreateResult(
        success=False,
        task=None,
        issues=(
            TaskProviderIssue(
                code=code,
                message=message,
                provider=_PROVIDER,
                operation="create",
                task_uuid=task_uuid,
            ),
        ),
    )


def _mutation_failure(
    *,
    code: str,
    message: str,
    operation: str,
    task_uuid: str | None,
) -> TaskMutationResult:
    """Construct one deterministic failed task mutation."""
    return TaskMutationResult(
        success=False,
        task=None,
        issues=(
            TaskProviderIssue(
                code=code,
                message=message,
                provider=_PROVIDER,
                operation=operation,
                task_uuid=task_uuid,
            ),
        ),
    )


def _list_failure(
    *,
    code: str,
    message: str,
) -> TaskListResult:
    """Construct one deterministic failed listing."""
    return TaskListResult(
        success=False,
        tasks=(),
        issues=(
            TaskProviderIssue(
                code=code,
                message=message,
                provider=_PROVIDER,
                operation="list",
            ),
        ),
    )
