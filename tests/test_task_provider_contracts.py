"""Tests for provider-neutral task contracts."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from lea.tasks import (
    TaskCreateRequest,
    TaskCreateResult,
    TaskListQuery,
    TaskListResult,
    TaskModifyRequest,
    TaskMutationResult,
    TaskProvider,
    TaskProviderInspectionResult,
    TaskProviderIssue,
    TaskRecord,
    TaskStatus,
)

TASK_UUID = "9f92a9a9-b845-42df-a76d-5c21061039cb"


def task_record() -> TaskRecord:
    """Return one valid task record."""
    return TaskRecord(
        uuid=TASK_UUID,
        description="Test task",
        status=TaskStatus.PENDING,
        entry=datetime(2026, 7, 21, 17, 26, 8, tzinfo=UTC),
        tags=("zeta", "alpha", "alpha"),
    )


def issue() -> TaskProviderIssue:
    """Return one valid provider issue."""
    return TaskProviderIssue(
        code="task_provider_unavailable",
        message="The provider is unavailable.",
        provider="taskwarrior",
    )


def test_task_record_is_immutable_and_normalises_tags() -> None:
    """Task records should be frozen and deterministically tagged."""
    record = task_record()

    assert record.tags == ("alpha", "zeta")

    with pytest.raises(FrozenInstanceError):
        record.description = "Changed"  # type: ignore[misc]


def test_task_record_rejects_naive_timestamp() -> None:
    """Task timestamps must be timezone-aware."""
    with pytest.raises(
        ValueError,
        match="entry must be timezone-aware",
    ):
        TaskRecord(
            uuid=TASK_UUID,
            description="Test",
            status=TaskStatus.PENDING,
            entry=datetime(2026, 7, 21, 12, 0),
        )


def test_create_request_normalises_tags() -> None:
    """Creation requests should normalise repeated tags."""
    request = TaskCreateRequest(
        description="Test",
        tags=("beta", "alpha", "beta"),
    )

    assert request.tags == ("alpha", "beta")


def test_default_list_query_is_pending() -> None:
    """Default listing should target pending tasks."""
    assert TaskListQuery().status is TaskStatus.PENDING


def test_modify_request_requires_a_change() -> None:
    """Empty modifications should fail before provider invocation."""
    with pytest.raises(
        ValueError,
        match="at least one change",
    ):
        TaskModifyRequest(task_uuid=TASK_UUID)


def test_modify_request_rejects_conflicting_tag_changes() -> None:
    """One tag must not be added and removed together."""
    with pytest.raises(
        ValueError,
        match="same tag",
    ):
        TaskModifyRequest(
            task_uuid=TASK_UUID,
            add_tags=("urgent",),
            remove_tags=("urgent",),
        )


def test_successful_results_require_values() -> None:
    """Successful task results must contain their expected values."""
    with pytest.raises(ValueError):
        TaskCreateResult(success=True, task=None, issues=())

    with pytest.raises(ValueError):
        TaskListResult(
            success=True,
            tasks=(),
            issues=(issue(),),
        )

    with pytest.raises(ValueError):
        TaskMutationResult(success=True, task=None, issues=())


def test_failed_results_require_issues() -> None:
    """Failed task results must expose structured issues."""
    with pytest.raises(ValueError):
        TaskCreateResult(success=False, task=None, issues=())

    with pytest.raises(ValueError):
        TaskListResult(success=False, tasks=(), issues=())


def test_inspection_result_consistency() -> None:
    """Inspection results should not mix success and failure data."""
    available = TaskProviderInspectionResult(
        available=True,
        provider="taskwarrior",
        version="3.4.2",
        issues=(),
    )
    unavailable = TaskProviderInspectionResult(
        available=False,
        provider="taskwarrior",
        version=None,
        issues=(issue(),),
    )

    assert available.version == "3.4.2"
    assert unavailable.issues == (issue(),)


def test_task_provider_protocol_is_runtime_checkable() -> None:
    """Complete compatible objects should satisfy the protocol."""

    class Provider:
        def inspect(self) -> TaskProviderInspectionResult:
            return TaskProviderInspectionResult(
                available=True,
                provider="test",
                version="1.0",
                issues=(),
            )

        def create_task(
            self,
            request: TaskCreateRequest,
        ) -> TaskCreateResult:
            return TaskCreateResult(
                success=True,
                task=task_record(),
                issues=(),
            )

        def list_tasks(
            self,
            query: TaskListQuery,
        ) -> TaskListResult:
            return TaskListResult(
                success=True,
                tasks=(task_record(),),
                issues=(),
            )

        def modify_task(
            self,
            request: TaskModifyRequest,
        ) -> TaskMutationResult:
            return TaskMutationResult(
                success=True,
                task=task_record(),
                issues=(),
            )

        def complete_task(
            self,
            task_uuid: str,
        ) -> TaskMutationResult:
            return TaskMutationResult(
                success=True,
                task=task_record(),
                issues=(),
            )

        def delete_task(
            self,
            task_uuid: str,
        ) -> TaskMutationResult:
            return TaskMutationResult(
                success=True,
                task=task_record(),
                issues=(),
            )

    assert isinstance(Provider(), TaskProvider)


def test_requests_normalise_hyphenated_tags() -> None:
    """Input contracts should canonicalise safe hyphenated tags."""
    create = TaskCreateRequest(
        description="Test",
        tags=("local-cli", "local_cli"),
    )
    listing = TaskListQuery(tag="local-cli")
    modify = TaskModifyRequest(
        task_uuid=TASK_UUID,
        add_tags=("sales-followup",),
    )

    assert create.tags == ("local_cli",)
    assert listing.tag == "local_cli"
    assert modify.add_tags == ("sales_followup",)


def test_modify_detects_conflicts_after_tag_normalisation() -> None:
    """Equivalent raw tags must conflict after normalisation."""
    with pytest.raises(ValueError, match="same tag"):
        TaskModifyRequest(
            task_uuid=TASK_UUID,
            add_tags=("local-cli",),
            remove_tags=("local_cli",),
        )


def test_task_record_rejects_non_canonical_provider_tags() -> None:
    """Provider read-back must not be silently rewritten."""
    with pytest.raises(ValueError, match="canonical"):
        TaskRecord(
            uuid=TASK_UUID,
            description="Test",
            status=TaskStatus.PENDING,
            entry=datetime(2026, 7, 21, 17, 26, 8, tzinfo=UTC),
            tags=("local-cli",),
        )
