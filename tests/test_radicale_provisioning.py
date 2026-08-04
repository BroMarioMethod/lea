"""Tests for fail-closed Radicale runtime provisioning."""

from pathlib import Path

from lea.installers.radicale import (
    RadicaleRuntimeLayout,
    RadicaleServerConfig,
    provision_radicale_runtime,
    render_radicale_configuration,
)


def _config(tmp_path: Path) -> RadicaleServerConfig:
    configuration_parent = tmp_path / "etc" / "lea"
    secrets_parent = tmp_path / "var" / "lib" / "lea" / "secrets"
    state_parent = tmp_path / "var" / "lib" / "lea"
    configuration_parent.mkdir(parents=True)
    secrets_parent.mkdir(parents=True)
    return RadicaleServerConfig(
        layout=RadicaleRuntimeLayout(
            configuration_directory=configuration_parent / "radicale",
            configuration_file=configuration_parent / "radicale" / "config",
            secrets_directory=secrets_parent / "radicale",
            users_file=secrets_parent / "radicale" / "users",
            storage_directory=state_parent / "radicale",
        ),
        bind_address="127.0.0.1",
    )


def test_runtime_provisioning_is_exact_restrictive_and_idempotent(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)

    created = provision_radicale_runtime(config)
    repeated = provision_radicale_runtime(config)

    assert created.success is True
    assert created.changed_paths == (
        config.layout.configuration_directory,
        config.layout.secrets_directory,
        config.layout.storage_directory,
        config.layout.configuration_file,
    )
    assert repeated.success is True
    assert repeated.changed_paths == ()
    assert config.layout.configuration_directory.stat().st_mode & 0o777 == 0o750
    assert config.layout.secrets_directory.stat().st_mode & 0o777 == 0o700
    assert config.layout.storage_directory.stat().st_mode & 0o777 == 0o750
    assert config.layout.configuration_file.stat().st_mode & 0o777 == 0o640
    assert (
        config.layout.configuration_file.read_text()
        == render_radicale_configuration(config)
    )


def test_runtime_provisioning_preserves_configuration_drift(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert provision_radicale_runtime(config).success is True
    config.layout.configuration_file.write_text("unexpected", encoding="utf-8")

    result = provision_radicale_runtime(config)

    assert result.success is False
    assert result.issues[0].code == "radicale_configuration_mismatch"
    assert config.layout.configuration_file.read_text(encoding="utf-8") == "unexpected"


def test_runtime_provisioning_rejects_symlinked_directory(tmp_path: Path) -> None:
    config = _config(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    config.layout.configuration_directory.symlink_to(target, target_is_directory=True)

    result = provision_radicale_runtime(config)

    assert result.success is False
    assert result.issues[0].code == "radicale_directory_invalid"
    assert not config.layout.configuration_file.exists()


def test_runtime_provisioning_does_not_start_external_processes(tmp_path: Path) -> None:
    config = _config(tmp_path)

    result = provision_radicale_runtime(config)

    assert result.success is True
    assert not any(path.name.endswith(".service") for path in result.changed_paths)
