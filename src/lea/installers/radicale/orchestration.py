"""Ordered fail-closed orchestration for the separate Radicale component."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import sleep

from lea.installers.radicale.binary import (
    RadicaleBinaryConfig,
    RadicaleBinaryResult,
    verify_and_register_radicale_binary,
)
from lea.installers.radicale.contracts import RadicaleServerConfig
from lea.installers.radicale.credentials import (
    RadicaleCredential,
    RadicaleCredentialIssue,
    RadicaleCredentialProvisionResult,
    provision_radicale_users_file,
)
from lea.installers.radicale.health import (
    RadicaleAcceptanceAccount,
    RadicaleHealthIssue,
    RadicaleHealthResult,
    RadicaleIsolationResult,
    inspect_radicale_health,
    verify_radicale_user_isolation,
)
from lea.installers.radicale.ownership import apply_radicale_ownership
from lea.installers.radicale.provisioning import (
    RadicaleProvisionResult,
    provision_radicale_runtime,
)
from lea.installers.radicale.service import (
    RadicaleServiceConfig,
    RadicaleServiceResult,
    RadicaleUnitProvisionResult,
    activate_radicale_service,
    provision_radicale_systemd_unit,
)


@dataclass(frozen=True, slots=True)
class RadicaleInstallRequest:
    """All explicit inputs required for one Radicale installation run."""

    binary: RadicaleBinaryConfig
    server: RadicaleServerConfig
    service: RadicaleServiceConfig
    credentials: tuple[RadicaleCredential, ...]
    base_url: str
    activate: bool
    acceptance_accounts: tuple[RadicaleAcceptanceAccount, ...] = ()
    health_attempts: int = 20
    health_retry_delay_seconds: float = 0.25

    def __post_init__(self) -> None:
        if self.service.executable != self.binary.executable:
            raise ValueError("service and binary must use the same exact executable.")
        if self.service.layout != self.server.layout:
            raise ValueError("service and server must use the same runtime layout.")
        if not self.credentials:
            raise ValueError("At least one Radicale credential is required.")
        if self.acceptance_accounts and len(self.acceptance_accounts) != 2:
            raise ValueError("User-isolation acceptance requires exactly two accounts.")
        if self.acceptance_accounts and not self.activate:
            raise ValueError("User-isolation acceptance requires service activation.")
        if isinstance(self.health_attempts, bool) or self.health_attempts < 1:
            raise ValueError("health_attempts must be a positive integer.")
        if (
            isinstance(self.health_retry_delay_seconds, bool)
            or self.health_retry_delay_seconds < 0
        ):
            raise ValueError("health_retry_delay_seconds must not be negative.")


@dataclass(frozen=True, slots=True)
class RadicaleInstallIssue:
    """One redaction-safe installer orchestration problem."""

    stage: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class RadicaleInstallResult:
    """Result of one ordered Radicale installation run."""

    success: bool
    completed_stages: tuple[str, ...]
    activated: bool
    healthy: bool
    isolation_verified: bool
    issues: tuple[RadicaleInstallIssue, ...]


BinaryVerifier = Callable[[RadicaleBinaryConfig, bool], RadicaleBinaryResult]
RuntimeProvisioner = Callable[[RadicaleServerConfig], RadicaleProvisionResult]
CredentialProvisioner = Callable[
    [Path, tuple[RadicaleCredential, ...]], RadicaleCredentialProvisionResult
]
UnitProvisioner = Callable[[RadicaleServiceConfig], RadicaleUnitProvisionResult]
ServiceActivator = Callable[[RadicaleServiceConfig], RadicaleServiceResult]
HealthInspector = Callable[[str], RadicaleHealthResult]
IsolationVerifier = Callable[
    [str, RadicaleAcceptanceAccount, RadicaleAcceptanceAccount],
    RadicaleIsolationResult,
]
Pause = Callable[[float], None]


def _verify_binary(
    config: RadicaleBinaryConfig, register: bool
) -> RadicaleBinaryResult:
    return verify_and_register_radicale_binary(config, register=register)


def _provision_owned_runtime(config: RadicaleServerConfig) -> RadicaleProvisionResult:
    return provision_radicale_runtime(
        config,
        apply_ownership=apply_radicale_ownership,
    )


def _provision_owned_credentials(
    path: Path,
    credentials: tuple[RadicaleCredential, ...],
) -> RadicaleCredentialProvisionResult:
    result = provision_radicale_users_file(path, credentials)
    if not result.success:
        return result
    try:
        apply_radicale_ownership(path, "lea", "lea")
    except (KeyError, OSError):
        return RadicaleCredentialProvisionResult(
            False,
            path,
            len(credentials),
            result.changed,
            (
                *result.issues,
                RadicaleCredentialIssue(
                    "radicale_users_ownership_failed",
                    "Radicale credential ownership could not be applied.",
                    path,
                ),
            ),
        )
    return result


@dataclass(frozen=True, slots=True)
class RadicaleInstallerDependencies:
    """Injected stage boundaries for isolated orchestration tests."""

    verify_binary: BinaryVerifier = _verify_binary
    provision_runtime: RuntimeProvisioner = _provision_owned_runtime
    provision_credentials: CredentialProvisioner = _provision_owned_credentials
    provision_unit: UnitProvisioner = provision_radicale_systemd_unit
    activate_service: ServiceActivator = activate_radicale_service
    inspect_health: HealthInspector = inspect_radicale_health
    verify_isolation: IsolationVerifier = verify_radicale_user_isolation
    pause: Pause = sleep


def install_radicale(
    request: RadicaleInstallRequest,
    *,
    dependencies: RadicaleInstallerDependencies | None = None,
) -> RadicaleInstallResult:
    """Run ordered stages and stop before every downstream side effect on failure."""
    resolved = dependencies or RadicaleInstallerDependencies()
    completed: list[str] = []

    verified = resolved.verify_binary(request.binary, False)
    if not verified.success:
        return _failed("binary.verify", completed, verified.issues)
    completed.append("binary.verify")

    runtime = resolved.provision_runtime(request.server)
    if not runtime.success:
        return _failed("runtime.provision", completed, runtime.issues)
    completed.append("runtime.provision")

    credentials = resolved.provision_credentials(
        request.server.layout.users_file, request.credentials
    )
    if not credentials.success:
        return _failed("credentials.provision", completed, credentials.issues)
    completed.append("credentials.provision")

    unit = resolved.provision_unit(request.service)
    if not unit.success:
        return _failed("service.unit", completed, unit.issues)
    completed.append("service.unit")

    registered = resolved.verify_binary(request.binary, True)
    if not registered.success:
        return _failed("binary.register", completed, registered.issues)
    completed.append("binary.register")

    if not request.activate:
        return RadicaleInstallResult(True, tuple(completed), False, False, False, ())

    service = resolved.activate_service(request.service)
    if not service.success:
        return _failed("service.activate", completed, service.issues)
    completed.append("service.activate")

    health = resolved.inspect_health(request.base_url)
    for _attempt in range(1, request.health_attempts):
        if health.healthy:
            break
        resolved.pause(request.health_retry_delay_seconds)
        health = resolved.inspect_health(request.base_url)
    if not health.healthy:
        issues = health.issues or (
            RadicaleHealthIssue(
                "radicale_health_readiness_timeout",
                "Radicale did not become ready within the bounded health window.",
            ),
        )
        return _failed("service.health", completed, issues, activated=True)
    completed.append("service.health")

    isolation_verified = False
    if request.acceptance_accounts:
        first, second = request.acceptance_accounts
        isolation = resolved.verify_isolation(request.base_url, first, second)
        if not isolation.success:
            return _failed(
                "service.isolation", completed, isolation.issues, activated=True
            )
        completed.append("service.isolation")
        isolation_verified = True
    return RadicaleInstallResult(
        True, tuple(completed), True, True, isolation_verified, ()
    )


def _failed(
    stage: str,
    completed: list[str],
    issues: tuple[object, ...],
    *,
    activated: bool = False,
) -> RadicaleInstallResult:
    mapped = tuple(
        RadicaleInstallIssue(
            stage,
            str(getattr(issue, "code", "radicale_install_failed")),
            str(getattr(issue, "message", "The Radicale installation stage failed.")),
        )
        for issue in issues
    )
    if not mapped:
        mapped = (
            RadicaleInstallIssue(
                stage,
                "radicale_install_failed",
                "The Radicale installation stage failed without a diagnostic.",
            ),
        )
    return RadicaleInstallResult(
        False, tuple(completed), activated, False, False, mapped
    )
