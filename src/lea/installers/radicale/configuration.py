"""Deterministic Radicale configuration rendering."""

from ipaddress import ip_address
from pathlib import Path

from lea.installers.radicale.contracts import (
    RadicaleRuntimeLayout,
    RadicaleServerConfig,
)


def render_radicale_configuration(config: RadicaleServerConfig) -> str:
    """Render private, authenticated, owner-isolated Radicale configuration."""
    if not isinstance(config, RadicaleServerConfig):
        raise TypeError("config must be a RadicaleServerConfig value.")
    address = ip_address(config.bind_address)
    host = f"[{address}]" if address.version == 6 else str(address)
    layout = config.layout
    return "\n".join(
        (
            "# Managed by LEA. Do not add credentials to this file.",
            "[server]",
            f"hosts = {host}:{config.port}",
            f"max_connections = {config.max_connections}",
            f"max_content_length = {config.max_content_length_bytes}",
            f"timeout = {config.timeout_seconds}",
            "",
            "[auth]",
            "type = htpasswd",
            f"htpasswd_filename = {layout.users_file}",
            "htpasswd_encryption = bcrypt",
            "",
            "[rights]",
            "type = owner_only",
            "",
            "[storage]",
            "type = multifilesystem",
            f"filesystem_folder = {layout.storage_directory}",
            "",
            "[logging]",
            "level = info",
            "mask_passwords = True",
            "",
        )
    )


def canonical_radicale_runtime_layout() -> RadicaleRuntimeLayout:
    """Return the canonical system paths for the Radicale component."""
    return RadicaleRuntimeLayout(
        configuration_directory=Path("/etc/lea/radicale"),
        configuration_file=Path("/etc/lea/radicale/config"),
        secrets_directory=Path("/var/lib/lea/secrets/radicale"),
        users_file=Path("/var/lib/lea/secrets/radicale/users"),
        storage_directory=Path("/var/lib/lea/radicale"),
    )
