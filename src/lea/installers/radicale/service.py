"""Hardened systemd unit rendering and explicit Radicale service lifecycle."""

import os
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from lea.installers.radicale.contracts import RadicaleRuntimeLayout


@dataclass(frozen=True, slots=True)
class RadicaleServiceConfig:
    """Exact executable, filesystem, and systemd service inputs."""

    executable: Path
    layout: RadicaleRuntimeLayout
    unit_file: Path
    systemctl: Path
    service_name: str = "lea-radicale.service"
    user: str = "lea"
    group: str = "lea"

    def __post_init__(self) -> None:
        """Validate service inputs without filesystem mutation."""
        for name, path in (
            ("executable", self.executable),
            ("unit_file", self.unit_file),
            ("systemctl", self.systemctl),
        ):
            if not isinstance(path, Path) or not path.is_absolute():
                raise ValueError(f"{name} must be an absolute path.")
        if not isinstance(self.layout, RadicaleRuntimeLayout):
            raise TypeError("layout must be a RadicaleRuntimeLayout value.")
        if self.unit_file.name != self.service_name:
            raise ValueError("unit_file must match service_name.")
        if "/" in self.service_name or not self.service_name.endswith(".service"):
            raise ValueError("service_name must be one systemd service unit.")
        for name, value in (("user", self.user), ("group", self.group)):
            if not value or any(character.isspace() for character in value):
                raise ValueError(f"{name} must be one non-empty account name.")


@dataclass(frozen=True, slots=True)
class RadicaleServiceIssue:
    """One redaction-safe service lifecycle problem."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class RadicaleServiceResult:
    """Result of explicit service activation and health inspection."""

    success: bool
    enabled: bool
    active: bool
    commands: tuple[tuple[str, ...], ...]
    issues: tuple[RadicaleServiceIssue, ...]


@dataclass(frozen=True, slots=True)
class ServiceCommandResult:
    """Sanitized subprocess status used by the service boundary."""

    return_code: int


ServiceCommandExecutor = Callable[[tuple[str, ...]], ServiceCommandResult]


@dataclass(frozen=True, slots=True)
class RadicaleUnitProvisionResult:
    """Result of exact systemd unit provisioning without activation."""

    success: bool
    changed: bool
    issues: tuple[RadicaleServiceIssue, ...]


def render_radicale_systemd_unit(config: RadicaleServiceConfig) -> str:
    """Render one hardened service tied to exact managed paths."""
    if not isinstance(config, RadicaleServiceConfig):
        raise TypeError("config must be a RadicaleServiceConfig value.")
    layout = config.layout
    return "\n".join(
        (
            "[Unit]",
            "Description=LEA Radicale CalDAV server",
            "After=network-online.target",
            "Wants=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            f"User={config.user}",
            f"Group={config.group}",
            f"ExecStart={config.executable} --config {layout.configuration_file}",
            "Restart=on-failure",
            "RestartSec=5s",
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "ProtectSystem=strict",
            "ProtectHome=true",
            "ProtectKernelTunables=true",
            "ProtectKernelModules=true",
            "ProtectControlGroups=true",
            "RestrictSUIDSGID=true",
            "LockPersonality=true",
            "MemoryDenyWriteExecute=true",
            f"ReadOnlyPaths={layout.configuration_directory}",
            f"ReadOnlyPaths={layout.secrets_directory}",
            f"ReadWritePaths={layout.storage_directory}",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        )
    )


def provision_radicale_systemd_unit(
    config: RadicaleServiceConfig,
) -> RadicaleUnitProvisionResult:
    """Atomically install the exact unit without reloading or starting systemd."""
    contents = render_radicale_systemd_unit(config).encode("utf-8")
    path = config.unit_file
    if path.parent.is_symlink() or not path.parent.is_dir():
        return _unit_failure(
            "radicale_unit_parent_invalid",
            "The systemd unit directory must be an existing non-symbolic directory.",
        )
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            return _unit_failure(
                "radicale_unit_invalid",
                "The Radicale unit path is not a regular non-symbolic file.",
            )
        try:
            if path.read_bytes() == contents and path.stat().st_mode & 0o777 == 0o644:
                return RadicaleUnitProvisionResult(True, False, ())
        except OSError:
            pass
        return _unit_failure(
            "radicale_unit_mismatch",
            "The existing Radicale unit does not match requested state.",
        )
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(name)
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    except OSError:
        return _unit_failure(
            "radicale_unit_write_failed",
            "The Radicale systemd unit could not be created.",
        )
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
    return RadicaleUnitProvisionResult(True, True, ())


def activate_radicale_service(
    config: RadicaleServiceConfig,
    *,
    execute: ServiceCommandExecutor | None = None,
) -> RadicaleServiceResult:
    """Explicitly reload, enable, start, and inspect the Radicale service."""
    issue = _inspect_activation_inputs(config)
    if issue is not None:
        return RadicaleServiceResult(False, False, False, (), (issue,))
    executor = execute or _execute
    commands: list[tuple[str, ...]] = []
    for arguments, code, message in (
        (
            (str(config.systemctl), "daemon-reload"),
            "radicale_reload_failed",
            "systemd could not reload unit definitions.",
        ),
        (
            (str(config.systemctl), "enable", "--now", config.service_name),
            "radicale_activation_failed",
            "The Radicale service could not be enabled and started.",
        ),
    ):
        commands.append(arguments)
        try:
            result = executor(arguments)
        except (OSError, subprocess.SubprocessError):
            result = ServiceCommandResult(1)
        if result.return_code != 0:
            return RadicaleServiceResult(
                False,
                False,
                False,
                tuple(commands),
                (RadicaleServiceIssue(code, message),),
            )
    enabled_command = (
        str(config.systemctl),
        "is-enabled",
        "--quiet",
        config.service_name,
    )
    active_command = (
        str(config.systemctl),
        "is-active",
        "--quiet",
        config.service_name,
    )
    commands.extend((enabled_command, active_command))
    try:
        enabled = executor(enabled_command).return_code == 0
        active = executor(active_command).return_code == 0
    except (OSError, subprocess.SubprocessError):
        enabled = False
        active = False
    if not enabled or not active:
        return RadicaleServiceResult(
            False,
            enabled,
            active,
            tuple(commands),
            (
                RadicaleServiceIssue(
                    "radicale_service_unhealthy",
                    "The Radicale service is not enabled and active.",
                ),
            ),
        )
    return RadicaleServiceResult(True, True, True, tuple(commands), ())


def _unit_failure(code: str, message: str) -> RadicaleUnitProvisionResult:
    return RadicaleUnitProvisionResult(
        False, False, (RadicaleServiceIssue(code, message),)
    )


def _inspect_activation_inputs(
    config: RadicaleServiceConfig,
) -> RadicaleServiceIssue | None:
    for path, code, message in (
        (
            config.executable,
            "radicale_executable_invalid",
            "The exact Radicale executable is unavailable.",
        ),
        (
            config.layout.configuration_file,
            "radicale_configuration_invalid",
            "The exact Radicale configuration is unavailable.",
        ),
        (
            config.unit_file,
            "radicale_unit_invalid",
            "The exact Radicale systemd unit is unavailable.",
        ),
        (
            config.systemctl,
            "radicale_systemctl_invalid",
            "The exact systemctl executable is unavailable.",
        ),
    ):
        if path.is_symlink() or not path.is_file():
            return RadicaleServiceIssue(code, message)
    if not os.access(config.executable, os.X_OK) or not os.access(
        config.systemctl, os.X_OK
    ):
        return RadicaleServiceIssue(
            "radicale_executable_invalid",
            "The required service executables are not executable.",
        )
    return None


def _execute(arguments: tuple[str, ...]) -> ServiceCommandResult:
    environment: Mapping[str, str] = {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    completed = subprocess.run(
        arguments,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=30,
        env=environment,
        cwd=Path("/"),
    )
    return ServiceCommandResult(completed.returncode)
