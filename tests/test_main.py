"""Tests for the public LEA entry point."""

from collections.abc import Mapping, Sequence
from io import StringIO
from typing import TextIO

import pytest

from lea.config import AppConfig
from lea.errors import ConfigurationError, LeaError
from lea.main import (
    EXIT_APPLICATION_ERROR,
    EXIT_CONFIGURATION_ERROR,
    EXIT_INTERNAL_ERROR,
    EXIT_SUCCESS,
    dispatch,
    execute,
)


def successful_runner(config: AppConfig) -> None:
    """Complete without raising an exception."""
    assert config.environment == "test"


def configuration_failure_runner(config: AppConfig) -> None:
    """Raise an expected configuration failure."""
    raise ConfigurationError("Invalid configuration during startup.")


def application_failure_runner(config: AppConfig) -> None:
    """Raise an expected LEA application failure."""
    raise LeaError("Expected application failure.")


def unexpected_failure_runner(config: AppConfig) -> None:
    """Raise an unexpected internal exception."""
    raise RuntimeError("Unexpected failure.")


def unexpected_application_runner(config: AppConfig) -> None:
    """Fail when application execution was not expected."""
    raise AssertionError("The application runner should not have been called.")


def successful_runtime_runner(
    arguments: Sequence[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Record one successful runtime CLI invocation."""
    assert tuple(arguments) == (
        "inspect",
        "--config",
        "/etc/lea/lea.toml",
    )
    stdout.write("Runtime command completed.\n")
    assert stderr.write("") == 0
    return EXIT_SUCCESS


def failing_runtime_runner(
    arguments: Sequence[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Return one runtime command failure."""
    assert tuple(arguments) == ("health",)
    assert stdout.write("") == 0
    stderr.write("Runtime command failed.\n")
    return EXIT_APPLICATION_ERROR


def successful_release_candidate_runner(
    arguments: Sequence[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Record one successful installer CLI invocation."""
    assert tuple(arguments) == (
        "--mode",
        "repair",
    )
    stdout.write("Installer command completed.\n")
    assert stderr.write("") == 0
    return EXIT_SUCCESS


def successful_local_cli_runner(
    arguments: Sequence[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Record one successful Local CLI invocation."""
    assert tuple(arguments) == ("status",)
    stdout.write("Local CLI completed.\n")
    assert stderr.write("") == 0
    return EXIT_SUCCESS


def successful_release_candidate_acceptance_runner(
    arguments: Sequence[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Record one successful acceptance CLI invocation."""
    assert tuple(arguments) == ("--no-telegram",)
    stdout.write("Acceptance command completed.\n")
    assert stderr.write("") == 0
    return EXIT_SUCCESS


def successful_calendar_provider_runner(
    arguments: Sequence[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Record one supported calendar-provider invocation."""
    assert tuple(arguments) == ("bootstrap", "--approve-first-collection")
    stdout.write("Calendar provider command completed.\n")
    assert stderr.write("") == 0
    return EXIT_SUCCESS


@pytest.fixture
def test_environment() -> Mapping[str, str]:
    """Return valid test configuration."""
    return {
        "LEA_ENV": "test",
        "LEA_LOG_LEVEL": "CRITICAL",
    }


def test_execute_returns_success(
    test_environment: Mapping[str, str],
) -> None:
    """Successful application execution should return zero."""
    assert execute(test_environment, successful_runner) == EXIT_SUCCESS


def test_execute_returns_configuration_error_for_invalid_input() -> None:
    """Invalid configuration should return exit status two."""
    assert execute({"LEA_ENV": "invalid"}) == EXIT_CONFIGURATION_ERROR


def test_execute_returns_configuration_error_for_runtime_failure(
    test_environment: Mapping[str, str],
) -> None:
    """Configuration failures during execution should return status two."""
    assert (
        execute(test_environment, configuration_failure_runner)
        == EXIT_CONFIGURATION_ERROR
    )


def test_execute_returns_application_error(
    test_environment: Mapping[str, str],
) -> None:
    """Expected LEA failures should return status one."""
    assert (
        execute(test_environment, application_failure_runner) == EXIT_APPLICATION_ERROR
    )


def test_execute_returns_internal_error(
    test_environment: Mapping[str, str],
) -> None:
    """Unexpected failures should return software-error status."""
    assert execute(test_environment, unexpected_failure_runner) == EXIT_INTERNAL_ERROR


def test_dispatch_without_arguments_runs_application(
    test_environment: Mapping[str, str],
) -> None:
    """No command arguments should preserve application startup."""
    exit_code = dispatch(
        [],
        test_environment,
        application_runner=successful_runner,
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert exit_code == EXIT_SUCCESS


def test_dispatch_calendar_provider_uses_supported_public_cli(
    test_environment: Mapping[str, str],
) -> None:
    stdout = StringIO()
    exit_code = dispatch(
        ["calendar-provider", "bootstrap", "--approve-first-collection"],
        test_environment,
        application_runner=unexpected_application_runner,
        calendar_provider_cli_runner=successful_calendar_provider_runner,
        stdout=stdout,
        stderr=StringIO(),
    )
    assert exit_code == EXIT_SUCCESS
    assert stdout.getvalue() == "Calendar provider command completed.\n"


def test_dispatch_runtime_command_uses_runtime_cli(
    test_environment: Mapping[str, str],
) -> None:
    """Runtime arguments should be routed without the prefix."""
    stdout = StringIO()
    stderr = StringIO()

    exit_code = dispatch(
        [
            "runtime",
            "inspect",
            "--config",
            "/etc/lea/lea.toml",
        ],
        test_environment,
        application_runner=unexpected_application_runner,
        runtime_cli_runner=successful_runtime_runner,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == EXIT_SUCCESS
    assert stdout.getvalue() == "Runtime command completed.\n"
    assert stderr.getvalue() == ""


def test_dispatch_preserves_runtime_exit_code(
    test_environment: Mapping[str, str],
) -> None:
    """Runtime command failures should preserve their exit status."""
    stdout = StringIO()
    stderr = StringIO()

    exit_code = dispatch(
        [
            "runtime",
            "health",
        ],
        test_environment,
        application_runner=unexpected_application_runner,
        runtime_cli_runner=failing_runtime_runner,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == EXIT_APPLICATION_ERROR
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "Runtime command failed.\n"


def test_dispatch_runtime_does_not_require_application_config() -> None:
    """Runtime commands should not load legacy application settings."""
    exit_code = dispatch(
        [
            "runtime",
            "inspect",
            "--config",
            "/etc/lea/lea.toml",
        ],
        {},
        application_runner=unexpected_application_runner,
        runtime_cli_runner=successful_runtime_runner,
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert exit_code == EXIT_SUCCESS


def test_dispatch_release_candidate_command_uses_installer_boundary() -> None:
    """Installer arguments should avoid legacy application startup."""
    stdout = StringIO()
    stderr = StringIO()

    exit_code = dispatch(
        [
            "install-release-candidate",
            "--mode",
            "repair",
        ],
        {},
        application_runner=unexpected_application_runner,
        release_candidate_cli_runner=successful_release_candidate_runner,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == EXIT_SUCCESS
    assert stdout.getvalue() == "Installer command completed.\n"
    assert stderr.getvalue() == ""


def test_dispatch_local_cli_command_uses_local_boundary() -> None:
    """Recognised Local CLI commands should avoid legacy application startup."""
    stdout = StringIO()
    stderr = StringIO()

    exit_code = dispatch(
        ["status"],
        {},
        application_runner=unexpected_application_runner,
        local_cli_runner=successful_local_cli_runner,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == EXIT_SUCCESS
    assert stdout.getvalue() == "Local CLI completed.\n"
    assert stderr.getvalue() == ""


@pytest.mark.parametrize(
    "expected_arguments",
    [
        ["--help"],
        ["-h"],
        ["--json", "status"],
        ["--config", "/opt/lea/.lea/config/lea.toml", "status"],
        [
            "--profile",
            "development",
            "--config",
            "/opt/lea/.lea/config/lea.toml",
            "status",
        ],
        ["--no-colour", "task", "list"],
        ["task", "list"],
        ["proposal", "list"],
    ],
)
def test_dispatch_recognises_local_cli_argument_paths(
    expected_arguments: list[str],
) -> None:
    """Local CLI roots and global options should route consistently."""
    called = False

    def local_runner(
        arguments: Sequence[str],
        *,
        stdout: TextIO,
        stderr: TextIO,
    ) -> int:
        nonlocal called
        called = True
        assert tuple(arguments) == tuple(expected_arguments)
        assert stdout.write("") == 0
        assert stderr.write("") == 0
        return EXIT_SUCCESS

    exit_code = dispatch(
        expected_arguments,
        {},
        application_runner=unexpected_application_runner,
        local_cli_runner=local_runner,
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert exit_code == EXIT_SUCCESS
    assert called is True


def test_non_runtime_arguments_preserve_existing_application_path(
    test_environment: Mapping[str, str],
) -> None:
    """Unknown top-level arguments should preserve prior behaviour."""
    exit_code = dispatch(
        ["unexpected"],
        test_environment,
        application_runner=successful_runner,
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert exit_code == EXIT_SUCCESS


def test_dispatch_acceptance_command_uses_acceptance_boundary() -> None:
    """Acceptance arguments should avoid legacy application startup."""
    stdout = StringIO()
    stderr = StringIO()

    exit_code = dispatch(
        [
            "accept-release-candidate",
            "--no-telegram",
        ],
        {},
        application_runner=unexpected_application_runner,
        release_candidate_acceptance_cli_runner=(
            successful_release_candidate_acceptance_runner
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == EXIT_SUCCESS
    assert stdout.getvalue() == "Acceptance command completed.\n"
    assert stderr.getvalue() == ""


def test_dispatch_preserves_acceptance_exit_code() -> None:
    """Acceptance failures should preserve their exit status."""

    def failing_acceptance_runner(
        arguments: Sequence[str],
        *,
        stdout: TextIO,
        stderr: TextIO,
    ) -> int:
        assert tuple(arguments) == ("--telegram",)
        stdout.write("Acceptance checks failed.\n")
        assert stderr.write("") == 0
        return EXIT_APPLICATION_ERROR

    stdout = StringIO()
    stderr = StringIO()

    exit_code = dispatch(
        [
            "accept-release-candidate",
            "--telegram",
        ],
        {},
        application_runner=unexpected_application_runner,
        release_candidate_acceptance_cli_runner=failing_acceptance_runner,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == EXIT_APPLICATION_ERROR
    assert stdout.getvalue() == "Acceptance checks failed.\n"
    assert stderr.getvalue() == ""


def test_dispatch_uninstall_command_uses_uninstall_boundary() -> None:
    """Uninstall arguments should avoid legacy application startup."""
    stdout = StringIO()
    stderr = StringIO()

    def successful_uninstall_runner(
        arguments: Sequence[str],
        *,
        stdout: TextIO,
        stderr: TextIO,
    ) -> int:
        assert tuple(arguments) == ("--purge", "--yes")
        stdout.write("Uninstall command completed.\n")
        assert stderr.write("") == 0
        return EXIT_SUCCESS

    exit_code = dispatch(
        [
            "uninstall-release-candidate",
            "--purge",
            "--yes",
        ],
        {},
        application_runner=unexpected_application_runner,
        release_candidate_uninstall_cli_runner=(successful_uninstall_runner),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == EXIT_SUCCESS
    assert stdout.getvalue() == "Uninstall command completed.\n"
    assert stderr.getvalue() == ""


def test_dispatch_android_acceptance_uses_acceptance_boundary() -> None:
    """Android acceptance arguments should avoid application startup."""
    stdout = StringIO()
    stderr = StringIO()

    def successful_calendar_acceptance_runner(
        arguments: Sequence[str],
        *,
        stdout: TextIO,
        stderr: TextIO,
    ) -> int:
        assert tuple(arguments) == ("--backup-verified",)
        stdout.write("Calendar acceptance completed.\n")
        assert stderr.write("") == 0
        return EXIT_SUCCESS

    exit_code = dispatch(
        ["accept-calendar-android", "--backup-verified"],
        {},
        application_runner=unexpected_application_runner,
        calendar_acceptance_cli_runner=successful_calendar_acceptance_runner,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == EXIT_SUCCESS
    assert stdout.getvalue() == "Calendar acceptance completed.\n"
    assert stderr.getvalue() == ""
