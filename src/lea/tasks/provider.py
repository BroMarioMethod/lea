"""Provider-neutral task execution interface."""

from typing import Protocol, runtime_checkable

from lea.tasks.contracts import (
    TaskCreateRequest,
    TaskCreateResult,
    TaskListQuery,
    TaskListResult,
    TaskModifyRequest,
    TaskMutationResult,
    TaskProviderInspectionResult,
)


@runtime_checkable
class TaskProvider(Protocol):
    """Interface implemented by deterministic task providers."""

    def inspect(self) -> TaskProviderInspectionResult:
        """Inspect provider availability and compatibility."""
        ...

    def create_task(
        self,
        request: TaskCreateRequest,
    ) -> TaskCreateResult:
        """Create one task."""
        ...

    def list_tasks(
        self,
        query: TaskListQuery,
    ) -> TaskListResult:
        """List tasks matching supported exact filters."""
        ...

    def modify_task(
        self,
        request: TaskModifyRequest,
    ) -> TaskMutationResult:
        """Modify one exact task."""
        ...

    def complete_task(
        self,
        task_uuid: str,
    ) -> TaskMutationResult:
        """Complete one exact task."""
        ...

    def delete_task(
        self,
        task_uuid: str,
    ) -> TaskMutationResult:
        """Delete one exact task."""
        ...
