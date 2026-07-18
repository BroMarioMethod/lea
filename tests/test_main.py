"""Tests for the public LEA entry point."""

from collections.abc import Mapping

import pytest

from lea.config import AppConfig
from lea.errors import ConfigurationError, LeaError
from lea.main import (
    EXIT_APPLICATION_ERROR,
    EXIT_CONFIGURATION_ERROR,
    EXIT_INTERNAL_ERROR,
    EXIT_SUCCESS,
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
