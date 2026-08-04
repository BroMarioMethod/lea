"""System account and filesystem provisioning for release-candidate installs."""

from __future__ import annotations

import grp
import os
import pwd
import stat
import subprocess
import tempfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

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
    legacy_contents: tuple[str, ...] = ()

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

        if not isinstance(self.legacy_contents, tuple):
            raise TypeError("legacy_contents must be a tuple.")

        if any(
            not isinstance(contents, str) or not contents
            for contents in self.legacy_contents
        ):
            raise ValueError("legacy_contents entries must be non-empty strings.")

        if len(set(self.legacy_contents)) != len(self.legacy_contents):
            raise ValueError("legacy_contents entries must be unique.")

        if self.contents in self.legacy_contents:
            raise ValueError("Canonical contents must not also be legacy contents.")


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
            mode=0o2770,
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
            mode=0o2770,
        ),
        ManagedDirectory(
            path=request.state_root / "proposals",
            owner=request.service_user,
            group=request.service_group,
            mode=0o2770,
        ),
        ManagedDirectory(
            path=request.state_root / "knowledge",
            owner=request.service_user,
            group=request.service_group,
            mode=0o2770,
        ),
        ManagedDirectory(
            path=request.state_root / "indexes",
            owner=request.service_user,
            group=request.service_group,
            mode=0o2770,
        ),
        ManagedDirectory(
            path=request.state_root / "adapters",
            owner=request.service_user,
            group=request.service_group,
            mode=0o2770,
        ),
        ManagedDirectory(
            path=request.state_root / "backups",
            owner=request.service_user,
            group=request.service_group,
            mode=0o2770,
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
            mode=0o2770,
        ),
        ManagedDirectory(
            path=request.log_root,
            owner=request.service_user,
            group=request.service_group,
            mode=0o2770,
        ),
    )

    return SystemProvisioningPlan(
        service_user=request.service_user,
        service_group=request.service_group,
        directories=directories,
        tmpfiles_configuration=ManagedFile(
            path=Path("/etc/tmpfiles.d/lea.conf"),
            contents=(
                f"d /run/lea 2770 {request.service_user} {request.service_group} -\n"
            ),
            owner="root",
            legacy_contents=(
                f"d /run/lea 0750 {request.service_user} {request.service_group} -\n",
            ),
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

        audit_directory = next(
            directory
            for directory in plan.directories
            if directory.path.name == "audit"
        )
        audit_file_changed = _ensure_runtime_audit_file(audit_directory)
        if audit_file_changed is not None:
            files_changed.append(audit_file_changed)

        proposal_directory = next(
            directory
            for directory in plan.directories
            if directory.path.name == "proposals"
        )
        files_changed.extend(_repair_managed_proposal_documents(proposal_directory))

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


_AUDIT_FILE_NAME = "actions-integrity.jsonl"
_AUDIT_FILE_MODE = 0o660


def _ensure_runtime_audit_file(
    directory: ManagedDirectory,
) -> Path | None:
    """Create or repair audit metadata without changing its contents."""
    path = directory.path / _AUDIT_FILE_NAME

    if path.is_symlink():
        raise OSError(f"Managed audit file path is a symbolic link: {path}")

    owner = pwd.getpwnam(directory.owner)
    group = grp.getgrnam(directory.group)

    try:
        existing_stat = path.lstat()
    except FileNotFoundError:
        existed = False
        expected_identity = None
    else:
        existed = True

        if not stat.S_ISREG(existing_stat.st_mode):
            raise OSError(f"Managed audit file path is not a regular file: {path}")

        expected_identity = (
            existing_stat.st_dev,
            existing_stat.st_ino,
        )

    no_follow = getattr(os, "O_NOFOLLOW", 0)

    if existed:
        descriptor = os.open(
            path,
            os.O_RDONLY | no_follow,
        )
    else:
        try:
            descriptor = os.open(
                path,
                (os.O_WRONLY | os.O_CREAT | os.O_EXCL | no_follow),
                _AUDIT_FILE_MODE,
            )
        except FileExistsError as error:
            raise OSError(
                f"Managed audit file appeared during creation: {path}"
            ) from error

    try:
        current_stat = os.fstat(descriptor)

        if not stat.S_ISREG(current_stat.st_mode):
            raise OSError(f"Managed audit file descriptor is not regular: {path}")

        if (
            expected_identity is not None
            and (
                current_stat.st_dev,
                current_stat.st_ino,
            )
            != expected_identity
        ):
            raise OSError(f"Managed audit file changed during repair: {path}")

        ownership_changed = (
            current_stat.st_uid != owner.pw_uid or current_stat.st_gid != group.gr_gid
        )
        mode_changed = stat.S_IMODE(current_stat.st_mode) != _AUDIT_FILE_MODE

        if ownership_changed:
            os.fchown(
                descriptor,
                owner.pw_uid,
                group.gr_gid,
            )

        if mode_changed:
            os.fchmod(
                descriptor,
                _AUDIT_FILE_MODE,
            )
    finally:
        os.close(descriptor)

    if not existed or ownership_changed or mode_changed:
        return path

    return None


def _ensure_managed_file(managed: ManagedFile) -> bool:
    """Create, repair or migrate one exact managed regular file."""
    path = managed.path

    if path.is_symlink():
        raise OSError(f"Managed file path is a symbolic link: {path}")

    existed = path.exists()

    if existed and not path.is_file():
        raise OSError(f"Managed file path is not a regular file: {path}")

    owner = pwd.getpwnam(managed.owner)
    group = grp.getgrnam(managed.group)
    contents_changed = False

    if existed:
        existing_stat = path.lstat()
        existing_identity = (
            existing_stat.st_dev,
            existing_stat.st_ino,
        )
        existing_contents = path.read_text(encoding="utf-8")

        if existing_contents != managed.contents:
            if existing_contents not in managed.legacy_contents:
                raise PermissionError(
                    f"Managed file contains conflicting contents: {path}"
                )

            _replace_managed_file_contents(
                managed,
                expected_identity=existing_identity,
                expected_contents=existing_contents,
                owner_uid=owner.pw_uid,
                group_gid=group.gr_gid,
            )
            contents_changed = True
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            managed.contents,
            encoding="utf-8",
            newline="\n",
        )

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

    return not existed or contents_changed or ownership_changed or mode_changed


def _replace_managed_file_contents(
    managed: ManagedFile,
    *,
    expected_identity: tuple[int, int],
    expected_contents: str,
    owner_uid: int,
    group_gid: int,
) -> None:
    """Atomically migrate one recognised previous managed document."""
    path = managed.path
    temporary_path: Path | None = None

    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".managed",
            dir=path.parent,
            text=True,
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, managed.mode)

        with os.fdopen(
            descriptor,
            mode="w",
            encoding="utf-8",
            newline="\n",
        ) as stream:
            stream.write(managed.contents)
            stream.flush()
            os.fsync(stream.fileno())

        os.chown(
            temporary_path,
            owner_uid,
            group_gid,
        )

        if path.is_symlink() or not path.is_file():
            raise OSError(f"Managed file changed type during repair: {path}")

        current_stat = path.lstat()
        current_identity = (
            current_stat.st_dev,
            current_stat.st_ino,
        )

        if current_identity != expected_identity:
            raise OSError(f"Managed file changed during repair: {path}")

        if path.read_text(encoding="utf-8") != expected_contents:
            raise OSError(f"Managed file contents changed during repair: {path}")

        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)


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


def _repair_managed_proposal_documents(
    directory: ManagedDirectory,
) -> tuple[Path, ...]:
    """Repair metadata for canonical managed proposal documents."""
    owner = pwd.getpwnam(directory.owner)
    group = grp.getgrnam(directory.group)
    changed: list[Path] = []

    for path in sorted(directory.path.iterdir()):
        if not _is_canonical_proposal_document(path):
            continue

        if path.is_symlink() or not path.is_file():
            raise OSError(f"Managed proposal path is not a regular file: {path}")

        stat_result = path.stat()
        ownership_changed = (
            stat_result.st_uid != owner.pw_uid or stat_result.st_gid != group.gr_gid
        )
        mode_changed = stat_result.st_mode & 0o7777 != 0o640

        if ownership_changed:
            os.chown(path, owner.pw_uid, group.gr_gid)

        if mode_changed:
            os.chmod(path, 0o640)

        if ownership_changed or mode_changed:
            changed.append(path)

    return tuple(changed)


def _is_canonical_proposal_document(path: Path) -> bool:
    """Return whether a path uses LEA's canonical proposal filename."""
    if path.suffix != ".md":
        return False

    try:
        identifier = UUID(path.stem)
    except ValueError:
        return False

    return str(identifier) == path.stem


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
