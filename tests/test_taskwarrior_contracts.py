"""Tests for immutable Taskwarrior adapter contracts."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from lea.adapters.taskwarrior import (
    TaskwarriorCommandResult,
    TaskwarriorConfig,
)


def valid_config(tmp_path: Path) -> TaskwarriorConfig:
    """Return one valid explicit Taskwarrior configuration."""
    return TaskwarriorConfig(
        executable=tmp_path / "bin" / "task",
        taskrc=tmp_path / "config" / "taskrc",
        data_dir=tmp_path / "data",
        home_dir=tmp_path / "home",
        working_dir=tmp_path,
    )


def test_taskwarrior_config_is_immutable(
    tmp_path: Path,
) -> None:
    """Adapter configuration should be frozen."""
    config = valid_config(tmp_path)

    with pytest.raises(FrozenInstanceError):
        config.timeout_seconds = 2.0  # type: ignore[misc]


def test_taskwarrior_config_requires_absolute_paths() -> None:
    """All configured paths must be explicit and absolute."""
    with pytest.raises(
        ValueError,
        match="executable must be an absolute path",
    ):
        TaskwarriorConfig(
            executable=Path("task"),
            taskrc=Path("/tmp/taskrc"),
            data_dir=Path("/tmp/data"),
            home_dir=Path("/tmp/home"),
        )


def test_taskwarrior_config_requires_positive_timeout(
    tmp_path: Path,
) -> None:
    """Every invocation must have a finite positive timeout."""
    with pytest.raises(
        ValueError,
        match="greater than zero",
    ):
        TaskwarriorConfig(
            executable=tmp_path / "task",
            taskrc=tmp_path / "taskrc",
            data_dir=tmp_path / "data",
            home_dir=tmp_path / "home",
            timeout_seconds=0,
        )


def test_command_result_is_immutable() -> None:
    """Captured command results should be frozen."""
    result = TaskwarriorCommandResult(
        arguments=("/opt/task", "--version"),
        return_code=0,
        stdout="3.4.2\n",
        stderr="",
        duration_seconds=0.01,
    )

    with pytest.raises(FrozenInstanceError):
        result.return_code = 1  # type: ignore[misc]


def test_command_result_rejects_empty_arguments() -> None:
    """A captured command must identify its executable."""
    with pytest.raises(
        ValueError,
        match="at least the executable",
    ):
        TaskwarriorCommandResult(
            arguments=(),
            return_code=0,
            stdout="",
            stderr="",
            duration_seconds=0,
        )


def test_command_result_rejects_negative_duration() -> None:
    """Measured command duration must not be negative."""
    with pytest.raises(
        ValueError,
        match="must not be negative",
    ):
        TaskwarriorCommandResult(
            arguments=("/opt/task",),
            return_code=0,
            stdout="",
            stderr="",
            duration_seconds=-0.1,
        )
