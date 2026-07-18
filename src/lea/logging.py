"""Logging configuration for LEA."""

import logging
from datetime import UTC, datetime

from lea.config import AppConfig

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class UtcFormatter(logging.Formatter):
    """Format log timestamps in UTC with timezone information."""

    converter = staticmethod(
        lambda timestamp: datetime.fromtimestamp(timestamp, UTC).timetuple()
    )


def configure_logging(config: AppConfig) -> None:
    """Configure application logging for the current process."""
    handler = logging.StreamHandler()
    handler.setFormatter(UtcFormatter(LOG_FORMAT))

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(config.log_level)
    root_logger.addHandler(handler)
