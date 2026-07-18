"""Core application lifecycle for LEA."""

import logging

from lea.config import AppConfig
from lea.version import get_version

LOGGER = logging.getLogger(__name__)


def run(config: AppConfig) -> None:
    """Run the deterministic LEA application lifecycle."""
    version = get_version()

    LOGGER.info(
        "Starting LEA %s in %s environment.",
        version,
        config.environment,
    )

    LOGGER.info("LEA application completed successfully.")
