"""Deterministic vdirsyncer CalDAV pair and separate password provisioning."""

import json
import os
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from lea.installers.calendar.configuration import (
    render_calendar_vdirsyncer_configuration,
)
from lea.installers.calendar.runtime_layout import CalendarToolchainRuntimeLayout

_USERNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}$")


@dataclass(frozen=True, slots=True)
class CalendarCaldavSyncConfig:
    """Non-secret inputs for one two-way CalDAV synchronization pair."""

    layout: CalendarToolchainRuntimeLayout
    url: str
    username: str
    password_file: Path
    password_reader: Path = Path("/usr/bin/cat")

    def __post_init__(self) -> None:
        if not isinstance(self.layout, CalendarToolchainRuntimeLayout):
            raise TypeError("layout must be a CalendarToolchainRuntimeLayout value.")
        parsed = urlsplit(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("url must be one explicit HTTP or HTTPS endpoint.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("url must not contain credentials, query, or fragment.")
        if not self.url.endswith("/"):
            raise ValueError("url must end with a collection-discovery slash.")
        if _USERNAME.fullmatch(self.username) is None:
            raise ValueError("username must use safe account characters.")
        for name, path in (
            ("password_file", self.password_file),
            ("password_reader", self.password_reader),
        ):
            if not isinstance(path, Path) or not path.is_absolute():
                raise ValueError(f"{name} must be an absolute path.")
        if self.password_file == self.layout.vdirsyncer_configuration:
            raise ValueError("password_file must be separate from configuration.")


@dataclass(frozen=True, slots=True)
class CalendarCaldavPassword:
    """Runtime-only plaintext used solely to provision the secret file."""

    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.value or "\n" in self.value or "\r" in self.value:
            raise ValueError("CalDAV password must be non-empty and single-line.")


@dataclass(frozen=True, slots=True)
class CalendarCaldavSecretIssue:
    """One redaction-safe password-file provisioning problem."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class CalendarCaldavSecretResult:
    """Result of exact CalDAV password-file provisioning."""

    success: bool
    changed: bool
    path: Path
    issues: tuple[CalendarCaldavSecretIssue, ...]


@dataclass(frozen=True, slots=True)
class CalendarCaldavActivationResult:
    """Result of explicitly replacing the local-only sync configuration."""

    success: bool
    changed: bool
    backup_file: Path | None
    issues: tuple[CalendarCaldavSecretIssue, ...]


def render_calendar_caldav_vdirsyncer_configuration(
    config: CalendarCaldavSyncConfig,
) -> str:
    """Render a two-way pair with explicit conflict errors and fetched password."""
    if not isinstance(config, CalendarCaldavSyncConfig):
        raise TypeError("config must be a CalendarCaldavSyncConfig value.")
    quote = json.dumps
    layout = config.layout
    lines = (
        "[general]",
        f"status_path = {quote(str(layout.vdirsyncer_status))}",
        "",
        "[pair lea_calendars]",
        'a = "lea_local"',
        'b = "lea_radicale"',
        'collections = ["from a", "from b"]',
        "conflict_resolution = null",
        'metadata = ["color", "displayname", "description", "order"]',
        "",
        "[storage lea_local]",
        'type = "filesystem"',
        f"path = {quote(str(layout.vdirs))}",
        'fileext = ".ics"',
        "",
        "[storage lea_radicale]",
        'type = "caldav"',
        f"url = {quote(config.url)}",
        f"username = {quote(config.username)}",
        "password.fetch = "
        + json.dumps(
            ["command", str(config.password_reader), str(config.password_file)]
        ),
        'auth = "basic"',
        "",
    )
    return "\n".join(lines)


def provision_calendar_caldav_password(
    path: Path,
    password: CalendarCaldavPassword,
) -> CalendarCaldavSecretResult:
    """Atomically create a mode-0600 password file without replacing drift."""
    if not path.is_absolute():
        raise ValueError("path must be absolute.")
    contents = (password.value + "\n").encode()
    if path.parent.is_symlink() or not path.parent.is_dir():
        return _secret_failure(
            path,
            "calendar_caldav_secret_parent_invalid",
            "The CalDAV secret directory is unavailable.",
        )
    if path.parent.stat().st_mode & 0o077:
        return _secret_failure(
            path,
            "calendar_caldav_secret_parent_permissions_invalid",
            "The CalDAV secret directory permissions are too broad.",
        )
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            return _secret_failure(
                path,
                "calendar_caldav_secret_invalid",
                "The CalDAV password path is not a regular non-symbolic file.",
            )
        try:
            if path.read_bytes() == contents and path.stat().st_mode & 0o777 == 0o600:
                return CalendarCaldavSecretResult(True, False, path, ())
        except OSError:
            pass
        return _secret_failure(
            path,
            "calendar_caldav_secret_mismatch",
            "The existing CalDAV password file does not match requested state.",
        )
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    except OSError:
        return _secret_failure(
            path,
            "calendar_caldav_secret_write_failed",
            "The CalDAV password file could not be created.",
        )
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
    return CalendarCaldavSecretResult(True, True, path, ())


def activate_calendar_caldav_configuration(
    config: CalendarCaldavSyncConfig,
    *,
    approve_replacement: bool,
) -> CalendarCaldavActivationResult:
    """Back up and atomically replace only the exact local-only baseline."""
    destination = config.layout.vdirsyncer_configuration
    expected = render_calendar_caldav_vdirsyncer_configuration(config).encode()
    baseline = render_calendar_vdirsyncer_configuration(config.layout).encode()
    prerequisite = _activation_prerequisite(config)
    if prerequisite is not None:
        return _activation_failure(prerequisite)
    try:
        actual = destination.read_bytes()
    except OSError:
        return _activation_failure(
            CalendarCaldavSecretIssue(
                "calendar_caldav_configuration_unavailable",
                "The installed vdirsyncer configuration could not be read.",
            )
        )
    if actual == expected and destination.stat().st_mode & 0o777 == 0o640:
        return CalendarCaldavActivationResult(True, False, None, ())
    if actual != baseline:
        return _activation_failure(
            CalendarCaldavSecretIssue(
                "calendar_caldav_configuration_drift",
                "The installed vdirsyncer configuration is not the managed baseline.",
            )
        )
    if not approve_replacement:
        return _activation_failure(
            CalendarCaldavSecretIssue(
                "calendar_caldav_replacement_approval_required",
                (
                    "CalDAV configuration activation requires explicit "
                    "replacement approval."
                ),
            )
        )
    backup = destination.with_name(f"{destination.name}.local-only.backup")
    if backup.exists() or backup.is_symlink():
        return _activation_failure(
            CalendarCaldavSecretIssue(
                "calendar_caldav_backup_exists",
                "The canonical CalDAV configuration backup already exists.",
            )
        )
    temporary: Path | None = None
    try:
        os.link(destination, backup)
        descriptor, name = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        temporary = Path(name)
        os.fchmod(descriptor, 0o640)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(expected)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        temporary = None
    except OSError:
        return _activation_failure(
            CalendarCaldavSecretIssue(
                "calendar_caldav_activation_failed",
                "The CalDAV synchronization configuration could not be activated.",
            ),
            backup=backup if backup.exists() else None,
        )
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
    return CalendarCaldavActivationResult(True, True, backup, ())


def _activation_prerequisite(
    config: CalendarCaldavSyncConfig,
) -> CalendarCaldavSecretIssue | None:
    for path, executable, code, message in (
        (
            config.layout.vdirsyncer_configuration,
            False,
            "calendar_caldav_configuration_unavailable",
            "The installed vdirsyncer configuration is unavailable.",
        ),
        (
            config.password_file,
            False,
            "calendar_caldav_secret_invalid",
            "The CalDAV password file is unavailable.",
        ),
        (
            config.password_reader,
            True,
            "calendar_caldav_password_reader_invalid",
            "The exact CalDAV password reader is unavailable.",
        ),
    ):
        if (
            path.is_symlink()
            or not path.is_file()
            or (executable and not os.access(path, os.X_OK))
        ):
            return CalendarCaldavSecretIssue(code, message)
    if config.password_file.stat().st_mode & 0o077:
        return CalendarCaldavSecretIssue(
            "calendar_caldav_secret_permissions_invalid",
            "The CalDAV password file permissions are too broad.",
        )
    return None


def _activation_failure(
    issue: CalendarCaldavSecretIssue,
    *,
    backup: Path | None = None,
) -> CalendarCaldavActivationResult:
    return CalendarCaldavActivationResult(False, False, backup, (issue,))


def _secret_failure(path: Path, code: str, message: str) -> CalendarCaldavSecretResult:
    return CalendarCaldavSecretResult(
        False, False, path, (CalendarCaldavSecretIssue(code, message),)
    )
