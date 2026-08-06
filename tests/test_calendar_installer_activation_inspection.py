"""Tests for inspection of activated managed calendar toolchains."""

import hashlib
import os
import stat
from pathlib import Path

from lea.installers.calendar import (
    CalendarToolchainActivatedLayout,
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
    inspect_activated_calendar_toolchain,
)


def _make_executable(path: Path) -> None:
    """Create one executable regular file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _config(
    tmp_path: Path,
) -> CalendarToolchainInstallerConfig:
    """Return one managed verified-network configuration."""
    uv = tmp_path / "uv"
    trusted_python = tmp_path / "python3.13"
    lock = tmp_path / "requirements.lock"
    payload = b"khal==0.11.4\nvdirsyncer==0.19.3\n"

    _make_executable(uv)
    _make_executable(trusted_python)
    lock.write_bytes(payload)

    return CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.VERIFIED_NETWORK,
        toolchain_version="calendar-1",
        khal_version="0.11.4",
        vdirsyncer_version="0.19.3",
        platform="linux-aarch64",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "install.json",
        service_user="lea",
        service_group="lea",
        uv_executable=uv,
        python_executable=trusted_python,
        requirements_lock=lock,
        expected_lock_sha256=hashlib.sha256(payload).hexdigest(),
        package_index_url="https://packages.example.invalid/simple",
    )


def _activated(
    config: CalendarToolchainInstallerConfig,
) -> CalendarToolchainActivatedLayout:
    """Create one structurally valid activated relocatable environment."""
    root = config.tools_root / config.toolchain_version
    environment = root / ".venv"
    bin_directory = environment / "bin"
    bin_directory.mkdir(parents=True)

    assert config.python_executable is not None

    (bin_directory / "python").symlink_to(config.python_executable)
    (bin_directory / "python3").symlink_to("python")
    (bin_directory / "python3.13").symlink_to("python")
    (environment / "lib64").symlink_to("lib")

    _make_executable(bin_directory / "khal")
    _make_executable(bin_directory / "vdirsyncer")

    package = (
        environment / "lib" / "python3.13" / "site-packages" / "calendar_package.py"
    )
    package.parent.mkdir(parents=True)
    package.write_text("VALUE = 1\n", encoding="utf-8")

    return CalendarToolchainActivatedLayout(
        toolchain_root=root,
        environment_root=environment,
        python_executable=bin_directory / "python",
        khal_executable=bin_directory / "khal",
        vdirsyncer_executable=bin_directory / "vdirsyncer",
    )


def test_valid_activated_toolchain_passes_inspection(
    tmp_path: Path,
) -> None:
    """A canonical activated environment should pass without mutation."""
    config = _config(tmp_path)
    activated = _activated(config)

    issues = inspect_activated_calendar_toolchain(
        config,
        activated,
    )

    assert issues == ()
    assert activated.toolchain_root.is_dir()
    assert os.readlink(activated.python_executable) == str(config.python_executable)


def test_missing_final_executable_is_reported(
    tmp_path: Path,
) -> None:
    """Inspection should fail closed when an expected tool is absent."""
    config = _config(tmp_path)
    activated = _activated(config)
    activated.vdirsyncer_executable.unlink()

    issues = inspect_activated_calendar_toolchain(
        config,
        activated,
    )

    assert len(issues) == 1
    assert issues[0].code is CalendarToolchainInstallFailureCode.ACTIVATION_FAILED
    assert issues[0].field == "vdirsyncer_executable"


def test_unexpected_symlink_is_rejected(
    tmp_path: Path,
) -> None:
    """Activated toolchains must not contain arbitrary symbolic links."""
    config = _config(tmp_path)
    activated = _activated(config)
    outside = tmp_path / "outside"
    outside.write_text("preserve\n", encoding="utf-8")
    malicious = activated.environment_root / "lib" / "escape"
    malicious.symlink_to(outside)

    issues = inspect_activated_calendar_toolchain(
        config,
        activated,
    )

    assert len(issues) == 1
    assert issues[0].path == malicious
    assert outside.read_text(encoding="utf-8") == "preserve\n"


def test_layout_from_another_root_is_rejected(
    tmp_path: Path,
) -> None:
    """Inspection must bind the layout to the configured version root."""
    first = _config(tmp_path / "first")
    second = _config(tmp_path / "second")
    activated = _activated(first)

    issues = inspect_activated_calendar_toolchain(
        second,
        activated,
    )

    assert len(issues) == 1
    assert issues[0].code is CalendarToolchainInstallFailureCode.INVALID_ARGUMENT
    assert activated.toolchain_root.is_dir()


def test_symlinked_tools_root_is_rejected(
    tmp_path: Path,
) -> None:
    """Inspection must not traverse a symlinked managed tools root."""
    config = _config(tmp_path)
    real_tools = tmp_path / "real-tools"
    linked_tools = config.tools_root
    linked_tools.symlink_to(real_tools, target_is_directory=True)

    root = real_tools / config.toolchain_version
    environment = root / ".venv"
    bin_directory = environment / "bin"
    bin_directory.mkdir(parents=True)

    assert config.python_executable is not None

    (bin_directory / "python").symlink_to(config.python_executable)
    _make_executable(bin_directory / "khal")
    _make_executable(bin_directory / "vdirsyncer")

    activated = CalendarToolchainActivatedLayout(
        toolchain_root=linked_tools / config.toolchain_version,
        environment_root=linked_tools / config.toolchain_version / ".venv",
        python_executable=(
            linked_tools / config.toolchain_version / ".venv" / "bin" / "python"
        ),
        khal_executable=(
            linked_tools / config.toolchain_version / ".venv" / "bin" / "khal"
        ),
        vdirsyncer_executable=(
            linked_tools / config.toolchain_version / ".venv" / "bin" / "vdirsyncer"
        ),
    )

    issues = inspect_activated_calendar_toolchain(
        config,
        activated,
    )

    assert len(issues) == 1
    assert issues[0].field == "tools_root"


def test_external_mode_has_no_managed_activation_inspection(
    tmp_path: Path,
) -> None:
    """External executables are validated through their separate path."""
    managed = _config(tmp_path)
    activated = _activated(managed)
    khal = tmp_path / "external" / "khal"
    vdirsyncer = tmp_path / "external" / "vdirsyncer"
    _make_executable(khal)
    _make_executable(vdirsyncer)

    external = CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES,
        toolchain_version=managed.toolchain_version,
        khal_version=managed.khal_version,
        vdirsyncer_version=managed.vdirsyncer_version,
        platform=managed.platform,
        tools_root=managed.tools_root,
        configuration_dir=managed.configuration_dir,
        state_root=managed.state_root,
        installation_record=managed.installation_record,
        service_user=managed.service_user,
        service_group=managed.service_group,
        external_khal_executable=khal,
        external_vdirsyncer_executable=vdirsyncer,
    )

    issues = inspect_activated_calendar_toolchain(
        external,
        activated,
    )

    assert len(issues) == 1
    assert issues[0].code is CalendarToolchainInstallFailureCode.INVALID_ARGUMENT
