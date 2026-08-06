"""Tests for deterministic managed calendar configuration."""

from pathlib import Path

import pytest

from lea.installers.calendar import (
    CalendarCaldavSyncConfig,
    CalendarToolchainConfigurationResult,
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
    CalendarToolchainRuntimeLayout,
    create_calendar_toolchain_configuration_plan,
    create_calendar_toolchain_runtime_layout,
    persist_calendar_toolchain_configuration,
    provision_calendar_toolchain_runtime_layout,
    render_calendar_caldav_vdirsyncer_configuration,
    render_calendar_khal_configuration,
    render_calendar_vdirsyncer_configuration,
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


def _provisioned(
    tmp_path: Path,
) -> tuple[
    CalendarToolchainInstallerConfig,
    CalendarToolchainRuntimeLayout,
]:
    """Return one configuration and provisioned runtime layout."""
    config = _config(tmp_path)
    result = provision_calendar_toolchain_runtime_layout(config)
    assert result.success is True
    assert result.layout is not None
    return config, result.layout


def test_khal_renderer_is_deterministic_and_explicit(
    tmp_path: Path,
) -> None:
    """khal should use managed vdirs, database and display timezone."""
    config = _config(tmp_path)
    layout = create_calendar_toolchain_runtime_layout(config)

    rendered = render_calendar_khal_configuration(
        layout,
        display_timezone="Africa/Gaborone",
    )

    assert rendered == (
        "[calendars]\n"
        "[[managed]]\n"
        f"path = {config.state_root}/vdirs/*\n"
        "type = discover\n"
        "\n"
        "[sqlite]\n"
        f"path = {config.state_root}/khal/khal.db\n"
        "\n"
        "[locale]\n"
        "local_timezone = Africa/Gaborone\n"
        "default_timezone = Africa/Gaborone\n"
        "timeformat = %H:%M\n"
        "dateformat = %Y-%m-%d\n"
        "longdateformat = %Y-%m-%d\n"
        "datetimeformat = %Y-%m-%d %H:%M\n"
        "longdatetimeformat = %Y-%m-%d %H:%M\n"
        "firstweekday = 0\n"
    )


def test_vdirsyncer_renderer_is_minimal_and_local_only(
    tmp_path: Path,
) -> None:
    """The initial vdirsyncer config must contain no remote endpoint."""
    config = _config(tmp_path)
    layout = create_calendar_toolchain_runtime_layout(config)

    rendered = render_calendar_vdirsyncer_configuration(layout)

    assert rendered == (
        f'[general]\nstatus_path = "{config.state_root}/vdirsyncer-status"\n'
    )

    lowered = rendered.lower()

    for forbidden in (
        "http://",
        "https://",
        "password",
        "token",
        "username",
        "[pair ",
        "[storage ",
    ):
        assert forbidden not in lowered


def test_repair_accepts_exact_supported_caldav_activation(tmp_path: Path) -> None:
    config, layout = _provisioned(tmp_path)
    layout.khal_configuration.write_text(
        render_calendar_khal_configuration(layout, display_timezone="Africa/Gaborone")
    )
    caldav = CalendarCaldavSyncConfig(
        layout,
        "http://192.168.1.2:5232/",
        "account",
        layout.state_root.parent / "secrets/calendar/caldav-password",
    )
    layout.vdirsyncer_configuration.write_text(
        render_calendar_caldav_vdirsyncer_configuration(caldav)
    )
    layout.khal_configuration.chmod(0o640)
    layout.vdirsyncer_configuration.chmod(0o640)

    result = persist_calendar_toolchain_configuration(
        config,
        layout,
        display_timezone="Africa/Gaborone",
    )

    assert result.success is True
    assert result.files_changed == ()


def test_configuration_plan_matches_runtime_layout(
    tmp_path: Path,
) -> None:
    """The plan should bind exact documents to canonical destinations."""
    config = _config(tmp_path)
    layout = create_calendar_toolchain_runtime_layout(config)

    plan = create_calendar_toolchain_configuration_plan(
        config,
        layout,
        display_timezone=" Africa/Gaborone ",
    )

    assert plan.layout == layout
    assert plan.display_timezone == "Africa/Gaborone"
    assert plan.khal_contents.endswith("\n")
    assert plan.vdirsyncer_contents.endswith("\n")


def test_persistence_creates_both_managed_files(
    tmp_path: Path,
) -> None:
    """Initial persistence should create only deterministic config files."""
    config, layout = _provisioned(tmp_path)

    result = persist_calendar_toolchain_configuration(
        config,
        layout,
        display_timezone="Africa/Gaborone",
    )

    assert result.success is True
    assert result.plan is not None
    assert result.files_changed == (
        layout.khal_configuration,
        layout.vdirsyncer_configuration,
    )

    assert layout.khal_configuration.read_text(encoding="utf-8") == (
        result.plan.khal_contents
    )
    assert (
        layout.vdirsyncer_configuration.read_text(encoding="utf-8")
        == result.plan.vdirsyncer_contents
    )

    for destination in result.files_changed:
        assert destination.is_file()
        assert destination.is_symlink() is False
        assert destination.stat().st_mode & 0o777 == 0o640


def test_persistence_is_idempotent(
    tmp_path: Path,
) -> None:
    """Byte-identical existing managed files should require no mutation."""
    config, layout = _provisioned(tmp_path)

    first = persist_calendar_toolchain_configuration(
        config,
        layout,
        display_timezone="Africa/Gaborone",
    )
    second = persist_calendar_toolchain_configuration(
        config,
        layout,
        display_timezone="Africa/Gaborone",
    )

    assert first.success is True
    assert second.success is True
    assert second.files_changed == ()


def test_mismatched_existing_file_blocks_all_writes(
    tmp_path: Path,
) -> None:
    """Differing managed content must fail before creating its sibling."""
    config, layout = _provisioned(tmp_path)
    layout.khal_configuration.write_text(
        "[calendars]\n# administrator content\n",
        encoding="utf-8",
    )

    result = persist_calendar_toolchain_configuration(
        config,
        layout,
        display_timezone="Africa/Gaborone",
    )

    assert result.success is False
    assert result.files_changed == ()
    assert (
        layout.khal_configuration.read_text(encoding="utf-8")
        == "[calendars]\n# administrator content\n"
    )
    assert layout.vdirsyncer_configuration.exists() is False
    assert result.issues[0].field == "khal_configuration"


def test_symlinked_destination_is_rejected(
    tmp_path: Path,
) -> None:
    """Managed configuration must never follow symbolic links."""
    config, layout = _provisioned(tmp_path)
    external = tmp_path / "external.conf"
    external.write_text("preserve\n", encoding="utf-8")
    layout.khal_configuration.symlink_to(external)

    result = persist_calendar_toolchain_configuration(
        config,
        layout,
        display_timezone="Africa/Gaborone",
    )

    assert result.success is False
    assert result.files_changed == ()
    assert external.read_text(encoding="utf-8") == "preserve\n"
    assert result.issues[0].field == "khal_configuration"


def test_unprovisioned_layout_is_rejected(
    tmp_path: Path,
) -> None:
    """Configuration must not implicitly create runtime directories."""
    config = _config(tmp_path)
    layout = create_calendar_toolchain_runtime_layout(config)

    result = persist_calendar_toolchain_configuration(
        config,
        layout,
        display_timezone="Africa/Gaborone",
    )

    assert result.success is False
    assert result.files_changed == ()
    assert result.issues[0].field == "configuration_directory"


def test_invalid_display_timezone_is_structured(
    tmp_path: Path,
) -> None:
    """Unknown IANA timezones should produce an invalid-argument result."""
    config, layout = _provisioned(tmp_path)

    result = persist_calendar_toolchain_configuration(
        config,
        layout,
        display_timezone="Invalid/Timezone",
    )

    assert result.success is False
    assert result.plan is None
    assert result.files_changed == ()
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.INVALID_ARGUMENT
    assert result.issues[0].field == "display_timezone"


def test_persistence_applies_root_group_ownership(
    tmp_path: Path,
) -> None:
    """Both ordinary configuration files should be root-managed."""
    config, layout = _provisioned(tmp_path)
    ownership: list[tuple[Path, str, str]] = []

    def apply_ownership(
        path: Path,
        owner: str,
        group: str,
    ) -> bool:
        ownership.append((path, owner, group))
        return False

    result = persist_calendar_toolchain_configuration(
        config,
        layout,
        display_timezone="Africa/Gaborone",
        apply_ownership=apply_ownership,
    )

    assert result.success is True
    assert ownership == [
        (layout.khal_configuration, "root", "lea"),
        (layout.vdirsyncer_configuration, "root", "lea"),
    ]


def test_mode_correction_is_reported_once(
    tmp_path: Path,
) -> None:
    """An identical file with a wrong mode should be corrected once."""
    config, layout = _provisioned(tmp_path)
    first = persist_calendar_toolchain_configuration(
        config,
        layout,
        display_timezone="Africa/Gaborone",
    )
    assert first.success is True

    layout.khal_configuration.chmod(0o600)

    second = persist_calendar_toolchain_configuration(
        config,
        layout,
        display_timezone="Africa/Gaborone",
    )

    assert second.success is True
    assert second.files_changed == (layout.khal_configuration,)
    assert layout.khal_configuration.stat().st_mode & 0o777 == 0o640


def test_wrong_layout_is_rejected_before_persistence(
    tmp_path: Path,
) -> None:
    """A layout from another installation must not be accepted."""
    first = _config(tmp_path / "first")
    second = _config(tmp_path / "second")
    wrong_layout = create_calendar_toolchain_runtime_layout(second)

    with pytest.raises(
        ValueError,
        match="does not match",
    ):
        create_calendar_toolchain_configuration_plan(
            first,
            wrong_layout,
            display_timezone="UTC",
        )


def test_successful_result_requires_plan() -> None:
    """A successful result without its plan must be impossible."""
    with pytest.raises(
        ValueError,
        match="must contain a plan",
    ):
        CalendarToolchainConfigurationResult(
            success=True,
            plan=None,
            files_changed=(),
            issues=(),
        )
