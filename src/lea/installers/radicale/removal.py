"""Explicit fail-closed removal for the separately managed Radicale service."""

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lea.installers.radicale.service import RadicaleServiceConfig, ServiceCommandResult


@dataclass(frozen=True, slots=True)
class RadicaleRemovalRequest:
    """Exact resources and approvals for one Radicale removal."""

    service: RadicaleServiceConfig
    installation_record: Path
    purge: bool = False
    confirmed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.service, RadicaleServiceConfig):
            raise TypeError("service must be a RadicaleServiceConfig value.")
        if not self.installation_record.is_absolute():
            raise ValueError("installation_record must be absolute.")
        if self.purge and not self.confirmed:
            raise ValueError("Purging Radicale state requires explicit confirmation.")
        protected = {Path("/"), Path("/etc"), Path("/var"), Path("/var/lib")}
        targets = {
            self.service.unit_file,
            self.service.layout.configuration_file,
            self.service.layout.users_file,
            self.service.layout.storage_directory,
            self.installation_record,
        }
        if targets & protected:
            raise ValueError("Radicale removal contains an unsafe broad path.")


@dataclass(frozen=True, slots=True)
class RadicaleRemovalIssue:
    """One redaction-safe removal failure."""

    code: str
    message: str
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class RadicaleRemovalResult:
    """Result of stopping the service and optionally purging exact state."""

    success: bool
    service_removed: bool
    state_purged: bool
    commands: tuple[tuple[str, ...], ...]
    issues: tuple[RadicaleRemovalIssue, ...]


RemovalCommandExecutor = Callable[[tuple[str, ...]], ServiceCommandResult]


def remove_radicale(
    request: RadicaleRemovalRequest,
    *,
    execute: RemovalCommandExecutor | None = None,
) -> RadicaleRemovalResult:
    """Stop and disable Radicale before exact, explicitly approved deletion."""
    issue = _inspect_targets(request)
    if issue is not None:
        return RadicaleRemovalResult(False, False, False, (), (issue,))
    runner = execute or _execute
    commands = (
        (str(request.service.systemctl), "stop", request.service.service_name),
        (str(request.service.systemctl), "disable", request.service.service_name),
    )
    completed: list[tuple[str, ...]] = []
    for command in commands:
        try:
            result = runner(command)
        except (OSError, subprocess.SubprocessError):
            return _command_failure(completed, command)
        completed.append(command)
        if result.return_code != 0:
            return _command_failure(completed, command)
    try:
        request.service.unit_file.unlink(missing_ok=True)
    except OSError:
        return _path_failure(completed, request.service.unit_file)
    reload_command = (str(request.service.systemctl), "daemon-reload")
    try:
        reload_result = runner(reload_command)
    except (OSError, subprocess.SubprocessError):
        return _command_failure(completed, reload_command)
    completed.append(reload_command)
    if reload_result.return_code != 0:
        return _command_failure(completed, reload_command)

    if not request.purge:
        return RadicaleRemovalResult(True, True, False, tuple(completed), ())
    for path in (
        request.service.layout.configuration_file,
        request.service.layout.users_file,
        request.installation_record,
    ):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            return _path_failure(completed, path, service_removed=True)
    try:
        shutil.rmtree(request.service.layout.storage_directory)
    except FileNotFoundError:
        pass
    except OSError:
        return _path_failure(
            completed,
            request.service.layout.storage_directory,
            service_removed=True,
        )
    return RadicaleRemovalResult(True, True, True, tuple(completed), ())


def _inspect_targets(request: RadicaleRemovalRequest) -> RadicaleRemovalIssue | None:
    paths = [request.service.unit_file]
    if request.purge:
        paths.extend(
            (
                request.service.layout.configuration_file,
                request.service.layout.users_file,
                request.installation_record,
            )
        )
        storage = request.service.layout.storage_directory
        if storage.is_symlink() or (storage.exists() and not storage.is_dir()):
            return RadicaleRemovalIssue(
                "radicale_removal_path_unsafe",
                "A managed Radicale removal path is unsafe.",
                storage,
            )
    for path in paths:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            return RadicaleRemovalIssue(
                "radicale_removal_path_unsafe",
                "A managed Radicale removal path is unsafe.",
                path,
            )
    return None


def _execute(command: tuple[str, ...]) -> ServiceCommandResult:
    completed = subprocess.run(
        command,
        shell=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=30,
    )
    return ServiceCommandResult(completed.returncode)


def _command_failure(
    completed: list[tuple[str, ...]], command: tuple[str, ...]
) -> RadicaleRemovalResult:
    return RadicaleRemovalResult(
        False,
        False,
        False,
        tuple(completed),
        (
            RadicaleRemovalIssue(
                "radicale_removal_command_failed",
                f"The Radicale service command {command[1]} failed.",
            ),
        ),
    )


def _path_failure(
    completed: list[tuple[str, ...]],
    path: Path,
    *,
    service_removed: bool = False,
) -> RadicaleRemovalResult:
    return RadicaleRemovalResult(
        False,
        service_removed,
        False,
        tuple(completed),
        (
            RadicaleRemovalIssue(
                "radicale_removal_path_failed",
                "A managed Radicale path could not be removed.",
                path,
            ),
        ),
    )
