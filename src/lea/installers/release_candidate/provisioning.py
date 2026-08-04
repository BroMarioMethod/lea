"""System account and filesystem provisioning for release-candidate installs."""

from __future__ import annotations

import grp
import os
import pwd
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lea.installers.release_candidate.contracts import (
    InstallerIssue,
    InstallerIssueCode,
    InstallerStepId,
    ReleaseCandidateInstallRequest,
)

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class ManagedDirectory:
    """One managed directory with explicit ownership and mode."""

    path: Path
    owner: str
    group: str
    mode: int

    def __post_init__(self) -> None:
        """Validate managed-directory fields."""
        _validate_absolute_path(self.path, field_name="path")

        for field_name, value in (
            ("owner", self.owner),
            ("group", self.group),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty.")

        if self.mode < 0 or self.mode > 0o7777:
            raise ValueError("mode must be a valid Unix permission mode.")


@dataclass(frozen=True, slots=True)
class ManagedFile:
    """One managed regular file with canonical contents and metadata."""

    path: Path
    contents: str
    owner: str
    group: str
    mode: int

    def __post_init__(self) -> None:
        """Validate managed-file fields."""
        _validate_absolute_path(self.path, field_name="path")

        if not isinstance(self.contents, str) or not self.contents:
            raise ValueError("contents must be non-empty.")

        for field_name, value in (
            ("owner", self.owner),
            ("group", self.group),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty.")

        if self.mode < 0 or self.mode > 0o7777:
            raise ValueError("mode must be a valid Unix permission mode.")


@dataclass(frozen=True, slots=True)
class SystemProvisioningPlan:
    """Immutable plan for the LEA account and managed directories."""

    service_user: str
    service_group: str
    directories: tuple[ManagedDirectory, ...]
    tmpfiles_configuration: ManagedFile
    systemd_tmpfiles: Path

    def __post_init__(self) -> None:
        """Validate provisioning-plan consistency."""
        for field_name, value in (
            ("service_user", self.service_user),
            ("service_group", self.service_group),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty.")

        if not self.directories:
            raise ValueError("directories must not be empty.")

        _validate_absolute_path(
            self.systemd_tmpfiles,
            field_name="systemd_tmpfiles",
        )

        paths = tuple(directory.path for directory in self.directories)
        if len(set(paths)) != len(paths):
            raise ValueError("directories must not contain duplicate paths.")


@dataclass(frozen=True, slots=True)
class SystemProvisioningResult:
    """Result of provisioning the LEA account and managed directories."""

    success: bool
    user_created: bool
    group_created: bool
    directories_changed: tuple[Path, ...]
    files_changed: tuple[Path, ...]
    issues: tuple[InstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate provisioning-result consistency."""
        for path in self.directories_changed:
            _validate_absolute_path(path, field_name="directories_changed")

        for path in self.files_changed:
            _validate_absolute_path(path, field_name="files_changed")

        if len(set(self.directories_changed)) != len(self.directories_changed):
            raise ValueError("directories_changed must not contain duplicates.")

        if len(set(self.files_changed)) != len(self.files_changed):
            raise ValueError("files_changed must not contain duplicates.")

        if self.success:
            if self.issues:
                raise ValueError("A successful result must not contain issues.")
            return

        if not self.issues:
            raise ValueError("A failed result must contain at least one issue.")


def create_system_provisioning_plan(
    request: ReleaseCandidateInstallRequest,
) -> SystemProvisioningPlan:
    """Create LEA's deterministic system account and directory plan."""
    if not isinstance(request, ReleaseCandidateInstallRequest):
        raise TypeError("request must be a ReleaseCandidateInstallRequest value.")

    directories = (
        ManagedDirectory(
            path=request.configuration_root,
            owner="root",
            group=request.service_group,
            mode=0o750,
        ),
        ManagedDirectory(
            path=request.configuration_root / "secrets",
            owner="root",
            group=request.service_group,
            mode=0o750,
        ),
        ManagedDirectory(
            path=request.configuration_root / "telegram",
            owner="root",
            group=request.service_group,
            mode=0o750,
        ),
        ManagedDirectory(
            path=request.state_root,
            owner=request.service_user,
            group=request.service_group,
            mode=0o750,
        ),
        ManagedDirectory(
            path=request.state_root / "install",
            owner="root",
            group=request.service_group,
            mode=0o750,
        ),
        ManagedDirectory(
            path=request.state_root / "audit",
            owner=request.service_user,
            group=request.service_group,
            mode=0o775,
        ),
        ManagedDirectory(
            path=request.state_root / "proposals",
            owner=request.service_user,
            group=request.service_group,
            mode=0o775,
        ),
        ManagedDirectory(
            path=request.state_root / "knowledge",
            owner=request.service_user,
            group=request.service_group,
            mode=0o775,
        ),
        ManagedDirectory(
            path=request.state_root / "indexes",
            owner=request.service_user,
            group=request.service_group,
            mode=0o775,
        ),
        ManagedDirectory(
            path=request.state_root / "adapters",
            owner=request.service_user,
            group=request.service_group,
            mode=0o775,
        ),
        ManagedDirectory(
            path=request.state_root / "backups",
            owner=request.service_user,
            group=request.service_group,
            mode=0o775,
        ),
        ManagedDirectory(
            path=request.state_root / "telegram",
            owner=request.service_user,
            group=request.service_group,
            mode=0o750,
        ),
        ManagedDirectory(
            path=Path("/run/lea"),
            owner=request.service_user,
            group=request.service_group,
            mode=0o750,
        ),
        ManagedDirectory(
            path=request.log_root,
            owner=request.service_user,
            group=request.service_group,
            mode=0o750,
        ),
    )

    return SystemProvisioningPlan(
        service_user=request.service_user,
        service_group=request.service_group,
        directories=directories,
        tmpfiles_configuration=ManagedFile(
            path=Path("/etc/tmpfiles.d/lea.conf"),
            contents=(
                f"d /run/lea 0750 {request.service_user} {request.service_group} -\n"
            ),
            owner="root",
            group="root",
            mode=0o644,
        ),
        systemd_tmpfiles=Path("/usr/bin/systemd-tmpfiles"),
    )


def provision_system_layout(
    plan: SystemProvisioningPlan,
    *,
    command_runner: CommandRunner = subprocess.run,
) -> SystemProvisioningResult:
    """Provision one system layout idempotently using exact commands."""
    if not isinstance(plan, SystemProvisioningPlan):
        raise TypeError("plan must be a SystemProvisioningPlan value.")

    user_created = False
    group_created = False
    changed: list[Path] = []
    files_changed: list[Path] = []

    try:
        if not _group_exists(plan.service_group):
            _run_checked(
                command_runner,
                (
                    "/usr/sbin/groupadd",
                    "--system",
                    plan.service_group,
                ),
            )
            group_created = True

        if not _user_exists(plan.service_user):
            _run_checked(
                command_runner,
                (
                    "/usr/sbin/useradd",
                    "--system",
                    "--gid",
                    plan.service_group,
                    "--home-dir",
                    "/nonexistent",
                    "--no-create-home",
                    "--shell",
                    "/usr/sbin/nologin",
                    plan.service_user,
                ),
            )
            user_created = True

        file_changed = _ensure_managed_file(
            plan.tmpfiles_configuration,
        )
        if file_changed:
            files_changed.append(plan.tmpfiles_configuration.path)

        _run_checked(
            command_runner,
            (
                str(plan.systemd_tmpfiles),
                "--create",
                str(plan.tmpfiles_configuration.path),
            ),
        )

        for directory in plan.directories:
            changed_now = _ensure_directory(directory)
            if changed_now:
                changed.append(directory.path)

    except (OSError, subprocess.CalledProcessError, KeyError) as error:
        return SystemProvisioningResult(
            success=False,
            user_created=user_created,
            group_created=group_created,
            directories_changed=tuple(changed),
            files_changed=tuple(files_changed),
            issues=(
                InstallerIssue(
                    code=InstallerIssueCode.STEP_FAILED,
                    message=(
                        "System account or filesystem provisioning failed: "
                        f"{type(error).__name__}."
                    ),
                    step=InstallerStepId.FILESYSTEM,
                ),
            ),
        )

    return SystemProvisioningResult(
        success=True,
        user_created=user_created,
        group_created=group_created,
        directories_changed=tuple(changed),
        files_changed=tuple(files_changed),
        issues=(),
    )


def _ensure_managed_file(managed: ManagedFile) -> bool:
    """Create or repair one exact managed regular file."""
    path = managed.path

    if path.is_symlink():
        raise OSError(f"Managed file path is a symbolic link: {path}")

    existed = path.exists()

    if existed and not path.is_file():
        raise OSError(f"Managed file path is not a regular file: {path}")

    if existed:
        existing_contents = path.read_text(encoding="utf-8")
        if existing_contents != managed.contents:
            raise PermissionError(f"Managed file contains conflicting contents: {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            managed.contents,
            encoding="utf-8",
            newline="\n",
        )

    owner = pwd.getpwnam(managed.owner)
    group = grp.getgrnam(managed.group)

    stat_result = path.stat()
    current_mode = stat_result.st_mode & 0o7777
    ownership_changed = (
        stat_result.st_uid != owner.pw_uid or stat_result.st_gid != group.gr_gid
    )
    mode_changed = current_mode != managed.mode

    if ownership_changed:
        os.chown(path, owner.pw_uid, group.gr_gid)

    if mode_changed:
        os.chmod(path, managed.mode)

    return not existed or ownership_changed or mode_changed


def _ensure_directory(directory: ManagedDirectory) -> bool:
    """Create or repair one managed directory."""
    existed = directory.path.exists()

    if existed and not directory.path.is_dir():
        raise OSError(f"Managed path is not a directory: {directory.path}")

    directory.path.mkdir(parents=True, exist_ok=True)

    owner = pwd.getpwnam(directory.owner)
    group = grp.getgrnam(directory.group)

    stat_result = directory.path.stat()
    current_mode = stat_result.st_mode & 0o7777
    ownership_changed = (
        stat_result.st_uid != owner.pw_uid or stat_result.st_gid != group.gr_gid
    )
    mode_changed = current_mode != directory.mode

    if ownership_changed:
        os.chown(directory.path, owner.pw_uid, group.gr_gid)

    if mode_changed:
        os.chmod(directory.path, directory.mode)

    return not existed or ownership_changed or mode_changed


def _run_checked(
    command_runner: CommandRunner,
    command: tuple[str, ...],
) -> None:
    """Run one exact finite command without a shell."""
    command_runner(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=30.0,
    )


def _user_exists(name: str) -> bool:
    """Return whether one local user exists."""
    try:
        pwd.getpwnam(name)
    except KeyError:
        return False
    return True


def _group_exists(name: str) -> bool:
    """Return whether one local group exists."""
    try:
        grp.getgrnam(name)
    except KeyError:
        return False
    return True


def _validate_absolute_path(
    path: Path,
    *,
    field_name: str,
) -> None:
    """Validate one absolute pathlib path."""
    if not isinstance(path, Path):
        raise TypeError(f"{field_name} must be a pathlib.Path value.")

    if not path.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path.")

    if "\x00" in str(path):
        raise ValueError(f"{field_name} must not contain a null byte.")
