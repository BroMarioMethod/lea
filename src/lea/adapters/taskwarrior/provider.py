"""Read-only Taskwarrior CLI task provider."""

from lea.adapters.taskwarrior.contracts import TaskwarriorConfig
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


class TaskwarriorCliProvider:
    """Provider-neutral access through the Taskwarrior CLI."""

    def __init__(
        self,
        config: TaskwarriorConfig,
        *,
        runner: TaskwarriorRunner | None = None,
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
        """Reject creation until the mutation slice is implemented."""
        return TaskCreateResult(
            success=False,
            task=None,
            issues=(_read_only_issue(operation="create"),),
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
                _read_only_issue(
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
                _read_only_issue(
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
                _read_only_issue(
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


def _read_only_issue(
    *,
    operation: str,
    task_uuid: str | None = None,
) -> TaskProviderIssue:
    """Construct one deterministic read-only provider issue."""
    return TaskProviderIssue(
        code="taskwarrior_operation_not_implemented",
        message=("This Taskwarrior provider operation is not implemented yet."),
        provider=_PROVIDER,
        operation=operation,
        task_uuid=task_uuid,
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
