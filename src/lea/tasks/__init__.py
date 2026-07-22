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
]
