"""Tests for the independent Radicale systemd lifecycle boundary."""

import os
from pathlib import Path

from lea.installers.radicale import (
    RadicaleRuntimeLayout,
    RadicaleServiceConfig,
    ServiceCommandResult,
    activate_radicale_service,
    provision_radicale_systemd_unit,
    render_radicale_systemd_unit,
)


def _service(tmp_path: Path) -> RadicaleServiceConfig:
    runtime = tmp_path / "runtime"
    configuration = runtime / "configuration"
    secrets = runtime / "secrets"
    storage = runtime / "storage"
    units = runtime / "systemd"
    tools = runtime / "tools"
    for path in (configuration, secrets, storage, units, tools):
        path.mkdir(parents=True)
    executable = tools / "radicale"
    systemctl = tools / "systemctl"
    executable.write_text("binary", encoding="utf-8")
    systemctl.write_text("binary", encoding="utf-8")
    os.chmod(executable, 0o750)
    os.chmod(systemctl, 0o750)
    config_file = configuration / "config"
    config_file.write_text("[server]\n", encoding="utf-8")
    return RadicaleServiceConfig(
        executable=executable,
        layout=RadicaleRuntimeLayout(
            configuration,
            config_file,
            secrets,
            secrets / "users",
            storage,
        ),
        unit_file=units / "lea-radicale.service",
        systemctl=systemctl,
    )


def test_unit_uses_exact_paths_and_hardens_the_service(tmp_path: Path) -> None:
    config = _service(tmp_path)
    rendered = render_radicale_systemd_unit(config)

    assert (
        f"ExecStart={config.executable} --config {config.layout.configuration_file}"
        in rendered
    )
    assert "NoNewPrivileges=true" in rendered
    assert "ProtectSystem=strict" in rendered
    assert f"ReadOnlyPaths={config.layout.secrets_directory}" in rendered
    assert f"ReadWritePaths={config.layout.storage_directory}" in rendered
    assert "0.0.0.0" not in rendered


def test_unit_provisioning_is_idempotent_and_does_not_activate(tmp_path: Path) -> None:
    config = _service(tmp_path)

    created = provision_radicale_systemd_unit(config)
    repeated = provision_radicale_systemd_unit(config)

    assert created.success is True
    assert created.changed is True
    assert repeated.success is True
    assert repeated.changed is False
    assert config.unit_file.stat().st_mode & 0o777 == 0o644


def test_unit_provisioning_preserves_drift(tmp_path: Path) -> None:
    config = _service(tmp_path)
    config.unit_file.write_text("custom", encoding="utf-8")

    result = provision_radicale_systemd_unit(config)

    assert result.success is False
    assert result.issues[0].code == "radicale_unit_mismatch"
    assert config.unit_file.read_text(encoding="utf-8") == "custom"


def test_activation_is_explicit_and_verifies_enabled_active_state(
    tmp_path: Path,
) -> None:
    config = _service(tmp_path)
    assert provision_radicale_systemd_unit(config).success is True
    recorded: list[tuple[str, ...]] = []

    def execute(arguments: tuple[str, ...]) -> ServiceCommandResult:
        recorded.append(arguments)
        return ServiceCommandResult(0)

    result = activate_radicale_service(config, execute=execute)

    assert result.success is True
    assert result.enabled is True
    assert result.active is True
    assert recorded == [
        (str(config.systemctl), "daemon-reload"),
        (str(config.systemctl), "enable", "--now", config.service_name),
        (str(config.systemctl), "is-enabled", "--quiet", config.service_name),
        (str(config.systemctl), "is-active", "--quiet", config.service_name),
    ]


def test_activation_fails_closed_before_systemctl_when_unit_is_missing(
    tmp_path: Path,
) -> None:
    config = _service(tmp_path)
    invoked = False

    def execute(_arguments: tuple[str, ...]) -> ServiceCommandResult:
        nonlocal invoked
        invoked = True
        return ServiceCommandResult(0)

    result = activate_radicale_service(config, execute=execute)

    assert result.success is False
    assert result.issues[0].code == "radicale_unit_invalid"
    assert invoked is False
