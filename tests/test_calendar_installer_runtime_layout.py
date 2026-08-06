"""Tests for managed calendar runtime-directory provisioning."""

from pathlib import Path

import pytest

from lea.installers.calendar import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
    CalendarToolchainRuntimeLayout,
    CalendarToolchainRuntimeLayoutResult,
    create_calendar_toolchain_runtime_layout,
    provision_calendar_toolchain_runtime_layout,
)


def _make_executable(path: Path) -> None:
    """Create one executable placeholder required by installer contracts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o750)


def _config(
    tmp_path: Path,
) -> CalendarToolchainInstallerConfig:
    """Return one isolated external-executable configuration."""
    khal = tmp_path / "external" / "khal"
    vdirsyncer = tmp_path / "external" / "vdirsyncer"
    _make_executable(khal)
    _make_executable(vdirsyncer)

    return CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES,
        toolchain_version="external-1",
        khal_version="0.11.4",
        vdirsyncer_version="0.19.3",
        platform="linux-aarch64",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "install" / "calendar.json",
        service_user="lea",
        service_group="lea",
        external_khal_executable=khal,
        external_vdirsyncer_executable=vdirsyncer,
    )


def test_path_model_uses_canonical_runtime_layout(
    tmp_path: Path,
) -> None:
    """The immutable layout should expose every canonical runtime path."""
    config = _config(tmp_path)

    layout = create_calendar_toolchain_runtime_layout(config)

    assert layout.configuration_directory == config.configuration_dir
    assert layout.khal_configuration == (config.configuration_dir / "khal.conf")
    assert layout.vdirsyncer_configuration == (
        config.configuration_dir / "vdirsyncer.conf"
    )
    assert layout.state_root == config.state_root
    assert layout.vdirs == config.state_root / "vdirs"
    assert layout.khal_state == config.state_root / "khal"
    assert layout.vdirsyncer_status == (config.state_root / "vdirsyncer-status")


def test_provisioning_creates_only_runtime_directories(
    tmp_path: Path,
) -> None:
    """This slice must not create khal or vdirsyncer configuration files."""
    config = _config(tmp_path)

    result = provision_calendar_toolchain_runtime_layout(config)

    assert result.success is True
    assert result.layout is not None
    assert result.directories_changed == (
        config.configuration_dir,
        config.state_root,
        config.state_root / "vdirs",
        config.state_root / "khal",
        config.state_root / "vdirsyncer-status",
    )
    assert result.layout.khal_configuration.exists() is False
    assert result.layout.vdirsyncer_configuration.exists() is False

    for directory in result.directories_changed:
        assert directory.is_dir()
        assert directory.is_symlink() is False
        assert directory.stat().st_mode & 0o777 == 0o750


def test_provisioning_is_idempotent(
    tmp_path: Path,
) -> None:
    """A matching existing layout should require no further mutation."""
    config = _config(tmp_path)

    first = provision_calendar_toolchain_runtime_layout(config)
    second = provision_calendar_toolchain_runtime_layout(config)

    assert first.success is True
    assert second.success is True
    assert second.layout == first.layout
    assert second.directories_changed == ()


def test_existing_calendar_state_is_preserved(
    tmp_path: Path,
) -> None:
    """Provisioning must not delete or rewrite existing calendar data."""
    config = _config(tmp_path)
    vdir = config.state_root / "vdirs" / "personal"
    vdir.mkdir(parents=True)
    event = vdir / "existing.ics"
    event.write_text(
        "BEGIN:VCALENDAR\nEND:VCALENDAR\n",
        encoding="utf-8",
    )

    result = provision_calendar_toolchain_runtime_layout(config)

    assert result.success is True
    assert event.read_text(encoding="utf-8") == ("BEGIN:VCALENDAR\nEND:VCALENDAR\n")


def test_symlinked_managed_directory_is_rejected(
    tmp_path: Path,
) -> None:
    """Managed state paths must never follow symbolic links."""
    config = _config(tmp_path)
    external = tmp_path / "external-state"
    external.mkdir()
    config.state_root.mkdir()
    (config.state_root / "vdirs").symlink_to(
        external,
        target_is_directory=True,
    )

    result = provision_calendar_toolchain_runtime_layout(config)

    assert result.success is False
    assert result.layout is None
    assert result.directories_changed == ()
    assert result.issues[0].field == "vdirs"
    assert (
        result.issues[0].code is CalendarToolchainInstallFailureCode.ACTIVATION_FAILED
    )
    assert external.is_dir()


def test_existing_non_directory_is_rejected_before_mutation(
    tmp_path: Path,
) -> None:
    """An incompatible managed path should fail before creating siblings."""
    config = _config(tmp_path)
    config.state_root.write_text("not a directory", encoding="utf-8")

    result = provision_calendar_toolchain_runtime_layout(config)

    assert result.success is False
    assert result.layout is None
    assert result.directories_changed == ()
    assert config.configuration_dir.exists() is False
    assert result.issues[0].field == "state_root"


def test_missing_base_parent_is_rejected_without_creation(
    tmp_path: Path,
) -> None:
    """The calendar slice must not implicitly create base LEA parents."""
    original = _config(tmp_path)
    configuration_dir = tmp_path / "missing-parent" / "calendar"

    config = CalendarToolchainInstallerConfig(
        mode=original.mode,
        toolchain_version=original.toolchain_version,
        khal_version=original.khal_version,
        vdirsyncer_version=original.vdirsyncer_version,
        platform=original.platform,
        tools_root=original.tools_root,
        configuration_dir=configuration_dir,
        state_root=original.state_root,
        installation_record=original.installation_record,
        service_user=original.service_user,
        service_group=original.service_group,
        external_khal_executable=original.external_khal_executable,
        external_vdirsyncer_executable=(original.external_vdirsyncer_executable),
    )

    result = provision_calendar_toolchain_runtime_layout(config)

    assert result.success is False
    assert result.directories_changed == ()
    assert configuration_dir.exists() is False
    assert result.issues[0].field == "configuration_dir_parent"


def test_provisioning_applies_canonical_ownership(
    tmp_path: Path,
) -> None:
    """Configuration is root-managed while state belongs to LEA."""
    config = _config(tmp_path)
    ownership: list[tuple[Path, str, str]] = []

    def apply_ownership(
        path: Path,
        owner: str,
        group: str,
    ) -> bool:
        ownership.append((path, owner, group))
        return False

    result = provision_calendar_toolchain_runtime_layout(
        config,
        apply_ownership=apply_ownership,
    )

    assert result.success is True
    assert ownership == [
        (config.configuration_dir, "root", "lea"),
        (config.state_root, "lea", "lea"),
        (config.state_root / "vdirs", "lea", "lea"),
        (config.state_root / "khal", "lea", "lea"),
        (
            config.state_root / "vdirsyncer-status",
            "lea",
            "lea",
        ),
    ]


def test_mode_correction_is_reported_once(
    tmp_path: Path,
) -> None:
    """Correcting an existing directory mode should count as one mutation."""
    config = _config(tmp_path)
    config.configuration_dir.mkdir(mode=0o700)

    result = provision_calendar_toolchain_runtime_layout(config)

    assert result.success is True
    assert result.directories_changed[0] == config.configuration_dir
    assert result.directories_changed.count(config.configuration_dir) == 1
    assert config.configuration_dir.stat().st_mode & 0o777 == 0o750


def test_ownership_change_is_reported_once(
    tmp_path: Path,
) -> None:
    """Ownership mutations should be represented in changed paths."""
    config = _config(tmp_path)
    changed_by_ownership = config.state_root / "khal"

    def apply_ownership(
        path: Path,
        _owner: str,
        _group: str,
    ) -> bool:
        return path == changed_by_ownership

    first = provision_calendar_toolchain_runtime_layout(config)
    assert first.success is True

    second = provision_calendar_toolchain_runtime_layout(
        config,
        apply_ownership=apply_ownership,
    )

    assert second.success is True
    assert second.directories_changed == (changed_by_ownership,)


def test_ownership_failure_is_structured_and_reports_prior_changes(
    tmp_path: Path,
) -> None:
    """A failed ownership application should retain mutation evidence."""
    config = _config(tmp_path)

    def fail_ownership(
        _path: Path,
        _owner: str,
        _group: str,
    ) -> bool:
        raise KeyError("lea")

    result = provision_calendar_toolchain_runtime_layout(
        config,
        apply_ownership=fail_ownership,
    )

    assert result.success is False
    assert result.layout is None
    assert result.directories_changed == (config.configuration_dir,)
    assert result.issues[0].field == "configuration_dir"
    assert "lea" in result.issues[0].message


def test_runtime_layout_contract_rejects_wrong_child_path(
    tmp_path: Path,
) -> None:
    """The path model must not permit a configuration outside its root."""
    config = _config(tmp_path)

    with pytest.raises(
        ValueError,
        match="khal_configuration must be inside",
    ):
        CalendarToolchainRuntimeLayout(
            configuration_directory=config.configuration_dir,
            khal_configuration=tmp_path / "other" / "khal.conf",
            vdirsyncer_configuration=(config.configuration_dir / "vdirsyncer.conf"),
            state_root=config.state_root,
            vdirs=config.state_root / "vdirs",
            khal_state=config.state_root / "khal",
            vdirsyncer_status=(config.state_root / "vdirsyncer-status"),
        )


def test_successful_result_requires_layout() -> None:
    """A successful result without its path model must be impossible."""
    with pytest.raises(
        ValueError,
        match="must contain a layout",
    ):
        CalendarToolchainRuntimeLayoutResult(
            success=True,
            layout=None,
            directories_changed=(),
            issues=(),
        )
