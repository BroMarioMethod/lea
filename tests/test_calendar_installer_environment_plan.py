"""Tests for deterministic calendar uv environment plans."""

import hashlib
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from lea.installers.calendar import (
    CalendarToolchainEnvironmentPlan,
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallMode,
    CalendarToolchainStagingLayout,
    create_calendar_toolchain_environment_plan,
    create_calendar_toolchain_staging,
)


def _make_executable(path: Path) -> None:
    """Create one executable test script."""
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _network_config(
    tmp_path: Path,
) -> CalendarToolchainInstallerConfig:
    """Return one managed verified-network configuration."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    uv_executable = tmp_path / "uv"
    python_executable = tmp_path / "python3"
    requirements_lock = tmp_path / "calendar-requirements.txt"
    payload = b"khal==0.11.4\nvdirsyncer==0.19.3\n"

    _make_executable(uv_executable)
    _make_executable(python_executable)
    requirements_lock.write_bytes(payload)

    return CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.VERIFIED_NETWORK,
        toolchain_version="1",
        khal_version="0.11.4",
        vdirsyncer_version="0.19.3",
        platform="linux-aarch64",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "install.json",
        service_user="lea",
        service_group="lea",
        uv_executable=uv_executable,
        python_executable=python_executable,
        requirements_lock=requirements_lock,
        expected_lock_sha256=hashlib.sha256(payload).hexdigest(),
        package_index_url="https://packages.example.invalid/simple",
        timeout_seconds=900.0,
    )


def _bundled_config(
    tmp_path: Path,
) -> CalendarToolchainInstallerConfig:
    """Return one managed bundled-wheelhouse configuration."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    archive = tmp_path / "calendar-wheelhouse.tar.gz"
    payload = b"wheelhouse"
    archive.write_bytes(payload)

    return replace(
        _network_config(tmp_path),
        mode=CalendarToolchainInstallMode.BUNDLED_WHEELHOUSE,
        package_index_url=None,
        wheelhouse_archive=archive,
        expected_wheelhouse_sha256=hashlib.sha256(payload).hexdigest(),
    )


def _external_config(
    tmp_path: Path,
) -> CalendarToolchainInstallerConfig:
    """Return one external-executables configuration."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    khal_executable = tmp_path / "khal"
    vdirsyncer_executable = tmp_path / "vdirsyncer"
    _make_executable(khal_executable)
    _make_executable(vdirsyncer_executable)

    return CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES,
        toolchain_version="external-1",
        khal_version="0.11.4",
        vdirsyncer_version="0.19.3",
        platform="linux-aarch64",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "install.json",
        service_user="lea",
        service_group="lea",
        external_khal_executable=khal_executable,
        external_vdirsyncer_executable=vdirsyncer_executable,
    )


def _stage(
    config: CalendarToolchainInstallerConfig,
) -> CalendarToolchainStagingLayout:
    """Create staging and return its successful layout."""
    result = create_calendar_toolchain_staging(config)
    assert result.staged is not None
    return result.staged


def test_network_plan_uses_exact_non_shell_uv_commands(
    tmp_path: Path,
) -> None:
    """Network mode should use the configured index and locked wheels."""
    config = _network_config(tmp_path)
    staged = _stage(config)

    plan = create_calendar_toolchain_environment_plan(config, staged)

    assert config.uv_executable is not None
    assert config.python_executable is not None
    assert plan.create_environment_command == (
        str(config.uv_executable),
        "--no-config",
        "--no-cache",
        "--no-python-downloads",
        "--no-progress",
        "venv",
        "--no-project",
        "--no-managed-python",
        "--relocatable",
        "--python",
        str(config.python_executable),
        str(staged.environment_root),
    )
    assert plan.install_packages_command == (
        str(config.uv_executable),
        "--no-config",
        "--no-cache",
        "--no-python-downloads",
        "--no-managed-python",
        "--no-progress",
        "pip",
        "sync",
        "--python",
        str(staged.environment_root / "bin" / "python"),
        "--require-hashes",
        "--only-binary",
        ":all:",
        "--strict",
        "--no-sources",
        "--default-index",
        "https://packages.example.invalid/simple",
        str(staged.requirements_lock),
    )
    assert "--offline" not in plan.install_packages_command
    assert "--no-index" not in plan.install_packages_command
    assert plan.timeout_seconds == 900.0
    assert plan.working_directory == staged.staging_root


def test_bundled_plan_is_offline_and_wheelhouse_only(
    tmp_path: Path,
) -> None:
    """Bundled mode should reject indexes and ambient uv caches."""
    config = _bundled_config(tmp_path)
    staged = _stage(config)

    plan = create_calendar_toolchain_environment_plan(config, staged)

    assert staged.wheelhouse_directory is not None
    assert plan.install_packages_command == (
        str(config.uv_executable),
        "--no-config",
        "--no-cache",
        "--no-python-downloads",
        "--no-managed-python",
        "--no-progress",
        "--offline",
        "pip",
        "sync",
        "--python",
        str(staged.environment_root / "bin" / "python"),
        "--require-hashes",
        "--only-binary",
        ":all:",
        "--strict",
        "--no-sources",
        "--no-index",
        "--find-links",
        str(staged.wheelhouse_directory),
        str(staged.requirements_lock),
    )
    assert "--default-index" not in plan.install_packages_command


def test_plan_does_not_create_environment_or_install_packages(
    tmp_path: Path,
) -> None:
    """Planning should leave the reserved environment path absent."""
    config = _network_config(tmp_path)
    staged = _stage(config)

    create_calendar_toolchain_environment_plan(config, staged)

    assert not staged.environment_root.exists()
    assert not staged.khal_executable.exists()
    assert not staged.vdirsyncer_executable.exists()


def test_external_mode_rejects_managed_environment_plan(
    tmp_path: Path,
) -> None:
    """External executables should not receive uv command plans."""
    config = _external_config(tmp_path)

    with pytest.raises(
        ValueError,
        match="does not use a managed environment plan",
    ):
        create_calendar_toolchain_environment_plan(
            config,
            object(),  # type: ignore[arg-type]
        )


def test_plan_rejects_staging_from_another_tools_root(
    tmp_path: Path,
) -> None:
    """A command plan must not combine unrelated configuration and staging."""
    first = _network_config(tmp_path / "first")
    second = _network_config(tmp_path / "second")
    staged = _stage(first)

    with pytest.raises(
        ValueError,
        match="does not belong to the configured tools root",
    ):
        create_calendar_toolchain_environment_plan(second, staged)


def test_bundled_plan_requires_wheelhouse_directory(
    tmp_path: Path,
) -> None:
    """Bundled planning should fail closed without its private wheel source."""
    config = _bundled_config(tmp_path)
    staged = replace(
        _stage(config),
        wheelhouse_directory=None,
    )

    with pytest.raises(
        ValueError,
        match="requires a staged wheelhouse directory",
    ):
        create_calendar_toolchain_environment_plan(config, staged)


def test_plan_contract_rejects_environment_python_outside_venv(
    tmp_path: Path,
) -> None:
    """The immutable plan should keep Python inside the staged environment."""
    environment = tmp_path / "stage" / "toolchain" / ".venv"

    with pytest.raises(
        ValueError,
        match="environment_python must be inside",
    ):
        CalendarToolchainEnvironmentPlan(
            mode=CalendarToolchainInstallMode.VERIFIED_NETWORK,
            create_environment_command=("/usr/bin/uv", "venv"),
            install_packages_command=("/usr/bin/uv", "pip", "install"),
            working_directory=tmp_path / "stage",
            environment_root=environment,
            environment_python=tmp_path / "outside-python",
            requirements_lock=tmp_path / "stage" / "requirements.lock",
            timeout_seconds=60.0,
        )
