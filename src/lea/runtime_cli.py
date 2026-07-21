"""Command-line handling for LEA runtime administration."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from lea.runtime import (
    RuntimeConfig,
    RuntimeProfile,
    bootstrap_runtime,
    check_runtime_health,
    development_runtime_config,
    format_bootstrap_result,
    format_configuration_result,
    format_health_result,
    format_initialisation_result,
    format_inspection_result,
    format_setup_result,
    format_setup_verification_result,
    initialise_runtime_config,
    inspect_runtime,
    isolated_test_runtime_config,
    load_runtime_config,
    setup_and_verify_runtime,
    setup_runtime,
    system_runtime_config,
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

    initialise_parser = subparsers.add_parser(
        "initialise",
        help="Create a canonical runtime configuration.",
    )
    _add_template_arguments(initialise_parser)
    _add_dry_run_argument(initialise_parser)

    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help="Create missing configured runtime directories.",
    )
    _add_config_argument(bootstrap_parser)
    _add_dry_run_argument(bootstrap_parser)

    setup_parser = subparsers.add_parser(
        "setup",
        help="Create configuration and runtime directories.",
    )
    _add_template_arguments(setup_parser)
    _add_dry_run_argument(setup_parser)

    verify_parser = subparsers.add_parser(
        "verify",
        help="Set up and verify a runtime.",
    )
    _add_template_arguments(verify_parser)
    _add_dry_run_argument(verify_parser)

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

    if command == "initialise":
        return _execute_initialise(
            namespace,
            stdout=stdout,
            stderr=stderr,
        )

    if command == "bootstrap":
        return _execute_bootstrap(
            config_path=namespace.config,
            dry_run=namespace.dry_run,
            stdout=stdout,
            stderr=stderr,
        )

    if command == "setup":
        return _execute_setup(
            namespace,
            stdout=stdout,
            stderr=stderr,
        )

    if command == "verify":
        return _execute_verify(
            namespace,
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


def _execute_initialise(
    namespace: argparse.Namespace,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Create one canonical configuration safely."""
    config = _build_template_or_report(
        namespace,
        stderr=stderr,
    )

    if config is None:
        return EXIT_CONFIGURATION_ERROR

    result = initialise_runtime_config(
        config,
        dry_run=namespace.dry_run,
    )
    stdout.write(format_initialisation_result(result))

    if result.success:
        return EXIT_SUCCESS

    return EXIT_RUNTIME_ERROR


def _execute_bootstrap(
    *,
    config_path: Path,
    dry_run: bool,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Bootstrap directories from an existing configuration."""
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

    result = bootstrap_runtime(
        config.paths,
        dry_run=dry_run,
    )
    stdout.write(format_bootstrap_result(result))

    if result.success:
        return EXIT_SUCCESS

    return EXIT_RUNTIME_ERROR


def _execute_setup(
    namespace: argparse.Namespace,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Create a canonical configuration and runtime directories."""
    config = _build_template_or_report(
        namespace,
        stderr=stderr,
    )

    if config is None:
        return EXIT_CONFIGURATION_ERROR

    result = setup_runtime(
        config,
        dry_run=namespace.dry_run,
    )
    stdout.write(format_setup_result(result))

    if result.success:
        return EXIT_SUCCESS

    return EXIT_RUNTIME_ERROR


def _execute_verify(
    namespace: argparse.Namespace,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Set up a canonical runtime and verify its health."""
    config = _build_template_or_report(
        namespace,
        stderr=stderr,
    )

    if config is None:
        return EXIT_CONFIGURATION_ERROR

    result = setup_and_verify_runtime(
        config,
        dry_run=namespace.dry_run,
    )
    stdout.write(format_setup_verification_result(result))

    if result.dry_run:
        if result.setup.success:
            return EXIT_SUCCESS

        return EXIT_RUNTIME_ERROR

    if result.verified:
        return EXIT_SUCCESS

    return EXIT_RUNTIME_ERROR


def _build_template_or_report(
    namespace: argparse.Namespace,
    *,
    stderr: TextIO,
) -> RuntimeConfig | None:
    """Build a canonical template or report invalid CLI input."""
    try:
        return _build_template(namespace)
    except (TypeError, ValueError) as error:
        stderr.write(f"Invalid runtime configuration: {error}\n")
        return None


def _build_template(
    namespace: argparse.Namespace,
) -> RuntimeConfig:
    """Build one canonical profile configuration."""
    profile = RuntimeProfile(namespace.profile)
    root: Path | None = namespace.root
    display_timezone: str = namespace.display_timezone
    telegram_token_file: Path | None = namespace.telegram_token_file

    if profile is RuntimeProfile.SYSTEM:
        if root is not None:
            raise ValueError("--root must not be supplied for the system profile.")

        return system_runtime_config(
            display_timezone=display_timezone,
            telegram_token_file=telegram_token_file,
        )

    if root is None:
        raise ValueError("--root is required for development and test profiles.")

    if profile is RuntimeProfile.DEVELOPMENT:
        return development_runtime_config(
            root,
            display_timezone=display_timezone,
            telegram_token_file=telegram_token_file,
        )

    return isolated_test_runtime_config(
        root,
        display_timezone=display_timezone,
        telegram_token_file=telegram_token_file,
    )


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


def _add_template_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    """Add canonical profile-template arguments."""
    parser.add_argument(
        "--profile",
        required=True,
        choices=tuple(profile.value for profile in RuntimeProfile),
        help="Canonical runtime profile.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        metavar="PATH",
        help=(
            "Absolute layout root for development or test profiles. "
            "Not valid for the system profile."
        ),
    )
    parser.add_argument(
        "--display-timezone",
        default="UTC",
        metavar="ZONE",
        help="IANA timezone used for human-readable presentation.",
    )
    parser.add_argument(
        "--telegram-token-file",
        type=Path,
        metavar="PATH",
        help="Optional absolute Telegram token-file reference.",
    )


def _add_dry_run_argument(
    parser: argparse.ArgumentParser,
) -> None:
    """Add a common dry-run option."""
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report planned changes without mutating the runtime.",
    )


def _normalise_argparse_exit(
    error: SystemExit,
) -> int:
    """Return an integer argparse exit status."""
    code = error.code

    if isinstance(code, int):
        return code

    return EXIT_RUNTIME_ERROR
