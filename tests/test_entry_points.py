"""Subprocess tests for LEA command entry points."""

import os
import subprocess
import sys
from collections.abc import Mapping


def run_command(
    command: list[str],
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a LEA command in a controlled subprocess."""
    process_environment = os.environ.copy()

    if environment is not None:
        process_environment.update(environment)

    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=process_environment,
    )


def test_console_script_returns_success() -> None:
    """The installed lea command should exit successfully."""
    result = run_command(["uv", "run", "lea"])

    assert result.returncode == 0
    assert "Starting LEA" in result.stderr
    assert "completed successfully" in result.stderr


def test_module_execution_returns_success() -> None:
    """python -m lea should use the same successful entry point."""
    result = run_command(["uv", "run", sys.executable, "-m", "lea"])

    assert result.returncode == 0
    assert "Starting LEA" in result.stderr
    assert "completed successfully" in result.stderr


def test_console_script_returns_configuration_error() -> None:
    """Invalid configuration should return exit status two."""
    result = run_command(
        ["uv", "run", "lea"],
        {
            "LEA_LOG_LEVEL": "VERBOSE",
        },
    )

    assert result.returncode == 2
    assert "Unsupported LEA_LOG_LEVEL value" in result.stderr


def test_module_execution_returns_configuration_error() -> None:
    """Module execution should preserve configuration exit status."""
    result = run_command(
        ["uv", "run", sys.executable, "-m", "lea"],
        {
            "LEA_ENV": "invalid",
        },
    )

    assert result.returncode == 2
    assert "Unsupported LEA_ENV value" in result.stderr


def test_acceptance_console_help_returns_success() -> None:
    """The installed lea command should expose acceptance help."""
    result = run_command(
        [
            "uv",
            "run",
            "lea",
            "accept-release-candidate",
            "--help",
        ]
    )

    assert result.returncode == 0
    assert "usage: lea accept-release-candidate" in result.stdout
    assert "--telegram" in result.stdout
    assert "--no-telegram" in result.stdout
    assert result.stderr == ""


def test_acceptance_module_help_returns_success() -> None:
    """python -m lea should expose the same acceptance help."""
    result = run_command(
        [
            "uv",
            "run",
            sys.executable,
            "-m",
            "lea",
            "accept-release-candidate",
            "--help",
        ]
    )

    assert result.returncode == 0
    assert "usage: lea accept-release-candidate" in result.stdout
    assert "--telegram" in result.stdout
    assert "--no-telegram" in result.stdout
    assert result.stderr == ""


def test_acceptance_console_requires_telegram_selection() -> None:
    """Acceptance should reject an omitted Telegram selection safely."""
    result = run_command(
        [
            "uv",
            "run",
            "lea",
            "accept-release-candidate",
        ]
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "--telegram --no-telegram" in result.stderr


def test_acceptance_module_rejects_relative_state_root() -> None:
    """Module execution should preserve acceptance input validation."""
    result = run_command(
        [
            "uv",
            "run",
            sys.executable,
            "-m",
            "lea",
            "accept-release-candidate",
            "--no-telegram",
            "--state-root",
            "relative/state",
        ]
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "state_root must be absolute" in result.stderr


def test_uninstall_console_help_returns_success() -> None:
    """The installed lea command should expose uninstall help."""
    result = run_command(
        [
            "uv",
            "run",
            "lea",
            "uninstall-release-candidate",
            "--help",
        ]
    )

    assert result.returncode == 0
    assert "usage: lea uninstall-release-candidate" in result.stdout
    assert "--purge" in result.stdout
    assert "--yes" in result.stdout
    assert result.stderr == ""


def test_uninstall_module_requires_purge() -> None:
    """Module execution should require explicit destructive intent."""
    result = run_command(
        [
            "uv",
            "run",
            sys.executable,
            "-m",
            "lea",
            "uninstall-release-candidate",
        ]
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "--purge" in result.stderr
