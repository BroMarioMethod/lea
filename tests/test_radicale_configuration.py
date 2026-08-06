"""Tests for deterministic, private Radicale configuration."""

from pathlib import Path

import pytest

from lea.installers.radicale import (
    RadicaleRuntimeLayout,
    RadicaleServerConfig,
    canonical_radicale_runtime_layout,
    render_radicale_configuration,
)


def test_canonical_configuration_separates_secrets_and_private_storage() -> None:
    layout = canonical_radicale_runtime_layout()
    rendered = render_radicale_configuration(
        RadicaleServerConfig(layout=layout, bind_address="192.168.1.20")
    )

    assert "hosts = 192.168.1.20:5232" in rendered
    assert "type = htpasswd" in rendered
    assert "htpasswd_encryption = bcrypt" in rendered
    assert f"htpasswd_filename = {layout.users_file}" in rendered
    assert "type = owner_only" in rendered
    assert f"filesystem_folder = {layout.storage_directory}" in rendered
    assert str(layout.users_file) not in str(layout.configuration_directory)
    assert "password" not in rendered.lower().replace("mask_passwords", "")


@pytest.mark.parametrize(
    "address",
    ["0.0.0.0", "::", "8.8.8.8", "radicale.example.test", "224.0.0.1"],
)
def test_configuration_rejects_uncontrolled_network_exposure(address: str) -> None:
    with pytest.raises(ValueError):
        RadicaleServerConfig(
            layout=canonical_radicale_runtime_layout(),
            bind_address=address,
        )


def test_layout_rejects_secret_file_in_configuration_directory() -> None:
    with pytest.raises(ValueError, match="separate"):
        RadicaleRuntimeLayout(
            configuration_directory=Path("/etc/lea/radicale"),
            configuration_file=Path("/etc/lea/radicale/config"),
            secrets_directory=Path("/etc/lea/radicale"),
            users_file=Path("/etc/lea/radicale/users"),
            storage_directory=Path("/var/lib/lea/radicale/collections"),
        )
