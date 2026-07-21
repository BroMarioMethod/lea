"""Read-only runtime configuration inspection for LEA."""

from pathlib import Path

from lea.runtime.contracts import RuntimeInspectionResult
from lea.runtime.health import check_runtime_health
from lea.runtime.loader import load_runtime_config


def inspect_runtime(
    source_path: str | Path,
    *,
    include_health: bool = False,
) -> RuntimeInspectionResult:
    """Load and optionally health-check one runtime configuration."""
    configuration = load_runtime_config(source_path)

    if not configuration.success:
        return RuntimeInspectionResult(
            success=False,
            configuration=configuration,
            health=None,
        )

    config = configuration.config

    if config is None:
        raise RuntimeError(
            "Successful configuration loading returned no runtime configuration."
        )

    if not include_health:
        return RuntimeInspectionResult(
            success=True,
            configuration=configuration,
            health=None,
        )

    health = check_runtime_health(config)

    return RuntimeInspectionResult(
        success=health.healthy,
        configuration=configuration,
        health=health,
    )
