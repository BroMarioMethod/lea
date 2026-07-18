"""Public command-line entry point for LEA."""

import logging
import os
from collections.abc import Callable, Mapping

from lea.application import run
from lea.config import AppConfig, load_config
from lea.errors import ConfigurationError, LeaError
from lea.logging import configure_logging

EXIT_SUCCESS = 0
EXIT_APPLICATION_ERROR = 1
EXIT_CONFIGURATION_ERROR = 2
EXIT_INTERNAL_ERROR = 70

LOGGER = logging.getLogger(__name__)

ApplicationRunner = Callable[[AppConfig], None]


def execute(
    environment: Mapping[str, str],
    application_runner: ApplicationRunner = run,
) -> int:
    """Execute LEA using supplied process inputs and dependencies."""
    try:
        config = load_config(environment)
    except ConfigurationError as error:
        logging.basicConfig(level=logging.ERROR)
        LOGGER.error("%s", error)
        return EXIT_CONFIGURATION_ERROR

    configure_logging(config)

    try:
        application_runner(config)
    except ConfigurationError as error:
        LOGGER.error("%s", error)
        return EXIT_CONFIGURATION_ERROR
    except LeaError as error:
        LOGGER.error("%s", error)
        return EXIT_APPLICATION_ERROR
    except Exception:
        LOGGER.exception("Unexpected internal failure.")
        return EXIT_INTERNAL_ERROR

    return EXIT_SUCCESS


def main() -> int:
    """Run LEA using the current process environment."""
    return execute(os.environ)
