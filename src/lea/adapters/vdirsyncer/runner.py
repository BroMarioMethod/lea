"""Hardened exact-path vdirsyncer subprocess execution."""

import os
import subprocess
from collections.abc import Mapping, Sequence
from time import monotonic

from lea.adapters.vdirsyncer.contracts import (
    VdirsyncerCommandResult,
    VdirsyncerConfig,
    VdirsyncerRunResult,
)
from lea.calendars import CalendarProviderIssue

_PROVIDER = "vdirsyncer"


class VdirsyncerRunner:
    """Invoke only the configured vdirsyncer executable and configuration."""

    def __init__(
        self,
        config: VdirsyncerConfig,
        *,
        base_environment: Mapping[str, str] | None = None,
    ) -> None:
        if not isinstance(config, VdirsyncerConfig):
            raise TypeError("config must be a VdirsyncerConfig value.")
        self._config = config
        self._base_environment = dict(base_environment or {})

    @property
    def config(self) -> VdirsyncerConfig:
        return self._config

    def run(
        self,
        arguments: Sequence[str],
        *,
        operation: str,
        configured: bool = True,
    ) -> VdirsyncerRunResult:
        """Run one bounded non-interactive command without a shell."""
        if not isinstance(operation, str) or not operation.strip():
            raise ValueError("operation must be non-empty.")
        if any(not isinstance(value, str) or not value for value in arguments):
            raise ValueError("arguments must contain only non-empty strings.")

        issue = self._inspect_runtime(operation=operation, configured=configured)
        if issue is not None:
            return _failure(issue)
        command = [str(self._config.executable)]
        if configured:
            command.extend(("--config", str(self._config.configuration)))
        command.extend(arguments)
        environment = {
            key: value
            for key, value in self._base_environment.items()
            if key in {"LANG", "LC_ALL", "PATH", "TZ"}
        }
        environment.update(
            {
                "HOME": str(self._config.working_directory),
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "NO_COLOR": "1",
                "PATH": f"{self._config.executable.parent}:/usr/bin:/bin",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
            }
        )
        started = monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=self._config.working_directory,
                env=environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=self._config.timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return _failure(
                _issue(
                    "vdirsyncer_process_timeout",
                    "The vdirsyncer process exceeded its timeout.",
                    operation,
                )
            )
        except OSError:
            return _failure(
                _issue(
                    "vdirsyncer_process_failed",
                    "The vdirsyncer process could not be started.",
                    operation,
                )
            )

        try:
            stdout = completed.stdout.decode("utf-8", errors="strict")
            stderr = completed.stderr.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return _failure(
                _issue(
                    "vdirsyncer_output_invalid_utf8",
                    "vdirsyncer output was not valid UTF-8.",
                    operation,
                )
            )
        evidence = VdirsyncerCommandResult(
            arguments=tuple(command),
            return_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=monotonic() - started,
        )
        if completed.returncode != 0:
            if operation == "calendar_discover" and (
                "Should vdirsyncer attempt to create it?" in stdout
                or "Should vdirsyncer attempt to create it?" in stderr
            ):
                return VdirsyncerRunResult(
                    success=False,
                    command=evidence,
                    issues=(
                        _issue(
                            "vdirsyncer_collection_creation_required",
                            (
                                "Calendar discovery requires a separate explicit "
                                "collection-bootstrap approval."
                            ),
                            operation,
                            completed.returncode,
                        ),
                    ),
                )
            return VdirsyncerRunResult(
                success=False,
                command=evidence,
                issues=(
                    _issue(
                        "vdirsyncer_process_failed",
                        "vdirsyncer returned a non-zero process status.",
                        operation,
                        completed.returncode,
                    ),
                ),
            )
        return VdirsyncerRunResult(True, evidence, ())

    def _inspect_runtime(
        self, *, operation: str, configured: bool
    ) -> CalendarProviderIssue | None:
        try:
            if (
                self._config.executable.is_symlink()
                or not self._config.executable.is_file()
            ):
                return _issue(
                    "vdirsyncer_executable_unavailable",
                    "The configured vdirsyncer executable is unavailable.",
                    operation,
                )
            if not os.access(self._config.executable, os.X_OK):
                return _issue(
                    "vdirsyncer_executable_unavailable",
                    "The configured vdirsyncer executable is not executable.",
                    operation,
                )
            if (
                self._config.working_directory.is_symlink()
                or not self._config.working_directory.is_dir()
            ):
                return _issue(
                    "vdirsyncer_working_directory_unavailable",
                    "The configured working directory is unavailable.",
                    operation,
                )
            if configured and (
                self._config.configuration.is_symlink()
                or not self._config.configuration.is_file()
            ):
                return _issue(
                    "vdirsyncer_configuration_unavailable",
                    "The configured vdirsyncer configuration is unavailable.",
                    operation,
                )
        except OSError:
            return _issue(
                "vdirsyncer_runtime_unavailable",
                "The vdirsyncer runtime could not be inspected.",
                operation,
            )
        return None


def _issue(
    code: str, message: str, operation: str, return_code: int | None = None
) -> CalendarProviderIssue:
    return CalendarProviderIssue(
        code=code,
        message=message,
        provider=_PROVIDER,
        operation=operation,
        return_code=return_code,
    )


def _failure(issue: CalendarProviderIssue) -> VdirsyncerRunResult:
    return VdirsyncerRunResult(False, None, (issue,))
