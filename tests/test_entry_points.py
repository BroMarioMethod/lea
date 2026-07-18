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
