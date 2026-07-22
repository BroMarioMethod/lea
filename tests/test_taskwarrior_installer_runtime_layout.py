"""Tests for Taskwarrior production runtime layout provisioning."""

from pathlib import Path

from lea.installers.taskwarrior import (
    TaskwarriorInstallerConfig,
    TaskwarriorInstallMode,
    provision_taskwarrior_runtime_layout,
    render_taskwarrior_taskrc,
)


def make_config(tmp_path: Path) -> TaskwarriorInstallerConfig:
    """Return one deterministic installer configuration."""
    return TaskwarriorInstallerConfig(
        mode=TaskwarriorInstallMode.BUNDLED_BINARY,
        version="3.4.2",
        platform="linux-aarch64",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "install" / "taskwarrior.json",
        service_user="lea",
        service_group="lea",
        artefact_path=tmp_path / "source-task",
        expected_sha256="a" * 64,
    )


def test_render_taskrc_is_deterministic() -> None:
    """The managed taskrc should contain only the required baseline."""
    assert render_taskwarrior_taskrc() == (
        "confirmation=no\nhooks=0\nverbose=nothing\n"
    )


def test_provision_runtime_layout_creates_paths(
    tmp_path: Path,
) -> None:
    """Provisioning should create isolated configuration and state paths."""
    config = make_config(tmp_path)

    result = provision_taskwarrior_runtime_layout(config)

    assert result.success is True
    assert result.layout is not None
    assert result.layout.taskrc.read_text(encoding="utf-8") == (
        render_taskwarrior_taskrc()
    )
    assert result.layout.home.is_dir()
    assert result.layout.data.is_dir()
    assert result.layout.taskrc.stat().st_mode & 0o777 == 0o600
    assert result.layout.home.stat().st_mode & 0o777 == 0o700
    assert result.layout.data.stat().st_mode & 0o777 == 0o700


def test_provision_runtime_layout_is_idempotent(
    tmp_path: Path,
) -> None:
    """Repeated provisioning should preserve matching managed state."""
    config = make_config(tmp_path)

    first = provision_taskwarrior_runtime_layout(config)
    second = provision_taskwarrior_runtime_layout(config)

    assert first.success is True
    assert second.success is True
    assert second.layout == first.layout


def test_existing_mismatched_taskrc_is_not_overwritten(
    tmp_path: Path,
) -> None:
    """A differing existing taskrc should fail closed."""
    config = make_config(tmp_path)
    config.configuration_dir.mkdir(parents=True)
    taskrc = config.configuration_dir / "taskrc"
    taskrc.write_text("confirmation=yes\n", encoding="utf-8")

    result = provision_taskwarrior_runtime_layout(config)

    assert result.success is False
    assert result.layout is None
    assert taskrc.read_text(encoding="utf-8") == "confirmation=yes\n"


def test_existing_task_data_is_preserved(
    tmp_path: Path,
) -> None:
    """Provisioning must not delete or modify existing task data."""
    config = make_config(tmp_path)
    data = config.state_root / "data"
    data.mkdir(parents=True)
    sentinel = data / "taskchampion.sqlite3"
    sentinel.write_bytes(b"preserve-existing-data")

    result = provision_taskwarrior_runtime_layout(config)

    assert result.success is True
    assert sentinel.read_bytes() == b"preserve-existing-data"


def test_symlinked_data_directory_is_rejected(
    tmp_path: Path,
) -> None:
    """Managed state directories must not be symbolic links."""
    config = make_config(tmp_path)
    external = tmp_path / "external-data"
    external.mkdir()
    config.state_root.mkdir(parents=True)
    (config.state_root / "data").symlink_to(
        external,
        target_is_directory=True,
    )

    result = provision_taskwarrior_runtime_layout(config)

    assert result.success is False
    assert external.is_dir()
