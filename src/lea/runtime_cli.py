"""Command-line handling for LEA runtime administration."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from lea.runtime import (
    check_runtime_health,
    format_configuration_result,
    format_health_result,
    format_inspection_result,
    inspect_runtime,
    load_runtime_config,
)

EXIT_SUCCESS = 0
EXIT_RUNTIME_ERROR = 1
EXIT_CONFIGURATION_ERROR = 2


def create_runtime_parser() -> argparse.ArgumentParser:
    """Create the runtime-administration argument parser."""
    parser = argparse.ArgumentParser(
        prog="lea runtime",
        description="Inspect and administer the LEA runtime.",
    )

    subparsers = parser.add_subparsers(
        dest="runtime_command",
        required=True,
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect a runtime configuration.",
    )
    _add_config_argument(inspect_parser)
    inspect_parser.add_argument(
        "--health",
        action="store_true",
        help="Include a read-only runtime health check.",
    )

    health_parser = subparsers.add_parser(
        "health",
        help="Run a read-only runtime health check.",
    )
    _add_config_argument(health_parser)

    return parser


def execute_runtime_cli(
    arguments: Sequence[str],
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Execute one runtime-administration command."""
    parser = create_runtime_parser()

    try:
        namespace = parser.parse_args(list(arguments))
    except SystemExit as error:
        return _normalise_argparse_exit(error)

    command = namespace.runtime_command

    if command == "inspect":
        return _execute_inspect(
            config_path=namespace.config,
            include_health=namespace.health,
            stdout=stdout,
        )

    if command == "health":
        return _execute_health(
            config_path=namespace.config,
            stdout=stdout,
            stderr=stderr,
        )

    stderr.write(f"Unsupported runtime command: {command}\n")
    return EXIT_RUNTIME_ERROR


def _execute_inspect(
    *,
    config_path: Path,
    include_health: bool,
    stdout: TextIO,
) -> int:
    """Execute read-only runtime inspection."""
    result = inspect_runtime(
        config_path,
        include_health=include_health,
    )

    stdout.write(format_inspection_result(result))

    if result.success:
        return EXIT_SUCCESS

    if not result.configuration.success:
        return EXIT_CONFIGURATION_ERROR

    return EXIT_RUNTIME_ERROR


def _execute_health(
    *,
    config_path: Path,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Load a configuration and run its health check."""
    configuration = load_runtime_config(config_path)

    if not configuration.success:
        stderr.write(format_configuration_result(configuration))
        return EXIT_CONFIGURATION_ERROR

    config = configuration.config

    if config is None:
        stderr.write(
            "Configuration loading succeeded without a runtime configuration.\n"
        )
        return EXIT_RUNTIME_ERROR

    result = check_runtime_health(config)
    stdout.write(format_health_result(result))

    if result.healthy:
        return EXIT_SUCCESS

    return EXIT_RUNTIME_ERROR


def _add_config_argument(
    parser: argparse.ArgumentParser,
) -> None:
    """Add the required explicit configuration-path argument."""
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        metavar="PATH",
        help="Absolute path to the LEA TOML configuration.",
    )


def _normalise_argparse_exit(
    error: SystemExit,
) -> int:
    """Return an integer argparse exit status."""
    code = error.code

    if isinstance(code, int):
        return code

    return EXIT_RUNTIME_ERROR
