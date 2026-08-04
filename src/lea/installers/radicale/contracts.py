"""Immutable contracts for the separately managed Radicale boundary."""

from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RadicaleRuntimeLayout:
    """Canonical Radicale configuration, secret, and data paths."""

    configuration_directory: Path
    configuration_file: Path
    secrets_directory: Path
    users_file: Path
    storage_directory: Path

    def __post_init__(self) -> None:
        """Require exact separation of public configuration and secrets."""
        for name, value in (
            ("configuration_directory", self.configuration_directory),
            ("configuration_file", self.configuration_file),
            ("secrets_directory", self.secrets_directory),
            ("users_file", self.users_file),
            ("storage_directory", self.storage_directory),
        ):
            if not isinstance(value, Path) or not value.is_absolute():
                raise ValueError(f"{name} must be an absolute path.")
        if self.configuration_file.parent != self.configuration_directory:
            raise ValueError(
                "configuration_file must be inside configuration_directory."
            )
        if self.users_file.parent != self.secrets_directory:
            raise ValueError("users_file must be inside secrets_directory.")
        if self.secrets_directory == self.configuration_directory:
            raise ValueError("Radicale secrets must be separate from configuration.")


@dataclass(frozen=True, slots=True)
class RadicaleServerConfig:
    """Security-sensitive inputs for one private Radicale server."""

    layout: RadicaleRuntimeLayout
    bind_address: str
    port: int = 5232
    max_connections: int = 20
    max_content_length_bytes: int = 100_000_000
    timeout_seconds: int = 30

    def __post_init__(self) -> None:
        """Reject wildcard and public exposure at the configuration boundary."""
        if not isinstance(self.layout, RadicaleRuntimeLayout):
            raise TypeError("layout must be a RadicaleRuntimeLayout value.")
        try:
            address = ip_address(self.bind_address)
        except ValueError as error:
            raise ValueError("bind_address must be one explicit IP address.") from error
        if address.is_unspecified or address.is_multicast:
            raise ValueError(
                "bind_address must not expose a wildcard or multicast socket."
            )
        if not (address.is_private or address.is_loopback):
            raise ValueError("bind_address must be a private-LAN or loopback address.")
        if isinstance(self.port, bool) or not 1 <= self.port <= 65_535:
            raise ValueError("port must be an integer from 1 through 65535.")
        for name, value in (
            ("max_connections", self.max_connections),
            ("max_content_length_bytes", self.max_content_length_bytes),
            ("timeout_seconds", self.timeout_seconds),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer.")
