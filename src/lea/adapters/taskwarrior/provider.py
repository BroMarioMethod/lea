"""Taskwarrior CLI task provider."""

from collections.abc import Sequence
from datetime import UTC
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

    def modify_task(
        self,
        request: TaskModifyRequest,
    ) -> TaskMutationResult:
        """Reject modification until the mutation slice is implemented."""
        return TaskMutationResult(
            success=False,
            task=None,
            issues=(
                _not_implemented_issue(
                    operation="modify",
                    task_uuid=request.task_uuid,
                ),
            ),
        )

    def complete_task(
        self,
        task_uuid: str,
    ) -> TaskMutationResult:
        """Reject completion until the mutation slice is implemented."""
        return TaskMutationResult(
            success=False,
            task=None,
            issues=(
                _not_implemented_issue(
                    operation="complete",
                    task_uuid=task_uuid,
                ),
            ),
        )

    def delete_task(
        self,
        task_uuid: str,
    ) -> TaskMutationResult:
        """Reject deletion until the mutation slice is implemented."""
        return TaskMutationResult(
            success=False,
            task=None,
            issues=(
                _not_implemented_issue(
                    operation="delete",
                    task_uuid=task_uuid,
                ),
            ),
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
        due = request.due.astimezone(UTC).strftime(_TASKWARRIOR_TIMESTAMP_FORMAT)
        arguments.append(f"due:{due}")

    if request.priority is not None:
        arguments.append(f"priority:{request.priority}")

    arguments.extend(f"+{tag}" for tag in request.tags)
    return tuple(arguments)


def _is_canonical_uuid(value: str) -> bool:
    """Return whether a value is one canonical lower-case UUID."""
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _not_implemented_issue(
    *,
    operation: str,
    task_uuid: str | None = None,
) -> TaskProviderIssue:
    """Construct one deterministic unimplemented-operation issue."""
    return TaskProviderIssue(
        code="taskwarrior_operation_not_implemented",
        message=("This Taskwarrior provider operation is not implemented yet."),
        provider=_PROVIDER,
        operation=operation,
        task_uuid=task_uuid,
    )


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
