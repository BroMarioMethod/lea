"""Errors raised by LEA audit persistence."""

from pathlib import Path


class AuditStoreError(RuntimeError):
    """Structured failure while reading or writing an audit store."""

    def __init__(
        self,
        message: str,
        *,
        path: Path,
        line_number: int | None = None,
    ) -> None:
        """Initialise an audit-store error with location information."""
        self.path = path
        self.line_number = line_number

        location = str(path)

        if line_number is not None:
            location = f"{location}:{line_number}"

        super().__init__(f"{location}: {message}")
