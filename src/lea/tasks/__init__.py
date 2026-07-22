"""Public provider-neutral task interfaces."""

from lea.tasks.action_handlers import (
    TaskActionHandlerError,
    complete_task_action_handler,
    create_task_action_handler,
    delete_task_action_handler,
    modify_task_action_handler,
    task_action_handler_registry,
)
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
    "TaskActionHandlerError",
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
    "complete_task_action_handler",
    "create_task_action_handler",
    "delete_task_action_handler",
    "modify_task_action_handler",
    "normalise_task_tag",
    "task_action_handler_registry",
]
