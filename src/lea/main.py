"""Public command-line entry point for LEA."""

import logging
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol, TextIO

from lea.application import run
from lea.config import AppConfig, load_config
from lea.errors import ConfigurationError, LeaError
from lea.logging import configure_logging
from lea.runtime_cli import execute_runtime_cli

EXIT_SUCCESS = 0
EXIT_APPLICATION_ERROR = 1
EXIT_CONFIGURATION_ERROR = 2
EXIT_INTERNAL_ERROR = 70

LOGGER = logging.getLogger(__name__)

ApplicationRunner = Callable[[AppConfig], None]


class RuntimeCliRunner(Protocol):
    """Callable boundary for runtime CLI execution."""

    def __call__(
        self,
        arguments: Sequence[str],
        *,
        stdout: TextIO,
        stderr: TextIO,
    ) -> int:
        """Execute runtime CLI arguments."""
        ...


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


def dispatch(
    arguments: Sequence[str],
    environment: Mapping[str, str],
    *,
    application_runner: ApplicationRunner = run,
    runtime_cli_runner: RuntimeCliRunner = execute_runtime_cli,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Dispatch process arguments to the selected LEA interface."""
    if arguments and arguments[0] == "runtime":
        return runtime_cli_runner(
            arguments[1:],
            stdout=stdout,
            stderr=stderr,
        )

    return execute(
        environment,
        application_runner,
    )


def main() -> int:
    """Run LEA using current process arguments and environment."""
    return dispatch(
        sys.argv[1:],
        os.environ,
    )
