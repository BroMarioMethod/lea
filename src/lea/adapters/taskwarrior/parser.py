"""Strict Taskwarrior JSON export parsing."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast

from lea.tasks import (
    TaskListResult,
    TaskProviderIssue,
    TaskRecord,
    TaskStatus,
)

_PROVIDER = "taskwarrior"
_TASKWARRIOR_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"

_STATUS_MAP = {
    "pending": TaskStatus.PENDING,
    "completed": TaskStatus.COMPLETED,
    "deleted": TaskStatus.DELETED,
}


def parse_taskwarrior_export(
    payload: str,
) -> TaskListResult:
    """Parse one untrusted Taskwarrior JSON export payload."""
    if not isinstance(payload, str):
        raise TypeError("payload must be a string.")

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return _failure(
            code="taskwarrior_export_invalid_json",
            message="Taskwarrior export did not contain valid JSON.",
        )

    if not isinstance(parsed, list):
        return _failure(
            code="taskwarrior_export_invalid_shape",
            message="Taskwarrior export must contain a JSON array.",
        )

    tasks: list[TaskRecord] = []

    for index, raw_task in enumerate(parsed):
        if not isinstance(raw_task, Mapping):
            return TaskListResult(
                success=False,
                tasks=(),
                issues=(
                    _task_issue(
                        message=("Each Taskwarrior export item must be an object."),
                        index=index,
                    ),
                ),
            )

        result = _parse_task(
            cast(Mapping[str, object], raw_task),
            index=index,
        )

        if isinstance(result, TaskProviderIssue):
            return TaskListResult(
                success=False,
                tasks=(),
                issues=(result,),
            )

        tasks.append(result)

    tasks.sort(
        key=lambda task: (
            task.entry,
            task.uuid,
        )
    )

    return TaskListResult(
        success=True,
        tasks=tuple(tasks),
        issues=(),
    )


def _parse_task(
    data: Mapping[str, object],
    *,
    index: int,
) -> TaskRecord | TaskProviderIssue:
    """Parse one exported task object."""
    required_fields = (
        "uuid",
        "description",
        "status",
        "entry",
    )

    for field in required_fields:
        if field not in data:
            return _task_issue(
                message=f"Taskwarrior task field '{field}' is missing.",
                index=index,
                field=field,
            )

    uuid = data["uuid"]
    description = data["description"]
    status = data["status"]
    entry = data["entry"]

    if not isinstance(uuid, str):
        return _task_issue(
            message="Taskwarrior task UUID must be a string.",
            index=index,
            field="uuid",
        )

    if not isinstance(description, str):
        return _task_issue(
            message="Taskwarrior task description must be a string.",
            index=index,
            field="description",
        )

    if not isinstance(status, str) or status not in _STATUS_MAP:
        return _task_issue(
            message="Taskwarrior task status is unsupported.",
            index=index,
            field="status",
            task_uuid=uuid,
        )

    entry_result = _parse_timestamp(
        entry,
        field="entry",
        index=index,
        task_uuid=uuid,
    )
    if isinstance(entry_result, TaskProviderIssue):
        return entry_result

    modified_result = _parse_optional_timestamp(
        data.get("modified"),
        field="modified",
        index=index,
        task_uuid=uuid,
    )
    if isinstance(modified_result, TaskProviderIssue):
        return modified_result

    due_result = _parse_optional_timestamp(
        data.get("due"),
        field="due",
        index=index,
        task_uuid=uuid,
    )
    if isinstance(due_result, TaskProviderIssue):
        return due_result

    project_result = _parse_optional_string(
        data.get("project"),
        field="project",
        index=index,
        task_uuid=uuid,
    )
    if isinstance(project_result, TaskProviderIssue):
        return project_result

    priority_result = _parse_optional_string(
        data.get("priority"),
        field="priority",
        index=index,
        task_uuid=uuid,
    )
    if isinstance(priority_result, TaskProviderIssue):
        return priority_result

    tags_result = _parse_tags(
        data.get("tags"),
        index=index,
        task_uuid=uuid,
    )
    if isinstance(tags_result, TaskProviderIssue):
        return tags_result

    try:
        return TaskRecord(
            uuid=uuid,
            description=description,
            status=_STATUS_MAP[status],
            entry=entry_result,
            modified=modified_result,
            due=due_result,
            project=project_result,
            tags=tags_result,
            priority=priority_result,
        )
    except ValueError as error:
        return _task_issue(
            message=str(error),
            index=index,
            field="uuid",
        )


def _parse_timestamp(
    value: object,
    *,
    field: str,
    index: int,
    task_uuid: str | None,
) -> datetime | TaskProviderIssue:
    """Parse one required Taskwarrior UTC timestamp."""
    if not isinstance(value, str):
        return _task_issue(
            message=f"Taskwarrior task field '{field}' must be a string.",
            index=index,
            field=field,
            task_uuid=task_uuid,
        )

    try:
        return datetime.strptime(
            value,
            _TASKWARRIOR_TIMESTAMP_FORMAT,
        ).replace(tzinfo=UTC)
    except ValueError:
        return _task_issue(
            message=f"Taskwarrior task field '{field}' is not a valid timestamp.",
            index=index,
            field=field,
            task_uuid=task_uuid,
        )


def _parse_optional_timestamp(
    value: object,
    *,
    field: str,
    index: int,
    task_uuid: str | None,
) -> datetime | None | TaskProviderIssue:
    """Parse one optional Taskwarrior UTC timestamp."""
    if value is None:
        return None

    return _parse_timestamp(
        value,
        field=field,
        index=index,
        task_uuid=task_uuid,
    )


def _parse_optional_string(
    value: object,
    *,
    field: str,
    index: int,
    task_uuid: str | None,
) -> str | None | TaskProviderIssue:
    """Parse one optional non-blank string."""
    if value is None:
        return None

    if not isinstance(value, str) or not value.strip():
        return _task_issue(
            message=f"Taskwarrior task field '{field}' must be a non-empty string.",
            index=index,
            field=field,
            task_uuid=task_uuid,
        )

    return value


def _parse_tags(
    value: object,
    *,
    index: int,
    task_uuid: str | None,
) -> tuple[str, ...] | TaskProviderIssue:
    """Parse optional Taskwarrior tags."""
    if value is None:
        return ()

    if not isinstance(value, list):
        return _task_issue(
            message="Taskwarrior task field 'tags' must be an array.",
            index=index,
            field="tags",
            task_uuid=task_uuid,
        )

    tags: list[str] = []

    for tag in value:
        if not isinstance(tag, str) or not tag.strip():
            return _task_issue(
                message="Taskwarrior task tags must contain non-empty strings.",
                index=index,
                field="tags",
                task_uuid=task_uuid,
            )

        tags.append(tag)

    return tuple(tags)


def _task_issue(
    *,
    message: str,
    index: int,
    field: str | None = None,
    task_uuid: str | None = None,
) -> TaskProviderIssue:
    """Construct one deterministic invalid-task issue."""
    return TaskProviderIssue(
        code="taskwarrior_task_invalid",
        message=message,
        provider=_PROVIDER,
        operation="export",
        task_uuid=task_uuid,
        field=(f"items[{index}].{field}" if field is not None else f"items[{index}]"),
    )


def _failure(
    *,
    code: str,
    message: str,
) -> TaskListResult:
    """Construct one deterministic export-parse failure."""
    return TaskListResult(
        success=False,
        tasks=(),
        issues=(
            TaskProviderIssue(
                code=code,
                message=message,
                provider=_PROVIDER,
                operation="export",
            ),
        ),
    )
