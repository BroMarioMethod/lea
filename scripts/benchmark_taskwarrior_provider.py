#!/usr/bin/env python3
"""Benchmark the real isolated Taskwarrior provider."""

import argparse
import statistics
import tempfile
from collections.abc import Callable
from pathlib import Path
from time import perf_counter

from lea.adapters.taskwarrior import (
    TaskwarriorCliProvider,
    TaskwarriorConfig,
)
from lea.tasks import (
    TaskCreateRequest,
    TaskCreateResult,
    TaskListQuery,
    TaskListResult,
    TaskModifyRequest,
    TaskMutationResult,
)


def _measure[T](
    action: Callable[[], T],
) -> tuple[T, float]:
    """Run one action and return its duration in milliseconds."""
    started = perf_counter()
    result = action()
    duration_ms = (perf_counter() - started) * 1_000
    return result, duration_ms


def _provider(
    *,
    executable: Path,
    root: Path,
) -> TaskwarriorCliProvider:
    """Create one isolated benchmark provider."""
    taskrc = root / "config" / "taskrc"
    data_dir = root / "data"
    home_dir = root / "home"
    working_dir = root / "working"

    taskrc.parent.mkdir(parents=True)
    data_dir.mkdir()
    home_dir.mkdir()
    working_dir.mkdir()

    taskrc.write_text(
        ("confirmation=no\nhooks=0\nverbose=nothing\n"),
        encoding="utf-8",
    )

    return TaskwarriorCliProvider(
        TaskwarriorConfig(
            executable=executable,
            taskrc=taskrc,
            data_dir=data_dir,
            home_dir=home_dir,
            working_dir=working_dir,
            timeout_seconds=10.0,
        )
    )


def _summary(
    name: str,
    values: list[float],
) -> None:
    """Print one compact latency summary."""
    print(
        f"{name:12} "
        f"n={len(values):2d} "
        f"min={min(values):8.2f} ms "
        f"median={statistics.median(values):8.2f} ms "
        f"mean={statistics.fmean(values):8.2f} ms "
        f"max={max(values):8.2f} ms"
    )


def main() -> int:
    """Run the provider benchmark."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--executable",
        type=Path,
        default=Path("/opt/lea-tools/taskwarrior/3.4.2/bin/task"),
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
    )
    arguments = parser.parse_args()

    if arguments.iterations <= 0:
        parser.error("--iterations must be greater than zero")

    executable = arguments.executable.resolve()

    if not executable.is_file():
        parser.error(f"Taskwarrior executable not found: {executable}")

    measurements: dict[str, list[float]] = {
        "inspect": [],
        "create": [],
        "list": [],
        "modify": [],
        "complete": [],
        "delete": [],
    }

    with tempfile.TemporaryDirectory(
        prefix="lea-taskwarrior-benchmark-"
    ) as temporary_directory:
        provider = _provider(
            executable=executable,
            root=Path(temporary_directory),
        )

        for index in range(arguments.iterations):
            inspected, duration = _measure(provider.inspect)
            assert inspected.available
            measurements["inspect"].append(duration)

            create_request = TaskCreateRequest(
                description=f"LEA benchmark lifecycle {index}",
                project="lea.benchmark",
                tags=("benchmark", "lifecycle"),
            )

            def create_action(
                request: TaskCreateRequest = create_request,
            ) -> TaskCreateResult:
                return provider.create_task(request)

            created, duration = _measure(create_action)
            assert created.success and created.task is not None
            measurements["create"].append(duration)
            task_uuid = created.task.uuid

            list_query = TaskListQuery(uuid=task_uuid)

            def list_action(
                query: TaskListQuery = list_query,
            ) -> TaskListResult:
                return provider.list_tasks(query)

            listed, duration = _measure(list_action)
            assert listed.success
            measurements["list"].append(duration)

            modify_request = TaskModifyRequest(
                task_uuid=task_uuid,
                description=(f"LEA benchmark lifecycle updated {index}"),
                add_tags=("updated",),
            )

            def modify_action(
                request: TaskModifyRequest = modify_request,
            ) -> TaskMutationResult:
                return provider.modify_task(request)

            modified, duration = _measure(modify_action)
            assert modified.success
            measurements["modify"].append(duration)

            def complete_action(
                uuid: str = task_uuid,
            ) -> TaskMutationResult:
                return provider.complete_task(uuid)

            completed, duration = _measure(complete_action)
            assert completed.success
            measurements["complete"].append(duration)

            deletion_created = provider.create_task(
                TaskCreateRequest(
                    description=f"LEA benchmark deletion {index}",
                    tags=("benchmark", "delete"),
                )
            )
            assert deletion_created.success
            assert deletion_created.task is not None
            deletion_uuid = deletion_created.task.uuid

            def delete_action(
                uuid: str = deletion_uuid,
            ) -> TaskMutationResult:
                return provider.delete_task(uuid)

            deleted, duration = _measure(delete_action)
            assert deleted.success
            measurements["delete"].append(duration)

    print(f"Executable: {executable}")
    print(f"Iterations: {arguments.iterations}")

    for operation, values in measurements.items():
        _summary(operation, values)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
