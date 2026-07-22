"""Public provider-neutral task interfaces."""

from lea.tasks.contracts import (
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
from lea.tasks.provider import TaskProvider
from lea.tasks.tags import normalise_task_tag

__all__ = [
    "TaskCreateRequest",
    "TaskCreateResult",
    "TaskListQuery",
    "TaskListResult",
    "TaskModifyRequest",
    "TaskMutationResult",
    "TaskProvider",
    "TaskProviderInspectionResult",
    "TaskProviderIssue",
    "TaskRecord",
    "TaskStatus",
    "normalise_task_tag",
]
