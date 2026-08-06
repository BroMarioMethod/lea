"""Secure calendar-provider backup and isolated restore tooling."""

import os
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True, slots=True)
class CalendarProviderBackupResult:
    success: bool
    path: Path
    code: str | None = None


def create_calendar_provider_backup(
    destination: Path,
    *,
    sources: tuple[tuple[str, Path], ...] = (
        ("radicale-configuration", Path("/etc/lea/radicale")),
        ("radicale-secrets", Path("/var/lib/lea/secrets/radicale")),
        ("radicale-storage", Path("/var/lib/lea/radicale")),
        ("calendar-configuration", Path("/etc/lea/calendar")),
        ("calendar-state", Path("/var/lib/lea/calendar")),
        ("calendar-secrets", Path("/var/lib/lea/secrets/calendar")),
        ("installation-records", Path("/var/lib/lea/install")),
        ("acceptance-records", Path("/var/lib/lea/acceptance")),
    ),
) -> CalendarProviderBackupResult:
    """Create a root-only archive; mode 0600 exists before any secret is written."""
    if os.geteuid() != 0:
        return _failure(destination, "backup_requires_root")
    if (
        not destination.is_absolute()
        or destination.exists()
        or destination.is_symlink()
    ):
        return _failure(destination, "backup_destination_invalid")
    for _name, source in sources:
        if source.is_symlink() or not source.is_dir():
            return _failure(destination, "backup_source_invalid")
        if any(path.is_symlink() for path in source.rglob("*")):
            return _failure(destination, "backup_source_symlink")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        descriptor = os.open(destination, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        os.fchown(descriptor, 0, 0)
        with os.fdopen(descriptor, "wb") as raw:
            with tarfile.open(fileobj=raw, mode="w:gz") as archive:
                for name, source in sources:
                    archive.add(source, arcname=name, recursive=True)
            raw.flush()
            os.fsync(raw.fileno())
    except (OSError, tarfile.TarError):
        destination.unlink(missing_ok=True)
        return _failure(destination, "backup_creation_failed")
    stat = destination.stat()
    if (
        stat.st_uid != os.getuid()
        or stat.st_gid != os.getgid()
        or stat.st_mode & 0o777 != 0o600
    ):
        return _failure(destination, "backup_metadata_invalid")
    return CalendarProviderBackupResult(True, destination)


def restore_calendar_provider_backup_isolated(
    archive_path: Path, destination: Path
) -> CalendarProviderBackupResult:
    """Extract only safe members into a new isolated root-only directory."""
    if os.geteuid() != 0:
        return _failure(destination, "restore_requires_root")
    archive_stat = archive_path.stat() if archive_path.exists() else None
    if (
        archive_path.is_symlink()
        or not archive_path.is_file()
        or archive_stat is None
        or archive_stat.st_mode & 0o077
        or archive_stat.st_uid != os.getuid()
        or archive_stat.st_gid != os.getgid()
    ):
        return _failure(destination, "restore_archive_invalid")
    if (
        not destination.is_absolute()
        or destination.exists()
        or destination.is_symlink()
    ):
        return _failure(destination, "restore_destination_invalid")
    destination.mkdir(mode=0o700)
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = archive.getmembers()
            for member in members:
                path = PurePosixPath(member.name)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or member.issym()
                    or member.islnk()
                    or member.isdev()
                    or member.isfifo()
                ):
                    raise tarfile.TarError("unsafe archive member")
            archive.extractall(destination, members=members, filter="fully_trusted")
    except (OSError, tarfile.TarError, TypeError):
        return _failure(destination, "restore_failed")
    return CalendarProviderBackupResult(True, destination)


def _failure(path: Path, code: str) -> CalendarProviderBackupResult:
    return CalendarProviderBackupResult(False, path, code)
