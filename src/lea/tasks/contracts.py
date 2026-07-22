"""Immutable provider-neutral task contracts."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from lea.tasks.tags import normalise_task_tag, validate_canonical_task_tag


class TaskStatus(StrEnum):
    """Supported provider-neutral task statuses."""

    PENDING = "pending"
    COMPLETED = "completed"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class TaskProviderIssue:
    """One structured task-provider problem."""

    code: str
    message: str
    provider: str | None = None
    operation: str | None = None
    task_uuid: str | None = None
    field: str | None = None
    return_code: int | None = None

    def __post_init__(self) -> None:
        """Validate task-provider issue fields."""
        if not self.code.strip():
            raise ValueError("Task provider issue code must be non-empty.")

        if not self.message.strip():
            raise ValueError("Task provider issue message must be non-empty.")

        for field_name, value in (
            ("provider", self.provider),
            ("operation", self.operation),
            ("field", self.field),
        ):
            if value is not None and not value.strip():
                raise ValueError(f"{field_name} must be non-empty when provided.")

        if self.task_uuid is not None:
            _validate_uuid(
                self.task_uuid,
                field_name="task_uuid",
            )


@dataclass(frozen=True, slots=True)
class TaskRecord:
    """Immutable provider-neutral task projection."""

    uuid: str
    description: str
    status: TaskStatus
    entry: datetime
    modified: datetime | None = None
    due: datetime | None = None
    project: str | None = None
    tags: tuple[str, ...] = ()
    priority: str | None = None

    def __post_init__(self) -> None:
        """Validate and normalise one task projection."""
        _validate_uuid(self.uuid, field_name="uuid")

        if not self.description.strip():
            raise ValueError("description must be non-empty.")

        _validate_aware_datetime(self.entry, field_name="entry")

        for field_name, value in (
            ("modified", self.modified),
            ("due", self.due),
        ):
            if value is not None:
                _validate_aware_datetime(value, field_name=field_name)

        if self.project is not None and not self.project.strip():
            raise ValueError("project must be non-empty when provided.")

        if self.priority is not None and not self.priority.strip():
            raise ValueError("priority must be non-empty when provided.")

        canonical_tags = tuple(sorted(set(self.tags)))

        for tag in canonical_tags:
            validate_canonical_task_tag(tag)

        object.__setattr__(self, "tags", canonical_tags)


@dataclass(frozen=True, slots=True)
class TaskCreateRequest:
    """Immutable request to create one task."""

    description: str
    project: str | None = None
    due: datetime | None = None
    priority: str | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate and normalise one task-creation request."""
        if not self.description.strip():
            raise ValueError("description must be non-empty.")

        canonical_tags = _normalise_task_tags(self.tags)

        _validate_optional_task_fields(
            project=self.project,
            due=self.due,
            priority=self.priority,
            tags=canonical_tags,
        )

        object.__setattr__(self, "tags", canonical_tags)


@dataclass(frozen=True, slots=True)
class TaskListQuery:
    """Immutable supported task-list query."""

    uuid: str | None = None
    status: TaskStatus | None = TaskStatus.PENDING
    project: str | None = None
    tag: str | None = None

    def __post_init__(self) -> None:
        """Validate exact supported listing filters."""
        if self.uuid is not None:
            _validate_uuid(self.uuid, field_name="uuid")

        if self.project is not None and not self.project.strip():
            raise ValueError("project must be non-empty when provided.")

        if self.tag is not None:
            object.__setattr__(self, "tag", normalise_task_tag(self.tag))


@dataclass(frozen=True, slots=True)
class TaskModifyRequest:
    """Immutable request to modify one exact task."""

    task_uuid: str
    description: str | None = None
    project: str | None = None
    due: datetime | None = None
    clear_due: bool = False
    priority: str | None = None
    clear_priority: bool = False
    add_tags: tuple[str, ...] = ()
    remove_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate and normalise one task modification."""
        _validate_uuid(self.task_uuid, field_name="task_uuid")

        if self.description is not None and not self.description.strip():
            raise ValueError("description must be non-empty when provided.")

        if self.project is not None and not self.project.strip():
            raise ValueError("project must be non-empty when provided.")

        if self.due is not None:
            _validate_aware_datetime(self.due, field_name="due")

        if self.due is not None and self.clear_due:
            raise ValueError("due and clear_due must not be supplied together.")

        if self.priority is not None and not self.priority.strip():
            raise ValueError("priority must be non-empty when provided.")

        if self.priority is not None and self.clear_priority:
            raise ValueError(
                "priority and clear_priority must not be supplied together."
            )

        add_tags = _normalise_task_tags(self.add_tags)
        remove_tags = _normalise_task_tags(self.remove_tags)

        if set(add_tags) & set(remove_tags):
            raise ValueError("The same tag must not be added and removed.")

        object.__setattr__(self, "add_tags", add_tags)
        object.__setattr__(self, "remove_tags", remove_tags)

        if not any(
            (
                self.description is not None,
                self.project is not None,
                self.due is not None,
                self.clear_due,
                self.priority is not None,
                self.clear_priority,
                bool(add_tags),
                bool(remove_tags),
            )
        ):
            raise ValueError("A task modification must contain at least one change.")


@dataclass(frozen=True, slots=True)
class TaskProviderInspectionResult:
    """Immutable result of inspecting one task provider."""

    available: bool
    provider: str
    version: str | None
    issues: tuple[TaskProviderIssue, ...]

    def __post_init__(self) -> None:
        """Validate inspection-result consistency."""
        if not self.provider.strip():
            raise ValueError("provider must be non-empty.")

        if self.available:
            if self.version is None or not self.version.strip():
                raise ValueError("An available provider must contain a version.")
            if self.issues:
                raise ValueError("An available provider must not contain issues.")
            return

        if self.version is not None:
            raise ValueError("An unavailable provider must not contain a version.")

        if not self.issues:
            raise ValueError("An unavailable provider must contain at least one issue.")


@dataclass(frozen=True, slots=True)
class TaskCreateResult:
    """Immutable result of creating one task."""

    success: bool
    task: TaskRecord | None
    issues: tuple[TaskProviderIssue, ...]

    def __post_init__(self) -> None:
        """Validate creation-result consistency."""
        _validate_task_result(
            success=self.success,
            task=self.task,
            issues=self.issues,
            operation="create",
        )


@dataclass(frozen=True, slots=True)
class TaskListResult:
    """Immutable result of listing tasks."""

    success: bool
    tasks: tuple[TaskRecord, ...]
    issues: tuple[TaskProviderIssue, ...]

    def __post_init__(self) -> None:
        """Validate listing-result consistency."""
        if self.success and self.issues:
            raise ValueError("A successful task list must not contain issues.")

        if not self.success:
            if self.tasks:
                raise ValueError("A failed task list must not contain tasks.")
            if not self.issues:
                raise ValueError("A failed task list must contain at least one issue.")


@dataclass(frozen=True, slots=True)
class TaskMutationResult:
    """Immutable result of modifying one task."""

    success: bool
    task: TaskRecord | None
    issues: tuple[TaskProviderIssue, ...]

    def __post_init__(self) -> None:
        """Validate mutation-result consistency."""
        _validate_task_result(
            success=self.success,
            task=self.task,
            issues=self.issues,
            operation="mutation",
        )


def _validate_task_result(
    *,
    success: bool,
    task: TaskRecord | None,
    issues: tuple[TaskProviderIssue, ...],
    operation: str,
) -> None:
    """Validate one result containing an optional task."""
    if success:
        if task is None:
            raise ValueError(f"A successful task {operation} must contain a task.")
        if issues:
            raise ValueError(f"A successful task {operation} must not contain issues.")
        return

    if task is not None:
        raise ValueError(f"A failed task {operation} must not contain a task.")

    if not issues:
        raise ValueError(f"A failed task {operation} must contain at least one issue.")


def _validate_optional_task_fields(
    *,
    project: str | None,
    due: datetime | None,
    priority: str | None,
    tags: tuple[str, ...],
) -> None:
    """Validate common optional task fields."""
    if project is not None and not project.strip():
        raise ValueError("project must be non-empty when provided.")

    if due is not None:
        _validate_aware_datetime(due, field_name="due")

    if priority is not None and not priority.strip():
        raise ValueError("priority must be non-empty when provided.")

    for tag in tags:
        validate_canonical_task_tag(tag)


def _normalise_task_tags(tags: tuple[str, ...]) -> tuple[str, ...]:
    """Normalise, deduplicate and sort task tags."""
    return tuple(sorted({normalise_task_tag(tag) for tag in tags}))


def _validate_uuid(
    value: str,
    *,
    field_name: str,
) -> None:
    """Validate one canonical lower-case UUID."""
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a valid UUID.") from error

    if str(parsed) != value:
        raise ValueError(f"{field_name} must use canonical lower-case UUID format.")


def _validate_aware_datetime(
    value: datetime,
    *,
    field_name: str,
) -> None:
    """Validate one timezone-aware datetime."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")
