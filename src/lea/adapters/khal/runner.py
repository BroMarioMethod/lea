"""Safe deterministic khal subprocess execution."""

import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from time import monotonic

from lea.adapters.khal.contracts import (
    KhalCommandResult,
    KhalConfig,
    KhalRunResult,
)
from lea.calendars import CalendarProviderIssue

_PROVIDER = "khal"


class KhalRunner:
    """Invoke one explicitly configured khal executable."""

    def __init__(
        self,
        config: KhalConfig,
        *,
        base_environment: Mapping[str, str] | None = None,
    ) -> None:
        """Configure deterministic khal process execution."""
        if not isinstance(config, KhalConfig):
            raise TypeError("config must be a KhalConfig value.")

        self._config = config
        self._base_environment = (
            dict(base_environment) if base_environment is not None else {}
        )

    @property
    def config(self) -> KhalConfig:
        """Return the immutable runner configuration."""
        return self._config

    def run(
        self,
        arguments: Sequence[str],
        *,
        operation: str,
        configured: bool = True,
    ) -> KhalRunResult:
        """Run khal without shell construction."""
        if not isinstance(operation, str):
            raise TypeError("operation must be a string.")

        if not operation.strip():
            raise ValueError("operation must be non-empty.")

        if any(not isinstance(argument, str) or not argument for argument in arguments):
            raise ValueError("arguments must contain only non-empty strings.")

        issue = self._inspect_executable(operation=operation)

        if issue is not None:
            return _failure(issue)

        working_issue = self._inspect_directory(
            self._config.working_directory,
            field="working_directory",
            missing_code="khal_working_directory_unavailable",
            invalid_code="khal_working_directory_unavailable",
            operation=operation,
        )

        if working_issue is not None:
            return _failure(working_issue)

        if configured:
            configured_issue = self._inspect_configured_runtime(
                operation=operation,
            )

            if configured_issue is not None:
                return _failure(configured_issue)

        command = self._build_command(
            arguments,
            configured=configured,
        )
        environment = self._build_environment(
            configured=configured,
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
        except FileNotFoundError:
            return _failure(
                _issue(
                    code="khal_executable_missing",
                    message="The configured khal executable was not found.",
                    operation=operation,
                    field="executable",
                )
            )
        except PermissionError:
            return _failure(
                _issue(
                    code="khal_executable_not_executable",
                    message=("The configured khal executable could not be executed."),
                    operation=operation,
                    field="executable",
                )
            )
        except subprocess.TimeoutExpired:
            return _failure(
                _issue(
                    code="khal_process_timeout",
                    message="The khal process exceeded its timeout.",
                    operation=operation,
                )
            )
        except OSError:
            return _failure(
                _issue(
                    code="khal_process_failed",
                    message="The khal process could not be started.",
                    operation=operation,
                )
            )

        duration = monotonic() - started

        try:
            stdout = completed.stdout.decode("utf-8", errors="strict")
            stderr = completed.stderr.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return _failure(
                _issue(
                    code="khal_output_invalid_utf8",
                    message=("khal returned output that was not valid UTF-8."),
                    operation=operation,
                )
            )

        command_result = KhalCommandResult(
            arguments=tuple(command),
            return_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
        )

        if completed.returncode != 0:
            return KhalRunResult(
                success=False,
                command=command_result,
                issues=(
                    _issue(
                        code="khal_process_failed",
                        message=("khal returned a non-zero process status."),
                        operation=operation,
                        return_code=completed.returncode,
                    ),
                ),
            )

        return KhalRunResult(
            success=True,
            command=command_result,
            issues=(),
        )

    def _build_command(
        self,
        arguments: Sequence[str],
        *,
        configured: bool,
    ) -> list[str]:
        """Build one exact khal argument list."""
        if not configured:
            return [
                str(self._config.executable),
                *arguments,
            ]

        return [
            str(self._config.executable),
            "--no-color",
            "-c",
            str(self._config.configuration),
            *arguments,
        ]

    def _build_environment(
        self,
        *,
        configured: bool,
    ) -> dict[str, str]:
        """Build one explicit bounded subprocess environment."""
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
                "PATH": (f"{self._config.executable.parent}:/usr/bin:/bin"),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
                "PYTHONUTF8": "1",
                "TZ": "UTC",
            }
        )

        if configured:
            environment.update(
                {
                    "HOME": str(self._config.state_directory),
                    "XDG_CACHE_HOME": str(self._config.state_directory),
                    "XDG_CONFIG_HOME": str(self._config.configuration.parent),
                    "XDG_DATA_HOME": str(self._config.state_directory),
                }
            )
        else:
            environment.pop("XDG_CACHE_HOME", None)
            environment.pop("XDG_CONFIG_HOME", None)
            environment.pop("XDG_DATA_HOME", None)

        return environment

    def _inspect_executable(
        self,
        *,
        operation: str,
    ) -> CalendarProviderIssue | None:
        """Require one exact non-symbolic regular executable."""
        path = self._config.executable

        try:
            if path.is_symlink():
                return _issue(
                    code="khal_executable_invalid",
                    message=(
                        "The configured khal executable must not be a symbolic link."
                    ),
                    operation=operation,
                    field="executable",
                )

            if not path.exists():
                return _issue(
                    code="khal_executable_missing",
                    message=("The configured khal executable was not found."),
                    operation=operation,
                    field="executable",
                )

            if not path.is_file():
                return _issue(
                    code="khal_executable_not_executable",
                    message=(
                        "The configured khal executable path is not a regular file."
                    ),
                    operation=operation,
                    field="executable",
                )

            if not os.access(path, os.X_OK):
                return _issue(
                    code="khal_executable_not_executable",
                    message=("The configured khal executable is not executable."),
                    operation=operation,
                    field="executable",
                )
        except OSError:
            return _issue(
                code="khal_executable_invalid",
                message=("The configured khal executable could not be inspected."),
                operation=operation,
                field="executable",
            )

        return None

    def _inspect_configured_runtime(
        self,
        *,
        operation: str,
    ) -> CalendarProviderIssue | None:
        """Require exact configuration and state paths."""
        configuration = self._config.configuration

        try:
            if configuration.is_symlink():
                return _issue(
                    code="khal_configuration_invalid",
                    message=(
                        "The configured khal configuration must not be a symbolic link."
                    ),
                    operation=operation,
                    field="configuration",
                )

            if not configuration.exists():
                return _issue(
                    code="khal_configuration_missing",
                    message=("The configured khal configuration file does not exist."),
                    operation=operation,
                    field="configuration",
                )

            if not configuration.is_file():
                return _issue(
                    code="khal_configuration_invalid",
                    message=(
                        "The configured khal configuration path is not a regular file."
                    ),
                    operation=operation,
                    field="configuration",
                )
        except OSError:
            return _issue(
                code="khal_configuration_invalid",
                message=("The configured khal configuration could not be inspected."),
                operation=operation,
                field="configuration",
            )

        return self._inspect_directory(
            self._config.state_directory,
            field="state_directory",
            missing_code="khal_state_directory_missing",
            invalid_code="khal_state_directory_invalid",
            operation=operation,
        )

    def _inspect_directory(
        self,
        path: Path,
        *,
        field: str,
        missing_code: str,
        invalid_code: str,
        operation: str,
    ) -> CalendarProviderIssue | None:
        """Require one exact non-symbolic directory."""
        try:
            if path.is_symlink():
                return _issue(
                    code=invalid_code,
                    message=(
                        f"The configured khal {field.replace('_', ' ')} "
                        "must not be a symbolic link."
                    ),
                    operation=operation,
                    field=field,
                )

            if not path.exists():
                return _issue(
                    code=missing_code,
                    message=(
                        f"The configured khal {field.replace('_', ' ')} does not exist."
                    ),
                    operation=operation,
                    field=field,
                )

            if not path.is_dir():
                return _issue(
                    code=invalid_code,
                    message=(
                        f"The configured khal {field.replace('_', ' ')} "
                        "is not a directory."
                    ),
                    operation=operation,
                    field=field,
                )
        except OSError:
            return _issue(
                code=invalid_code,
                message=(
                    f"The configured khal {field.replace('_', ' ')} "
                    "could not be inspected."
                ),
                operation=operation,
                field=field,
            )

        return None


def _failure(
    issue: CalendarProviderIssue,
) -> KhalRunResult:
    """Construct one deterministic failed invocation."""
    return KhalRunResult(
        success=False,
        command=None,
        issues=(issue,),
    )


def _issue(
    *,
    code: str,
    message: str,
    operation: str,
    field: str | None = None,
    return_code: int | None = None,
) -> CalendarProviderIssue:
    """Construct one structured khal provider issue."""
    return CalendarProviderIssue(
        code=code,
        message=message,
        provider=_PROVIDER,
        operation=operation,
        field=field,
        return_code=return_code,
    )
