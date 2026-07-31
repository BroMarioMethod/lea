"""Tests for atomic managed calendar toolchain activation."""

import hashlib
import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from lea.installers.calendar import (
    CalendarToolchainActivatedLayout,
    CalendarToolchainActivationResult,
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
    CalendarToolchainStagingLayout,
    activate_staged_calendar_toolchain,
    create_calendar_toolchain_staging,
)


def _make_executable(
    path: Path,
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> None:
    """Create one deterministic shell executable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "#!/bin/sh\n"
            f"printf '%b' {stdout!r}\n"
            f"printf '%b' {stderr!r} >&2\n"
            f"exit {returncode}\n"
        ),
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _config(
    tmp_path: Path,
    *,
    toolchain_version: str = "calendar-1",
) -> CalendarToolchainInstallerConfig:
    """Return one managed verified-network installer configuration."""
    uv_executable = tmp_path / "uv"
    python_executable = tmp_path / "python3.13"
    requirements_lock = tmp_path / "requirements.lock"
    payload = b"khal==0.11.4\nvdirsyncer==0.19.3\n"

    _make_executable(uv_executable)
    _make_executable(python_executable)
    requirements_lock.write_bytes(payload)

    return CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.VERIFIED_NETWORK,
        toolchain_version=toolchain_version,
        khal_version="0.11.4",
        vdirsyncer_version="0.19.3",
        platform="linux-aarch64",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "install" / "calendar.json",
        service_user="lea",
        service_group="lea",
        uv_executable=uv_executable,
        python_executable=python_executable,
        requirements_lock=requirements_lock,
        expected_lock_sha256=hashlib.sha256(payload).hexdigest(),
        package_index_url="https://packages.example.invalid/simple",
        timeout_seconds=30.0,
    )


def _staged(
    tmp_path: Path,
    *,
    vdirsyncer_version: str = "0.19.3",
    python_symlink: bool = False,
) -> tuple[
    CalendarToolchainInstallerConfig,
    CalendarToolchainStagingLayout,
]:
    """Create one structurally valid staged relocatable toolchain."""
    config = _config(tmp_path)
    result = create_calendar_toolchain_staging(config)
    assert result.staged is not None
    staged = result.staged

    bin_directory = staged.environment_root / "bin"
    bin_directory.mkdir(parents=True)

    python = bin_directory / "python"

    if python_symlink:
        assert config.python_executable is not None
        python.symlink_to(config.python_executable)
        (bin_directory / "python3").symlink_to("python")
        (bin_directory / "python3.13").symlink_to("python")
    else:
        _make_executable(python)

    _make_executable(
        staged.khal_executable,
        stdout="khal, version 0.11.4\n",
    )
    _make_executable(
        staged.vdirsyncer_executable,
        stderr=f"vdirsyncer, version {vdirsyncer_version}\n",
    )

    (staged.environment_root / "lib64").symlink_to("lib")

    package_file = (
        staged.environment_root
        / "lib"
        / "python3.13"
        / "site-packages"
        / "calendar_package.py"
    )
    package_file.parent.mkdir(parents=True)
    package_file.write_text("VALUE = 1\n", encoding="utf-8")

    return config, staged


def test_activation_moves_only_verified_toolchain_root(
    tmp_path: Path,
) -> None:
    """Activation should preserve staging inputs for later cleanup."""
    config, staged = _staged(tmp_path)

    result = activate_staged_calendar_toolchain(
        config,
        staged,
    )

    final_root = config.tools_root / config.toolchain_version

    assert result.success is True
    assert result.changed is True
    assert result.activated is not None
    assert result.activated.toolchain_root == final_root
    assert result.activated.environment_root == final_root / ".venv"
    assert result.activated.khal_executable.is_file()
    assert result.activated.vdirsyncer_executable.is_file()
    assert staged.toolchain_root.exists() is False
    assert staged.staging_root.is_dir()
    assert staged.requirements_lock.is_file()
    assert config.installation_record.exists() is False


def test_activation_accepts_expected_uv_python_links(
    tmp_path: Path,
) -> None:
    """Expected interpreter links should survive without being followed."""
    config, staged = _staged(
        tmp_path,
        python_symlink=True,
    )

    result = activate_staged_calendar_toolchain(
        config,
        staged,
    )

    assert result.success is True
    assert result.activated is not None
    assert result.activated.python_executable.is_symlink()
    assert os.readlink(result.activated.python_executable) == str(
        config.python_executable
    )
    assert (result.activated.environment_root / "lib64").is_symlink()
    assert os.readlink(result.activated.environment_root / "lib64") == "lib"


def test_activation_normalises_modes_and_ownership(
    tmp_path: Path,
) -> None:
    """The final managed tree should use deliberate modes and ownership."""
    config, staged = _staged(tmp_path)
    package_file = (
        staged.environment_root
        / "lib"
        / "python3.13"
        / "site-packages"
        / "calendar_package.py"
    )
    ownership: list[tuple[Path, str, str]] = []

    def apply_ownership(
        path: Path,
        owner: str,
        group: str,
    ) -> bool:
        ownership.append((path, owner, group))
        return False

    result = activate_staged_calendar_toolchain(
        config,
        staged,
        apply_ownership=apply_ownership,
    )

    assert result.success is True
    assert result.activated is not None

    final_root = result.activated.toolchain_root
    final_package = final_root / package_file.relative_to(staged.toolchain_root)

    assert config.tools_root.stat().st_mode & 0o777 == 0o750
    assert final_root.stat().st_mode & 0o777 == 0o750
    assert result.activated.khal_executable.stat().st_mode & 0o777 == 0o750
    assert final_package.stat().st_mode & 0o777 == 0o640

    assert (config.tools_root, "root", "lea") in ownership
    assert (final_root, "root", "lea") in ownership
    assert (
        result.activated.khal_executable,
        "root",
        "lea",
    ) in ownership
    assert (final_package, "root", "lea") in ownership


def test_existing_final_root_is_not_replaced(
    tmp_path: Path,
) -> None:
    """Any pre-existing version root must be preserved for record checks."""
    config, staged = _staged(tmp_path)
    final_root = config.tools_root / config.toolchain_version
    final_root.mkdir()
    sentinel = final_root / "preserve"
    sentinel.write_text("existing\n", encoding="utf-8")

    result = activate_staged_calendar_toolchain(
        config,
        staged,
    )

    assert result.success is False
    assert result.changed is False
    assert (
        result.issues[0].code is CalendarToolchainInstallFailureCode.ALREADY_INSTALLED
    )
    assert sentinel.read_text(encoding="utf-8") == "existing\n"
    assert staged.toolchain_root.is_dir()


def test_missing_expected_executable_fails_before_move(
    tmp_path: Path,
) -> None:
    """Incomplete staging should remain untouched and unactivated."""
    config, staged = _staged(tmp_path)
    staged.vdirsyncer_executable.unlink()

    result = activate_staged_calendar_toolchain(
        config,
        staged,
    )

    assert result.success is False
    assert result.changed is False
    assert result.issues[0].field == "vdirsyncer_executable"
    assert staged.toolchain_root.is_dir()
    assert not (config.tools_root / config.toolchain_version).exists()


def test_unexpected_symlink_fails_before_move(
    tmp_path: Path,
) -> None:
    """Activation must not preserve arbitrary toolchain symlinks."""
    config, staged = _staged(tmp_path)
    outside = tmp_path / "outside"
    outside.write_text("preserve\n", encoding="utf-8")
    malicious = staged.environment_root / "lib" / "escape"
    malicious.parent.mkdir(parents=True, exist_ok=True)
    malicious.symlink_to(outside)

    result = activate_staged_calendar_toolchain(
        config,
        staged,
    )

    assert result.success is False
    assert result.changed is False
    assert result.issues[0].path == malicious
    assert outside.read_text(encoding="utf-8") == "preserve\n"
    assert staged.toolchain_root.is_dir()


def test_relocated_version_mismatch_rolls_back(
    tmp_path: Path,
) -> None:
    """Final-path version validation must roll back mismatched tools."""
    config, staged = _staged(
        tmp_path,
        vdirsyncer_version="0.20.0",
    )

    result = activate_staged_calendar_toolchain(
        config,
        staged,
    )

    final_root = config.tools_root / config.toolchain_version

    assert result.success is False
    assert result.changed is False
    assert (
        result.issues[0].code
        is CalendarToolchainInstallFailureCode.VERSION_CHECK_FAILED
    )
    assert final_root.exists() is False
    assert staged.staging_root.is_dir()
    assert staged.toolchain_root.exists() is False


def test_ownership_failure_after_move_rolls_back(
    tmp_path: Path,
) -> None:
    """Post-move permission failure must remove the new version root."""
    config, staged = _staged(tmp_path)
    final_root = config.tools_root / config.toolchain_version

    def fail_ownership(
        path: Path,
        _owner: str,
        _group: str,
    ) -> bool:
        if path == final_root:
            raise PermissionError("ownership denied")

        return False

    result = activate_staged_calendar_toolchain(
        config,
        staged,
        apply_ownership=fail_ownership,
    )

    assert result.success is False
    assert result.changed is False
    assert (
        result.issues[0].code is CalendarToolchainInstallFailureCode.ACTIVATION_FAILED
    )
    assert "ownership denied" in result.issues[0].message
    assert final_root.exists() is False
    assert config.installation_record.exists() is False


def test_failed_rollback_reports_remaining_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed rollback must report that the filesystem remains changed."""
    config, staged = _staged(
        tmp_path,
        vdirsyncer_version="0.20.0",
    )
    final_root = config.tools_root / config.toolchain_version

    def fail_rollback(
        path: Path,
    ) -> CalendarToolchainInstallerIssue:
        assert path == final_root

        return CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.ACTIVATION_FAILED,
            message="synthetic rollback failure",
            field="tools_root",
            path=path,
        )

    monkeypatch.setattr(
        "lea.installers.calendar.activation._rollback_activated_toolchain",
        fail_rollback,
    )

    result = activate_staged_calendar_toolchain(
        config,
        staged,
    )

    assert result.success is False
    assert result.changed is True
    assert len(result.issues) == 2
    assert final_root.is_dir()


def test_staging_from_another_tools_root_is_rejected(
    tmp_path: Path,
) -> None:
    """Activation must bind staging to the same configured tools root."""
    first_config, staged = _staged(tmp_path / "first")
    second_config = replace(
        first_config,
        tools_root=tmp_path / "second" / "tools",
    )

    result = activate_staged_calendar_toolchain(
        second_config,
        staged,
    )

    assert result.success is False
    assert result.changed is False
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.INVALID_ARGUMENT


def test_unsafe_version_component_is_rejected(
    tmp_path: Path,
) -> None:
    """A version must not escape or introduce nested target paths."""
    config, staged = _staged(tmp_path)
    unsafe = replace(
        config,
        toolchain_version="nested/version",
    )

    result = activate_staged_calendar_toolchain(
        unsafe,
        staged,
    )

    assert result.success is False
    assert result.changed is False
    assert result.issues[0].field == "toolchain_version"


def test_external_mode_does_not_activate_managed_staging(
    tmp_path: Path,
) -> None:
    """External executable selection has no managed activation phase."""
    managed, staged = _staged(tmp_path)
    khal = tmp_path / "external" / "khal"
    vdirsyncer = tmp_path / "external" / "vdirsyncer"
    _make_executable(khal)
    _make_executable(vdirsyncer)

    external = CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES,
        toolchain_version="external-1",
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

    result = activate_staged_calendar_toolchain(
        external,
        staged,
    )

    assert result.success is False
    assert result.changed is False
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.INVALID_ARGUMENT


def test_activated_layout_rejects_wrong_executable_path(
    tmp_path: Path,
) -> None:
    """The final path model must enforce exact executable locations."""
    final_root = tmp_path / "calendar-1"

    with pytest.raises(
        ValueError,
        match="khal_executable must be inside",
    ):
        CalendarToolchainActivatedLayout(
            toolchain_root=final_root,
            environment_root=final_root / ".venv",
            python_executable=final_root / ".venv" / "bin" / "python",
            khal_executable=final_root / "bin" / "khal",
            vdirsyncer_executable=(final_root / ".venv" / "bin" / "vdirsyncer"),
        )


def test_successful_activation_result_requires_layout() -> None:
    """Successful activation cannot omit its final path model."""
    with pytest.raises(
        ValueError,
        match="must contain its final layout",
    ):
        CalendarToolchainActivationResult(
            success=True,
            changed=True,
            activated=None,
            issues=(),
        )
