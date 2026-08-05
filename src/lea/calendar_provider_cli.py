"""Supported administrative CLI for the Milestone 4 calendar provider."""

import argparse
import base64
import grp
import os
import pwd
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO
from urllib.parse import quote, urlsplit

from lea.adapters.vdirsyncer import VdirsyncerConfig, VdirsyncerRunner
from lea.installers.calendar.caldav_configuration import (
    CalendarCaldavPassword,
    CalendarCaldavSyncConfig,
    activate_calendar_caldav_configuration,
    provision_calendar_caldav_password,
)
from lea.installers.calendar.runtime_layout import CalendarToolchainRuntimeLayout
from lea.installers.radicale.binary import RadicaleBinaryConfig
from lea.installers.radicale.configuration import canonical_radicale_runtime_layout
from lea.installers.radicale.contracts import RadicaleServerConfig
from lea.installers.radicale.credentials import RadicaleCredential
from lea.installers.radicale.distribution import (
    RadicaleDistributionRequest,
    install_radicale_distribution,
)
from lea.installers.radicale.health import RadicaleAcceptanceAccount
from lea.installers.radicale.orchestration import (
    RadicaleInstallRequest,
    install_radicale,
)
from lea.installers.radicale.recovery import (
    create_calendar_provider_backup,
    restore_calendar_provider_backup_isolated,
)
from lea.installers.radicale.service import RadicaleServiceConfig

RADICALE_LOCK_SHA256 = (
    "bc339317cbda1deec4cd7cff15bed10539297341471e67fbb05c3b906db70669"
)
_COLLECTION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lea calendar-provider")
    commands = parser.add_subparsers(dest="operation", required=True)
    install = commands.add_parser(
        "install", help="Install Radicale and activate CalDAV."
    )
    install.add_argument("--bind-address", required=True)
    install.add_argument("--port", type=int, default=5232)
    credential_inputs = install.add_mutually_exclusive_group(required=True)
    credential_inputs.add_argument(
        "--credential", action="append", metavar="USER=HASH_FILE"
    )
    credential_inputs.add_argument(
        "--credentials-file", type=Path, metavar="HTPASSWD_FILE"
    )
    install.add_argument("--caldav-username", required=True)
    install.add_argument("--caldav-password-file", type=Path, required=True)
    install.add_argument("--uv-executable", type=Path, required=True)
    install.add_argument("--python-executable", type=Path, required=True)
    install.add_argument(
        "--requirements-lock",
        type=Path,
        default=Path("/opt/lea-release-assets/radicale-requirements.lock"),
    )
    install.add_argument("--requirements-sha256", default=RADICALE_LOCK_SHA256)
    install.add_argument("--approve-replacement", action="store_true", required=True)
    install.add_argument("--activate", action="store_true", required=True)
    install.add_argument(
        "--acceptance-account",
        action="append",
        default=[],
        metavar="USER=PASSWORD_FILE",
        help="Repeat exactly twice to verify reciprocal user isolation.",
    )
    bootstrap = commands.add_parser(
        "bootstrap", help="Approve first collection creation."
    )
    bootstrap.add_argument("--base-url", required=True)
    bootstrap.add_argument("--username", required=True)
    bootstrap.add_argument("--password-file", type=Path, required=True)
    bootstrap.add_argument("--collection-name", required=True)
    bootstrap.add_argument(
        "--approve-first-collection", action="store_true", required=True
    )
    backup = commands.add_parser("backup")
    backup.add_argument("--output", type=Path, required=True)
    restore = commands.add_parser("restore-isolated")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    return parser


def execute_calendar_provider_cli(
    arguments: Sequence[str],
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    try:
        namespace = create_parser().parse_args(list(arguments))
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else 2
    if os.geteuid() != 0:
        stderr.write("calendar-provider operations require root.\n")
        return 1
    try:
        if namespace.operation == "install":
            return _install(namespace, stdout, stderr)
        if namespace.operation == "bootstrap":
            _bootstrap_remote_collection(
                namespace.base_url,
                namespace.username,
                namespace.password_file,
                namespace.collection_name,
            )
            runner = VdirsyncerRunner(_vdirsyncer_config())
            result = runner.run(
                ("discover",),
                operation="calendar_collection_bootstrap",
                approved_input=b"y\n",
            )
            if not result.success:
                stderr.write("Collection bootstrap failed.\n")
                return 1
            stdout.write("Calendar first collection bootstrap: SUCCESS\n")
            return 0
        if namespace.operation == "backup":
            recovery = create_calendar_provider_backup(namespace.output)
        else:
            recovery = restore_calendar_provider_backup_isolated(
                namespace.archive, namespace.destination
            )
        if not recovery.success:
            stderr.write(f"Calendar provider recovery failed: {recovery.code}\n")
            return 1
        stdout.write(f"Calendar provider {namespace.operation}: SUCCESS\n")
        return 0
    except (OSError, ValueError, TypeError) as error:
        stderr.write(f"Invalid calendar-provider input: {error}\n")
        return 2


def _install(namespace: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    _prepare_provider_parents()
    distribution = install_radicale_distribution(
        RadicaleDistributionRequest(
            requirements_lock=namespace.requirements_lock,
            expected_lock_sha256=namespace.requirements_sha256,
            uv_executable=namespace.uv_executable,
            python_executable=namespace.python_executable,
        )
    )
    if (
        not distribution.success
        or distribution.executable is None
        or distribution.executable_sha256 is None
    ):
        stderr.write(f"Radicale distribution failed: {distribution.code}\n")
        return 1
    credentials = (
        _credentials_file(namespace.credentials_file)
        if namespace.credentials_file is not None
        else tuple(_credential(value) for value in namespace.credential)
    )
    acceptance_accounts = tuple(
        _acceptance_account(value) for value in namespace.acceptance_account
    )
    if acceptance_accounts and len(acceptance_accounts) != 2:
        raise ValueError("--acceptance-account must be omitted or repeated twice")
    layout = canonical_radicale_runtime_layout()
    server = RadicaleServerConfig(layout, namespace.bind_address, namespace.port)
    service = RadicaleServiceConfig(
        distribution.executable,
        layout,
        Path("/etc/systemd/system/lea-radicale.service"),
        Path("/usr/bin/systemctl"),
    )
    binary = RadicaleBinaryConfig(
        distribution.executable,
        "3.5.4",
        distribution.executable_sha256,
        Path("/var/lib/lea/install/radicale.json"),
        Path("/opt/lea-tools/radicale/3.5.4"),
    )
    result = install_radicale(
        RadicaleInstallRequest(
            binary,
            server,
            service,
            credentials,
            f"http://{namespace.bind_address}:{namespace.port}/",
            True,
            acceptance_accounts,
        )
    )
    if not result.success:
        stderr.write(f"Radicale provisioning failed: {result.issues[0].code}\n")
        return 1
    source_password = _protected_line(namespace.caldav_password_file)
    password_path = Path("/var/lib/lea/secrets/calendar/caldav-password")
    secret = provision_calendar_caldav_password(
        password_path, CalendarCaldavPassword(source_password)
    )
    if not secret.success:
        stderr.write(f"CalDAV secret provisioning failed: {secret.issues[0].code}\n")
        return 1
    _apply_and_verify(password_path, 0o600, "lea", "lea", readable=True)
    sync = CalendarCaldavSyncConfig(
        _calendar_layout(),
        f"http://{namespace.bind_address}:{namespace.port}/",
        namespace.caldav_username,
        password_path,
    )
    activation = activate_calendar_caldav_configuration(
        sync, approve_replacement=namespace.approve_replacement
    )
    if not activation.success:
        stderr.write(f"CalDAV activation failed: {activation.issues[0].code}\n")
        return 1
    _apply_and_verify(
        sync.layout.vdirsyncer_configuration,
        0o640,
        "root",
        "lea",
        readable=True,
    )
    for path, mode in (
        (layout.configuration_directory, 0o750),
        (layout.configuration_file, 0o640),
        (layout.secrets_directory, 0o700),
        (layout.users_file, 0o600),
        (layout.storage_directory, 0o750),
    ):
        _apply_and_verify(path, mode, "lea", "lea", readable=True)
    stdout.write("Radicale and CalDAV provisioning: SUCCESS\n")
    return 0


def _prepare_provider_parents() -> None:
    """Create exact provider-owned parents omitted by the base LEA lifecycle."""
    policies = (
        (Path("/opt/lea-tools/radicale"), 0o750, "root", "lea"),
        (Path("/var/lib/lea/secrets"), 0o750, "root", "lea"),
        (Path("/var/lib/lea/secrets/calendar"), 0o700, "lea", "lea"),
    )
    for path, mode, owner, group in policies:
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise OSError("managed provider parent is unsafe")
        path.mkdir(mode=mode, parents=False, exist_ok=True)
        _apply_and_verify(path, mode, owner, group, readable=True)


def _bootstrap_remote_collection(
    base_url: str, username: str, password_file: Path, collection_name: str
) -> None:
    """Create one declared Radicale collection without interactive input."""
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not base_url.endswith("/")
    ):
        raise ValueError("base URL must be an explicit credential-free HTTP URL")
    if _COLLECTION_NAME.fullmatch(username) is None:
        raise ValueError("username must use safe account characters")
    if _COLLECTION_NAME.fullmatch(collection_name) is None:
        raise ValueError("collection name must use safe account characters")
    password = _protected_line(password_file)
    endpoint = (
        f"{base_url}{quote(username, safe='')}/{quote(collection_name, safe='')}/"
    )
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    request = urllib.request.Request(
        endpoint,
        data=(
            b'<?xml version="1.0" encoding="utf-8"?>'
            b'<C:mkcalendar xmlns:C="urn:ietf:params:xml:ns:caldav"/>'
        ),
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/xml; charset=utf-8",
        },
        method="MKCALENDAR",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    except (OSError, urllib.error.URLError) as error:
        raise OSError("remote collection bootstrap request failed") from error
    if status not in {201, 204, 405}:
        raise OSError("remote collection bootstrap was rejected")
    probe = urllib.request.Request(
        endpoint,
        headers={"Authorization": f"Basic {token}", "Depth": "0"},
        method="PROPFIND",
    )
    try:
        with urllib.request.urlopen(probe, timeout=30) as response:
            probe_status = response.status
    except (OSError, urllib.error.URLError) as error:
        raise OSError("remote collection bootstrap verification failed") from error
    if probe_status != 207:
        raise OSError("remote collection bootstrap verification failed")


def _credential(value: str) -> RadicaleCredential:
    username, separator, raw_path = value.partition("=")
    if not separator:
        raise ValueError("--credential must be USER=HASH_FILE")
    return RadicaleCredential(username, _protected_line(Path(raw_path)))


def _acceptance_account(value: str) -> RadicaleAcceptanceAccount:
    username, separator, raw_path = value.partition("=")
    if not separator:
        raise ValueError("--acceptance-account must be USER=PASSWORD_FILE")
    return RadicaleAcceptanceAccount(username, _protected_line(Path(raw_path)))


def _credentials_file(path: Path) -> tuple[RadicaleCredential, ...]:
    """Load a protected canonical htpasswd file without exposing verifiers."""
    return _parse_credentials_document(_protected_document(path))


def _parse_credentials_document(document: str) -> tuple[RadicaleCredential, ...]:
    """Parse canonical htpasswd contents after its path has been protected."""
    credentials: list[RadicaleCredential] = []
    for line in document.splitlines():
        username, separator, bcrypt_hash = line.partition(":")
        if not separator:
            raise ValueError("credentials file must use canonical htpasswd lines")
        credentials.append(RadicaleCredential(username, bcrypt_hash))
    if not credentials:
        raise ValueError("credentials file must contain at least one account")
    return tuple(credentials)


def _protected_line(path: Path) -> str:
    value = _protected_document(path).rstrip("\n")
    if not value or "\n" in value or "\r" in value:
        raise ValueError("secret inputs must contain one non-empty line")
    return value


def _protected_document(path: Path) -> str:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("secret inputs must be absolute regular files")
    stat = path.stat()
    if stat.st_mode & 0o077:
        raise ValueError("secret input permissions must be 0600 or stricter")
    if stat.st_uid != 0 or stat.st_gid != 0:
        raise ValueError("secret inputs must be owned by root:root")
    return path.read_text(encoding="utf-8")


def _apply_and_verify(
    path: Path, mode: int, owner: str, group: str, *, readable: bool
) -> None:
    user = pwd.getpwnam(owner)
    group_record = grp.getgrnam(group)
    os.chmod(path, mode, follow_symlinks=False)
    os.chown(path, user.pw_uid, group_record.gr_gid, follow_symlinks=False)
    stat = path.stat()
    if (
        stat.st_mode & 0o777 != mode
        or stat.st_uid != user.pw_uid
        or stat.st_gid != group_record.gr_gid
    ):
        raise OSError("managed path metadata verification failed")
    if readable and not _service_can_read(
        path, user.pw_uid, group_record.gr_gid, stat.st_mode
    ):
        raise OSError("managed path is not readable by the lea service account")
    if readable:
        inspected = subprocess.run(
            ("/usr/sbin/runuser", "-u", owner, "--", "/usr/bin/test", "-r", str(path)),
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=10,
        )
        if inspected.returncode != 0:
            raise OSError("effective lea service readability verification failed")


def _service_can_read(path: Path, uid: int, gid: int, mode: int) -> bool:
    stat = path.stat()
    return bool(
        (stat.st_uid == uid and mode & 0o400)
        or (stat.st_gid == gid and mode & 0o040)
        or mode & 0o004
    )


def _calendar_layout() -> CalendarToolchainRuntimeLayout:
    return CalendarToolchainRuntimeLayout(
        Path("/etc/lea/calendar"),
        Path("/etc/lea/calendar/khal.conf"),
        Path("/etc/lea/calendar/vdirsyncer.conf"),
        Path("/var/lib/lea/calendar"),
        Path("/var/lib/lea/calendar/vdirs"),
        Path("/var/lib/lea/calendar/khal"),
        Path("/var/lib/lea/calendar/vdirsyncer-status"),
    )


def _vdirsyncer_config() -> VdirsyncerConfig:
    return VdirsyncerConfig(
        Path("/opt/lea-tools/calendar/1.0.0/.venv/bin/vdirsyncer"),
        Path("/etc/lea/calendar/vdirsyncer.conf"),
        Path("/var/lib/lea/calendar"),
        "0.19.3",
    )
