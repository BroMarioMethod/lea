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
from lea.installers.radicale.provisioning import (
    RadicaleProvisionIssue,
    RadicaleProvisionResult,
    provision_radicale_runtime,
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
    "RadicaleInstallationRecord",
    "RadicaleIsolationResult",
    "RadicaleProbeResponse",
    "RadicaleProvisionIssue",
    "RadicaleProvisionResult",
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
    "provision_radicale_runtime",
    "provision_radicale_systemd_unit",
    "provision_radicale_users_file",
    "render_radicale_configuration",
    "render_radicale_systemd_unit",
    "render_radicale_users_file",
    "verify_and_register_radicale_binary",
    "verify_radicale_user_isolation",
]
