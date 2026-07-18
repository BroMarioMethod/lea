"""Application configuration loading and validation."""

from collections.abc import Mapping
from dataclasses import dataclass

from lea.errors import ConfigurationError

DEFAULT_ENVIRONMENT = "development"
DEFAULT_LOG_LEVEL = "INFO"

SUPPORTED_ENVIRONMENTS = frozenset(
    {
        "development",
        "test",
        "production",
    }
)

SUPPORTED_LOG_LEVELS = frozenset(
    {
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    }
)


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Validated immutable configuration for the LEA application."""

    environment: str
    log_level: str


def load_config(environment: Mapping[str, str]) -> AppConfig:
    """Load and validate application configuration from a mapping."""
    application_environment = (
        environment.get(
            "LEA_ENV",
            DEFAULT_ENVIRONMENT,
        )
        .strip()
        .lower()
    )

    log_level = (
        environment.get(
            "LEA_LOG_LEVEL",
            DEFAULT_LOG_LEVEL,
        )
        .strip()
        .upper()
    )

    if application_environment not in SUPPORTED_ENVIRONMENTS:
        supported = ", ".join(sorted(SUPPORTED_ENVIRONMENTS))
        raise ConfigurationError(
            "Unsupported LEA_ENV value "
            f"'{application_environment}'. Supported values: {supported}."
        )

    if log_level not in SUPPORTED_LOG_LEVELS:
        supported = ", ".join(sorted(SUPPORTED_LOG_LEVELS))
        raise ConfigurationError(
            "Unsupported LEA_LOG_LEVEL value "
            f"'{log_level}'. Supported values: {supported}."
        )

    return AppConfig(
        environment=application_environment,
        log_level=log_level,
    )
