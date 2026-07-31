"""Public khal CLI adapter interfaces."""

from lea.adapters.khal.contracts import (
    KhalCommandResult,
    KhalConfig,
    KhalRunResult,
)
from lea.adapters.khal.inspection import inspect_khal
from lea.adapters.khal.runner import KhalRunner

__all__ = [
    "KhalCommandResult",
    "KhalConfig",
    "KhalRunResult",
    "KhalRunner",
    "inspect_khal",
]
