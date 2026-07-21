"""Coordinated deterministic runtime setup for LEA."""

from lea.runtime.bootstrap import bootstrap_runtime
from lea.runtime.contracts import (
    RuntimeConfig,
    RuntimeSetupResult,
)
from lea.runtime.initialisation import initialise_runtime_config


def setup_runtime(
    config: RuntimeConfig,
    *,
    dry_run: bool = False,
) -> RuntimeSetupResult:
    """Initialise configuration and bootstrap runtime directories."""
    initialisation = initialise_runtime_config(
        config,
        dry_run=dry_run,
    )

    if not initialisation.success:
        return RuntimeSetupResult(
            success=False,
            dry_run=dry_run,
            initialisation=initialisation,
            bootstrap=None,
        )

    bootstrap = bootstrap_runtime(
        config.paths,
        dry_run=dry_run,
    )

    return RuntimeSetupResult(
        success=bootstrap.success,
        dry_run=dry_run,
        initialisation=initialisation,
        bootstrap=bootstrap,
    )
