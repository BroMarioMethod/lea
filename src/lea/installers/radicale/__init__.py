"""Separate Radicale CalDAV server deployment boundary."""

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
    "RadicaleCredential",
    "RadicaleCredentialIssue",
    "RadicaleCredentialProvisionResult",
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
    "provision_radicale_runtime",
    "provision_radicale_systemd_unit",
    "provision_radicale_users_file",
    "render_radicale_configuration",
    "render_radicale_systemd_unit",
    "render_radicale_users_file",
]
