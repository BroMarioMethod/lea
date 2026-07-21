"""Isolated lifecycle validation for staged Taskwarrior binaries."""

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lea.adapters.taskwarrior import (
    TaskwarriorCliProvider,
    TaskwarriorConfig,
    inspect_taskwarrior,
)
from lea.installers.taskwarrior.contracts import (
    TaskwarriorInstallerIssue,
    TaskwarriorInstallFailureCode,
)
from lea.installers.taskwarrior.staging import TaskwarriorStagedBinary
from lea.tasks import (
    TaskCreateRequest,
    TaskListQuery,
    TaskModifyRequest,
    TaskStatus,
)

_PROVIDER_FACTORY = Callable[
    [TaskwarriorConfig],
    TaskwarriorCliProvider,
]


@dataclass(frozen=True, slots=True)
class TaskwarriorSmokeTestResult:
    """Result of validating one staged Taskwarrior executable."""

    passed: bool
    version: str | None
    issues: tuple[TaskwarriorInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate smoke-test result consistency."""
        if self.passed:
            if self.version is None or not self.version.strip():
                raise ValueError("A passed smoke test must contain a version.")

            if self.issues:
                raise ValueError("A passed smoke test must not contain issues.")

            return

        if self.version is not None:
            raise ValueError("A failed smoke test must not contain a version.")

        if not self.issues:
            raise ValueError("A failed smoke test must contain at least one issue.")


def validate_staged_taskwarrior_binary(
    staged: TaskwarriorStagedBinary,
    *,
    timeout_seconds: float = 10.0,
    provider_factory: _PROVIDER_FACTORY = TaskwarriorCliProvider,
) -> TaskwarriorSmokeTestResult:
    """Validate one staged executable in disposable isolated storage."""
    if not isinstance(staged, TaskwarriorStagedBinary):
        raise TypeError("staged must be a TaskwarriorStagedBinary value.")

    return validate_taskwarrior_executable(
        staged.executable,
        temporary_parent=staged.staging_root,
        timeout_seconds=timeout_seconds,
        provider_factory=provider_factory,
    )


def validate_taskwarrior_executable(
    executable: Path,
    *,
    temporary_parent: Path,
    timeout_seconds: float = 10.0,
    provider_factory: _PROVIDER_FACTORY = TaskwarriorCliProvider,
) -> TaskwarriorSmokeTestResult:
    """Validate one exact executable in disposable isolated storage."""
    if not isinstance(executable, Path):
        raise TypeError("executable must be a pathlib.Path value.")

    if not isinstance(temporary_parent, Path):
        raise TypeError("temporary_parent must be a pathlib.Path value.")

    if not executable.is_absolute():
        raise ValueError("executable must be absolute.")

    if not temporary_parent.is_absolute():
        raise ValueError("temporary_parent must be absolute.")

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero.")

    temporary_parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(
        tempfile.mkdtemp(
            prefix=".taskwarrior-smoke-",
            dir=temporary_parent,
        )
    )

    try:
        config = _create_isolated_config(
            executable=executable,
            temporary_root=temporary_root,
            timeout_seconds=timeout_seconds,
        )

        inspection = inspect_taskwarrior(config)

        if not inspection.available or inspection.version is None:
            return _failure(
                "The staged Taskwarrior executable failed version inspection."
            )

        provider = provider_factory(config)

        create_result = provider.create_task(
            TaskCreateRequest(
                description="LEA Taskwarrior installer smoke test",
                project="lea.install",
                tags=("lea-smoke-test",),
            )
        )

        if not create_result.success or create_result.task is None:
            return _failure("The staged Taskwarrior executable failed task creation.")

        first_uuid = create_result.task.uuid

        list_result = provider.list_tasks(TaskListQuery(uuid=first_uuid))

        if (
            not list_result.success
            or len(list_result.tasks) != 1
            or list_result.tasks[0].uuid != first_uuid
        ):
            return _failure(
                "The staged Taskwarrior executable failed exact task listing."
            )

        modify_result = provider.modify_task(
            TaskModifyRequest(
                task_uuid=first_uuid,
                description=("LEA Taskwarrior installer smoke test modified"),
                add_tags=("modified",),
            )
        )

        if (
            not modify_result.success
            or modify_result.task is None
            or modify_result.task.uuid != first_uuid
            or modify_result.task.description
            != "LEA Taskwarrior installer smoke test modified"
        ):
            return _failure(
                "The staged Taskwarrior executable failed task modification."
            )

        complete_result = provider.complete_task(first_uuid)

        if (
            not complete_result.success
            or complete_result.task is None
            or complete_result.task.uuid != first_uuid
            or complete_result.task.status is not TaskStatus.COMPLETED
        ):
            return _failure("The staged Taskwarrior executable failed task completion.")

        second_create_result = provider.create_task(
            TaskCreateRequest(
                description=("LEA Taskwarrior installer deletion smoke test"),
                project="lea.install",
                tags=("lea-smoke-test",),
            )
        )

        if not second_create_result.success or second_create_result.task is None:
            return _failure(
                "The staged Taskwarrior executable failed secondary task creation."
            )

        second_uuid = second_create_result.task.uuid
        delete_result = provider.delete_task(second_uuid)

        if (
            not delete_result.success
            or delete_result.task is None
            or delete_result.task.uuid != second_uuid
            or delete_result.task.status is not TaskStatus.DELETED
        ):
            return _failure("The staged Taskwarrior executable failed task deletion.")

        return TaskwarriorSmokeTestResult(
            passed=True,
            version=inspection.version,
            issues=(),
        )
    except OSError as error:
        return _failure(
            "The isolated Taskwarrior smoke-test environment could not "
            f"be prepared: {error.strerror or type(error).__name__}."
        )
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def _create_isolated_config(
    *,
    executable: Path,
    temporary_root: Path,
    timeout_seconds: float,
) -> TaskwarriorConfig:
    """Create disposable Taskwarrior configuration and storage."""
    home_dir = temporary_root / "home"
    data_dir = temporary_root / "data"
    configuration_dir = temporary_root / "config"
    taskrc = configuration_dir / "taskrc"

    home_dir.mkdir(mode=0o700)
    data_dir.mkdir(mode=0o700)
    configuration_dir.mkdir(mode=0o700)

    taskrc.write_text(
        "confirmation=no\nhooks=0\nverbose=nothing\n",
        encoding="utf-8",
    )
    taskrc.chmod(0o600)

    return TaskwarriorConfig(
        executable=executable,
        taskrc=taskrc,
        data_dir=data_dir,
        home_dir=home_dir,
        timeout_seconds=timeout_seconds,
        working_dir=temporary_root,
    )


def _failure(
    message: str,
) -> TaskwarriorSmokeTestResult:
    """Create one structured smoke-test failure."""
    return TaskwarriorSmokeTestResult(
        passed=False,
        version=None,
        issues=(
            TaskwarriorInstallerIssue(
                code=(TaskwarriorInstallFailureCode.SMOKE_TEST_FAILED),
                message=message,
            ),
        ),
    )
