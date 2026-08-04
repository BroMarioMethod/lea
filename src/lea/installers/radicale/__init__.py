"""Separate Radicale CalDAV server deployment boundary."""

from lea.installers.radicale.binary import (
    RadicaleBinaryConfig,
    RadicaleBinaryIssue,
    RadicaleBinaryResult,
    RadicaleInstallationRecord,
    verify_and_register_radicale_binary,
)
from lea.installers.radicale.configuration import (
    canonical_radicale_runtime_layout,
    render_radicale_configuration,
)
from lea.installers.radicale.contracts import (
    RadicaleRuntimeLayout,
    RadicaleServerConfig,
)
from lea.installers.radicale.credentials import (
    RadicaleCredential,
    RadicaleCredentialIssue,
    RadicaleCredentialProvisionResult,
    provision_radicale_users_file,
    render_radicale_users_file,
)
from lea.installers.radicale.health import (
    RadicaleAcceptanceAccount,
    RadicaleHealthIssue,
    RadicaleHealthResult,
    RadicaleIsolationResult,
    RadicaleProbeResponse,
    inspect_radicale_health,
    verify_radicale_user_isolation,
)
from lea.installers.radicale.orchestration import (
    RadicaleInstallerDependencies,
    RadicaleInstallIssue,
    RadicaleInstallRequest,
    RadicaleInstallResult,
    install_radicale,
)
from lea.installers.radicale.provisioning import (
    RadicaleProvisionIssue,
    RadicaleProvisionResult,
    provision_radicale_runtime,
)
from lea.installers.radicale.removal import (
    RadicaleRemovalIssue,
    RadicaleRemovalRequest,
    RadicaleRemovalResult,
    remove_radicale,
)
from lea.installers.radicale.service import (
    RadicaleServiceConfig,
    RadicaleServiceIssue,
    RadicaleServiceResult,
    RadicaleUnitProvisionResult,
    ServiceCommandResult,
    activate_radicale_service,
    provision_radicale_systemd_unit,
    render_radicale_systemd_unit,
)

__all__ = [
    "RadicaleAcceptanceAccount",
    "RadicaleBinaryConfig",
    "RadicaleBinaryIssue",
    "RadicaleBinaryResult",
    "RadicaleCredential",
    "RadicaleCredentialIssue",
    "RadicaleCredentialProvisionResult",
    "RadicaleHealthIssue",
    "RadicaleHealthResult",
    "RadicaleInstallIssue",
    "RadicaleInstallRequest",
    "RadicaleInstallResult",
    "RadicaleInstallationRecord",
    "RadicaleInstallerDependencies",
    "RadicaleIsolationResult",
    "RadicaleProbeResponse",
    "RadicaleProvisionIssue",
    "RadicaleProvisionResult",
    "RadicaleRemovalIssue",
    "RadicaleRemovalRequest",
    "RadicaleRemovalResult",
    "RadicaleRuntimeLayout",
    "RadicaleServerConfig",
    "RadicaleServiceConfig",
    "RadicaleServiceIssue",
    "RadicaleServiceResult",
    "RadicaleUnitProvisionResult",
    "ServiceCommandResult",
    "activate_radicale_service",
    "canonical_radicale_runtime_layout",
    "inspect_radicale_health",
    "install_radicale",
    "provision_radicale_runtime",
    "provision_radicale_systemd_unit",
    "provision_radicale_users_file",
    "remove_radicale",
    "render_radicale_configuration",
    "render_radicale_systemd_unit",
    "render_radicale_users_file",
    "verify_and_register_radicale_binary",
    "verify_radicale_user_isolation",
]
