"""Tests for the LEA application lifecycle."""

import logging

from lea.application import run
from lea.config import AppConfig


def test_run_logs_startup_and_completion(caplog: object) -> None:
    """A successful run should log startup and completion."""
    config = AppConfig(
        environment="test",
        log_level="INFO",
    )

    with caplog.at_level(logging.INFO):  # type: ignore[attr-defined]
        run(config)

    messages = [record.message for record in caplog.records]  # type: ignore[attr-defined]

    assert any(
        "Starting LEA 0.2.1 in test environment." in message for message in messages
    )
    assert "LEA application completed successfully." in messages
