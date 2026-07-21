"""Safe deterministic Taskwarrior subprocess execution."""

import os
import subprocess
from collections.abc import Mapping, Sequence
from time import monotonic

from lea.adapters.taskwarrior.contracts import (
    TaskwarriorCommandResult,
    TaskwarriorConfig,
    TaskwarriorRunResult,
)
from lea.tasks import TaskProviderIssue

_PROVIDER = "taskwarrior"


class TaskwarriorRunner:
    """Invoke one explicitly configured Taskwarrior executable."""

    def __init__(
        self,
        config: TaskwarriorConfig,
        *,
        base_environment: Mapping[str, str] | None = None,
    ) -> None:
        """Configure deterministic Taskwarrior process execution."""
        self._config = config
        self._base_environment = (
            dict(base_environment) if base_environment is not None else dict(os.environ)
        )

    @property
    def config(self) -> TaskwarriorConfig:
        """Return the immutable runner configuration."""
        return self._config

    def run(
        self,
        arguments: Sequence[str],
        *,
        operation: str,
    ) -> TaskwarriorRunResult:
        """Run Taskwarrior without shell construction."""
        if not operation.strip():
            raise ValueError("operation must be non-empty.")

        if any(not argument for argument in arguments):
            raise ValueError("arguments must not contain empty values.")

        command = self._build_command(arguments)
        environment = self._build_environment()
        started = monotonic()

        try:
            completed = subprocess.run(
                command,
                cwd=self._config.working_dir,
                env=environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=self._config.timeout_seconds,
                check=False,
                shell=False,
            )
        except FileNotFoundError:
            return _failure(
                code="taskwarrior_executable_missing",
                message="The configured Taskwarrior executable was not found.",
                operation=operation,
            )
        except PermissionError:
            return _failure(
                code="taskwarrior_executable_not_executable",
                message=(
                    "The configured Taskwarrior executable could not be executed."
                ),
                operation=operation,
            )
        except subprocess.TimeoutExpired:
            return _failure(
                code="taskwarrior_process_timeout",
                message="The Taskwarrior process exceeded its timeout.",
                operation=operation,
            )
        except OSError:
            return _failure(
                code="taskwarrior_process_failed",
                message="The Taskwarrior process could not be started.",
                operation=operation,
            )

        duration = monotonic() - started

        try:
            stdout = completed.stdout.decode("utf-8", errors="strict")
            stderr = completed.stderr.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return _failure(
                code="taskwarrior_output_invalid_utf8",
                message="Taskwarrior returned output that was not valid UTF-8.",
                operation=operation,
            )

        command_result = TaskwarriorCommandResult(
            arguments=tuple(command),
            return_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
        )

        if completed.returncode != 0:
            return TaskwarriorRunResult(
                success=False,
                command=None,
                issues=(
                    TaskProviderIssue(
                        code="taskwarrior_process_failed",
                        message=("Taskwarrior returned a non-zero process status."),
                        provider=_PROVIDER,
                        operation=operation,
                        return_code=completed.returncode,
                    ),
                ),
            )

        return TaskwarriorRunResult(
            success=True,
            command=command_result,
            issues=(),
        )

    def _build_command(
        self,
        arguments: Sequence[str],
    ) -> list[str]:
        """Build one exact Taskwarrior argument list."""
        return [
            str(self._config.executable),
            f"rc:{self._config.taskrc}",
            f"rc.data.location:{self._config.data_dir}",
            "rc.confirmation:no",
            "rc.verbose:nothing",
            *arguments,
        ]

    def _build_environment(self) -> dict[str, str]:
        """Build the explicit subprocess environment."""
        environment = dict(self._base_environment)
        environment["HOME"] = str(self._config.home_dir)
        environment["TASKRC"] = str(self._config.taskrc)
        return environment


def _failure(
    *,
    code: str,
    message: str,
    operation: str,
) -> TaskwarriorRunResult:
    """Construct one deterministic failed invocation."""
    return TaskwarriorRunResult(
        success=False,
        command=None,
        issues=(
            TaskProviderIssue(
                code=code,
                message=message,
                provider=_PROVIDER,
                operation=operation,
            ),
        ),
    )
