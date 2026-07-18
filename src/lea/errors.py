"""Application-specific exceptions for LEA."""


class LeaError(Exception):
    """Base exception for expected LEA application failures."""


class ConfigurationError(LeaError):
    """Raised when application configuration is invalid."""
