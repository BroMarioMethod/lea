"""Supported administrative CLI for the Milestone 4 calendar provider."""

import argparse
import grp
import os
import pwd
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

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
    bootstrap = commands.add_parser(
        "bootstrap", help="Approve first collection creation."
    )
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


def _credential(value: str) -> RadicaleCredential:
    username, separator, raw_path = value.partition("=")
    if not separator:
        raise ValueError("--credential must be USER=HASH_FILE")
    return RadicaleCredential(username, _protected_line(Path(raw_path)))


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
