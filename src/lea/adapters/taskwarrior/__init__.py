"""Public Taskwarrior CLI adapter interfaces."""

from lea.adapters.taskwarrior.contracts import (
    TaskwarriorCommandResult,
    TaskwarriorConfig,
    TaskwarriorRunResult,
)
from lea.adapters.taskwarrior.inspection import inspect_taskwarrior
from lea.adapters.taskwarrior.runner import TaskwarriorRunner

__all__ = [
    "TaskwarriorCommandResult",
    "TaskwarriorConfig",
    "TaskwarriorRunResult",
    "TaskwarriorRunner",
    "inspect_taskwarrior",
]
