"""Tests for application configuration."""

import pytest

from lea.config import AppConfig, load_config
from lea.errors import ConfigurationError


def test_load_config_uses_defaults() -> None:
    """Configuration should use documented default values."""
    config = load_config({})

    assert config == AppConfig(
        environment="development",
        log_level="INFO",
    )


def test_load_config_normalises_values() -> None:
    """Configuration values should be normalised before validation."""
    config = load_config(
        {
            "LEA_ENV": "  ProDucTion  ",
            "LEA_LOG_LEVEL": "  debug  ",
        }
    )

    assert config.environment == "production"
    assert config.log_level == "DEBUG"


def test_load_config_rejects_invalid_environment() -> None:
    """Unsupported application environments should be rejected."""
    with pytest.raises(
        ConfigurationError,
        match="Unsupported LEA_ENV value",
    ):
        load_config({"LEA_ENV": "staging"})


def test_load_config_rejects_invalid_log_level() -> None:
    """Unsupported log levels should be rejected."""
    with pytest.raises(
        ConfigurationError,
        match="Unsupported LEA_LOG_LEVEL value",
    ):
        load_config({"LEA_LOG_LEVEL": "verbose"})


def test_app_config_is_immutable() -> None:
    """Validated configuration should not be mutable."""
    config = load_config({})

    with pytest.raises(AttributeError):
        config.log_level = "DEBUG"  # type: ignore[misc]
