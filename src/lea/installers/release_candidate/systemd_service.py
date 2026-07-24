"""systemd service deployment for release-candidate installation."""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lea.installers.release_candidate.contracts import (
    InstallerIssue,
    InstallerIssueCode,
    InstallerStepId,
    ReleaseCandidateInstallRequest,
)

CommandExecutor = Callable[[tuple[str, ...]], "SystemCommandResult"]
OwnershipApplier = Callable[[Path, str, str], None]


@dataclass(frozen=True, slots=True)
class SystemCommandResult:
    """Redaction-safe result of one exact system command."""

    return_code: int
    standard_output: str = ""
    standard_error: str = ""

    def __post_init__(self) -> None:
        """Validate command-result fields."""
        if isinstance(self.return_code, bool) or not isinstance(
            self.return_code,
            int,
        ):
            raise TypeError("return_code must be an integer.")


@dataclass(frozen=True, slots=True)
class TelegramSystemdServicePlan:
    """Immutable deployment plan for the Telegram systemd unit."""

    source_file: Path
    destination_file: Path
    backup_directory: Path
    systemctl: Path
    service_name: str
    owner: str = "root"
    group: str = "root"
    mode: int = 0o644

    def __post_init__(self) -> None:
        """Validate service-deployment fields."""
        for field_name, path in (
            ("source_file", self.source_file),
            ("destination_file", self.destination_file),
            ("backup_directory", self.backup_directory),
            ("systemctl", self.systemctl),
        ):
            _validate_absolute_path(path, field_name=field_name)

        for field_name, value in (
            ("service_name", self.service_name),
            ("owner", self.owner),
            ("group", self.group),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty.")

        if "/" in self.service_name or not self.service_name.endswith(".service"):
            raise ValueError("service_name must be one systemd .service unit name.")

        if self.destination_file.name != self.service_name:
            raise ValueError("destination_file must match the declared service_name.")

        if self.mode < 0 or self.mode > 0o7777:
            raise ValueError("mode must be a valid Unix mode.")


@dataclass(frozen=True, slots=True)
class TelegramSystemdServiceResult:
    """Result of deploying and activating the Telegram systemd unit."""

    success: bool
    unit_changed: bool
    backup_created: Path | None
    enabled: bool
    active: bool
    commands: tuple[tuple[str, ...], ...]
    issues: tuple[InstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate service-result consistency."""
        if self.backup_created is not None:
            _validate_absolute_path(
                self.backup_created,
                field_name="backup_created",
            )

        if self.success:
            if not self.enabled or not self.active:
                raise ValueError(
                    "A successful service result must be enabled and active."
                )
            if self.issues:
                raise ValueError("A successful service result must not contain issues.")
            return

        if not self.issues:
            raise ValueError("A failed service result must contain at least one issue.")


def create_telegram_systemd_service_plan(
    request: ReleaseCandidateInstallRequest,
    *,
    systemd_directory: Path = Path("/etc/systemd/system"),
    systemctl: Path = Path("/usr/bin/systemctl"),
) -> TelegramSystemdServicePlan:
    """Create the deterministic Telegram systemd service plan."""
    if not isinstance(request, ReleaseCandidateInstallRequest):
        raise TypeError("request must be a ReleaseCandidateInstallRequest value.")

    if not request.enable_telegram:
        raise ValueError("Telegram systemd deployment requires enable_telegram=True.")

    service_name = "lea-telegram.service"

    return TelegramSystemdServicePlan(
        source_file=(request.installation_root / "deploy" / "systemd" / service_name),
        destination_file=systemd_directory / service_name,
        backup_directory=(request.state_root / "backups" / "systemd"),
        systemctl=systemctl,
        service_name=service_name,
    )


def deploy_telegram_systemd_service(
    plan: TelegramSystemdServicePlan,
    *,
    approve_replacement: bool,
    execute: CommandExecutor | None = None,
    apply_ownership: OwnershipApplier | None = None,
    fsync: bool = True,
) -> TelegramSystemdServiceResult:
    """Install, enable, start and verify the Telegram systemd service."""
    if not isinstance(plan, TelegramSystemdServicePlan):
        raise TypeError("plan must be a TelegramSystemdServicePlan value.")

    command_executor = execute or _execute_command
    ownership_applier = apply_ownership or _apply_posix_ownership

    commands: list[tuple[str, ...]] = []
    changed = False
    backup: Path | None = None

    try:
        source_contents = _read_source(plan.source_file)
        changed, backup = _install_unit(
            plan,
            contents=source_contents,
            approve_replacement=approve_replacement,
            fsync=fsync,
        )
        ownership_applier(
            plan.destination_file,
            plan.owner,
            plan.group,
        )

        if changed:
            failure = _run_required(
                (
                    str(plan.systemctl),
                    "daemon-reload",
                ),
                execute=command_executor,
                commands=commands,
                operation="daemon-reload",
            )
            if failure is not None:
                return _failed(
                    changed=changed,
                    backup=backup,
                    enabled=False,
                    active=False,
                    commands=commands,
                    issue=failure,
                )

        enabled_state, failure = _query_state(
            (
                str(plan.systemctl),
                "is-enabled",
                plan.service_name,
            ),
            execute=command_executor,
            commands=commands,
            operation="is-enabled",
        )
        if failure is not None:
            return _failed(
                changed=changed,
                backup=backup,
                enabled=False,
                active=False,
                commands=commands,
                issue=failure,
            )

        if not enabled_state:
            failure = _run_required(
                (
                    str(plan.systemctl),
                    "enable",
                    plan.service_name,
                ),
                execute=command_executor,
                commands=commands,
                operation="enable",
            )
            if failure is not None:
                return _failed(
                    changed=changed,
                    backup=backup,
                    enabled=False,
                    active=False,
                    commands=commands,
                    issue=failure,
                )

        active_state, failure = _query_state(
            (
                str(plan.systemctl),
                "is-active",
                plan.service_name,
            ),
            execute=command_executor,
            commands=commands,
            operation="is-active",
        )
        if failure is not None:
            return _failed(
                changed=changed,
                backup=backup,
                enabled=True,
                active=False,
                commands=commands,
                issue=failure,
            )

        if not active_state:
            failure = _run_required(
                (
                    str(plan.systemctl),
                    "start",
                    plan.service_name,
                ),
                execute=command_executor,
                commands=commands,
                operation="start",
            )
            if failure is not None:
                return _failed(
                    changed=changed,
                    backup=backup,
                    enabled=True,
                    active=False,
                    commands=commands,
                    issue=failure,
                )

        enabled_state, failure = _query_state(
            (
                str(plan.systemctl),
                "is-enabled",
                plan.service_name,
            ),
            execute=command_executor,
            commands=commands,
            operation="verify-is-enabled",
        )
        if failure is not None or not enabled_state:
            return _failed(
                changed=changed,
                backup=backup,
                enabled=False,
                active=False,
                commands=commands,
                issue=failure
                or _issue(
                    "The Telegram service was not enabled after activation.",
                    field="service_name",
                    path=plan.destination_file,
                ),
            )

        active_state, failure = _query_state(
            (
                str(plan.systemctl),
                "is-active",
                plan.service_name,
            ),
            execute=command_executor,
            commands=commands,
            operation="verify-is-active",
        )
        if failure is not None or not active_state:
            return _failed(
                changed=changed,
                backup=backup,
                enabled=True,
                active=False,
                commands=commands,
                issue=failure
                or _issue(
                    "The Telegram service was not active after activation.",
                    field="service_name",
                    path=plan.destination_file,
                ),
            )

    except (OSError, UnicodeError, ValueError) as error:
        return _failed(
            changed=changed,
            backup=backup,
            enabled=False,
            active=False,
            commands=commands,
            issue=_issue(
                "Telegram systemd deployment failed before activation: "
                f"{type(error).__name__}.",
                path=plan.destination_file,
            ),
        )

    return TelegramSystemdServiceResult(
        success=True,
        unit_changed=changed,
        backup_created=backup,
        enabled=True,
        active=True,
        commands=tuple(commands),
        issues=(),
    )


def _read_source(path: Path) -> str:
    """Read one trusted regular unit source."""
    if path.is_symlink() or not path.is_file():
        raise ValueError(
            "The Telegram service source must be a regular non-symlink file."
        )

    contents = path.read_text(encoding="utf-8")

    if not contents.strip():
        raise ValueError("The Telegram service source must not be empty.")

    return contents


def _install_unit(
    plan: TelegramSystemdServicePlan,
    *,
    contents: str,
    approve_replacement: bool,
    fsync: bool,
) -> tuple[bool, Path | None]:
    """Install one service unit atomically with optional backup."""
    destination = plan.destination_file
    destination.parent.mkdir(parents=True, exist_ok=True)
    plan.backup_directory.mkdir(parents=True, exist_ok=True)

    existing: str | None = None

    if destination.exists():
        if destination.is_symlink() or not destination.is_file():
            raise ValueError(
                "The Telegram service destination is not a safe regular file."
            )

        existing = destination.read_text(encoding="utf-8")

        if existing == contents:
            destination.chmod(plan.mode)
            return False, None

        if not approve_replacement:
            raise PermissionError(
                "Replacement approval is required for the systemd service."
            )

    backup = (
        _create_backup(destination, plan.backup_directory, fsync=fsync)
        if existing is not None
        else None
    )

    _atomic_write(
        destination,
        contents=contents,
        mode=plan.mode,
        fsync=fsync,
    )
    return True, backup


def _create_backup(
    source: Path,
    backup_directory: Path,
    *,
    fsync: bool,
) -> Path:
    """Create one numbered immutable backup copy."""
    for index in range(1, 10_000):
        candidate = backup_directory / (f"{source.name}.{index:04d}.bak")
        if candidate.exists():
            continue

        _atomic_write(
            candidate,
            contents=source.read_text(encoding="utf-8"),
            mode=0o600,
            fsync=fsync,
        )
        return candidate

    raise OSError("No available backup filename remained.")


def _atomic_write(
    destination: Path,
    *,
    contents: str,
    mode: int,
    fsync: bool,
) -> None:
    """Atomically replace one managed UTF-8 file."""
    temporary_path: Path | None = None

    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            text=True,
        )
        temporary_path = Path(temporary_name)

        with os.fdopen(
            descriptor,
            mode="w",
            encoding="utf-8",
            newline="\n",
        ) as stream:
            stream.write(contents)
            stream.flush()
            if fsync:
                os.fsync(stream.fileno())

        temporary_path.chmod(mode)
        os.replace(temporary_path, destination)
        temporary_path = None

        if fsync:
            _fsync_directory(destination.parent)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _run_required(
    command: tuple[str, ...],
    *,
    execute: CommandExecutor,
    commands: list[tuple[str, ...]],
    operation: str,
) -> InstallerIssue | None:
    """Run one command that must return zero."""
    commands.append(command)

    try:
        result = execute(command)
    except Exception:
        return _issue(
            f"systemctl {operation} could not be executed.",
            field=operation,
        )

    if result.return_code != 0:
        return _issue(
            f"systemctl {operation} failed.",
            field=operation,
        )

    return None


def _query_state(
    command: tuple[str, ...],
    *,
    execute: CommandExecutor,
    commands: list[tuple[str, ...]],
    operation: str,
) -> tuple[bool, InstallerIssue | None]:
    """Query one systemd state where return codes zero and one are valid."""
    commands.append(command)

    try:
        result = execute(command)
    except Exception:
        return False, _issue(
            f"systemctl {operation} could not be executed.",
            field=operation,
        )

    if result.return_code == 0:
        return True, None

    if result.return_code == 1:
        return False, None

    return False, _issue(
        f"systemctl {operation} failed.",
        field=operation,
    )


def _execute_command(command: tuple[str, ...]) -> SystemCommandResult:
    """Execute one exact command without exposing its output."""
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return SystemCommandResult(
        return_code=completed.returncode,
        standard_output=completed.stdout,
        standard_error=completed.stderr,
    )


def _apply_posix_ownership(path: Path, owner: str, group: str) -> None:
    """Apply local POSIX ownership to one managed file."""
    import grp
    import pwd

    user_record = pwd.getpwnam(owner)
    group_record = grp.getgrnam(group)
    os.chown(path, user_record.pw_uid, group_record.gr_gid)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _failed(
    *,
    changed: bool,
    backup: Path | None,
    enabled: bool,
    active: bool,
    commands: list[tuple[str, ...]],
    issue: InstallerIssue,
) -> TelegramSystemdServiceResult:
    return TelegramSystemdServiceResult(
        success=False,
        unit_changed=changed,
        backup_created=backup,
        enabled=enabled,
        active=active,
        commands=tuple(commands),
        issues=(issue,),
    )


def _issue(
    message: str,
    *,
    field: str | None = None,
    path: Path | None = None,
) -> InstallerIssue:
    return InstallerIssue(
        code=InstallerIssueCode.STEP_FAILED,
        message=message,
        step=InstallerStepId.SYSTEMD_SERVICE,
        field=field,
        path=path,
    )


def _validate_absolute_path(path: Path, *, field_name: str) -> None:
    if not isinstance(path, Path):
        raise TypeError(f"{field_name} must be a pathlib.Path value.")
    if not path.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path.")
    if "\x00" in str(path):
        raise ValueError(f"{field_name} must not contain a null byte.")
