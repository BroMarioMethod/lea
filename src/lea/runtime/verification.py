"""Runtime setup and health verification orchestration for LEA."""

from lea.runtime.contracts import (
    RuntimeConfig,
    RuntimeSetupVerificationResult,
)
from lea.runtime.health import check_runtime_health
from lea.runtime.setup import setup_runtime


def setup_and_verify_runtime(
    config: RuntimeConfig,
    *,
    dry_run: bool = False,
) -> RuntimeSetupVerificationResult:
    """Set up one runtime and verify its resulting health."""
    setup = setup_runtime(
        config,
        dry_run=dry_run,
    )

    if not setup.success or dry_run:
        return RuntimeSetupVerificationResult(
            verified=False,
            dry_run=dry_run,
            setup=setup,
            health=None,
        )

    health = check_runtime_health(config)

    return RuntimeSetupVerificationResult(
        verified=health.healthy,
        dry_run=False,
        setup=setup,
        health=health,
    )
