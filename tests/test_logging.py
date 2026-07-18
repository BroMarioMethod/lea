"""Tests for LEA logging configuration."""

import logging

from lea.config import AppConfig
from lea.logging import configure_logging


def test_configure_logging_sets_root_level() -> None:
    """Logging should use the configured severity level."""
    configure_logging(
        AppConfig(
            environment="test",
            log_level="DEBUG",
        )
    )

    assert logging.getLogger().level == logging.DEBUG


def test_configure_logging_replaces_existing_handlers() -> None:
    """Repeated configuration should not accumulate handlers."""
    root_logger = logging.getLogger()
    root_logger.addHandler(logging.NullHandler())

    configure_logging(
        AppConfig(
            environment="test",
            log_level="INFO",
        )
    )

    assert len(root_logger.handlers) == 1
    assert isinstance(root_logger.handlers[0], logging.StreamHandler)
