"""Tests for constructing a khal provider from installation evidence."""

import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lea.adapters.khal import (
    KhalCalendarProviderBuildResult,
    KhalCalendarProviderFactoryConfig,
    build_khal_calendar_provider,
)
from lea.calendars import CalendarProviderIssue
from lea.installers.calendar.configuration import (
    render_calendar_khal_configuration,
)
from lea.installers.calendar.contracts import (
    CalendarToolchainInstallMode,
)
from lea.installers.calendar.records import (
    CalendarToolchainInstallationRecord,
    render_calendar_toolchain_installation_record,
)
from lea.installers.calendar.runtime_layout import (
    CalendarToolchainRuntimeLayout,
)

KHAL_VERSION = "0.11.4"
VDIRSYNCER_VERSION = "0.19.3"
TOOLCHAIN_VERSION = "1.0.0"
INSTALLED_AT = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)


def digest(path: Path) -> str:
    """Return one exact file SHA-256."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_executable(
    path: Path,
    contents: str,
) -> None:
    """Create one executable script."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o750)


def make_factory_config(
    tmp_path: Path,
) -> KhalCalendarProviderFactoryConfig:
    """Create one complete runtime layout and factory configuration."""
    tools_root = tmp_path / "tools"
    configuration_directory = tmp_path / "config"
    state_root = tmp_path / "state"
    working_directory = tmp_path / "working"
    installation_record = tmp_path / "records" / "calendar.json"

    tools_root.mkdir(parents=True)
    configuration_directory.mkdir(parents=True)
    (state_root / "vdirs").mkdir(parents=True)
    (state_root / "khal").mkdir()
    (state_root / "vdirsyncer-status").mkdir()
    working_directory.mkdir()
    installation_record.parent.mkdir(parents=True)

    config = KhalCalendarProviderFactoryConfig(
        installation_record=installation_record,
        tools_root=tools_root,
        configuration_directory=configuration_directory,
        state_root=state_root,
        working_directory=working_directory,
        display_timezone="Africa/Gaborone",
    )
    write_expected_khal_configuration(config)
    return config


def runtime_layout(
    config: KhalCalendarProviderFactoryConfig,
) -> CalendarToolchainRuntimeLayout:
    """Return the exact runtime layout represented by a factory config."""
    return CalendarToolchainRuntimeLayout(
        configuration_directory=config.configuration_directory,
        khal_configuration=config.configuration_directory / "khal.conf",
        vdirsyncer_configuration=(config.configuration_directory / "vdirsyncer.conf"),
        state_root=config.state_root,
        vdirs=config.state_root / "vdirs",
        khal_state=config.state_root / "khal",
        vdirsyncer_status=config.state_root / "vdirsyncer-status",
    )


def write_expected_khal_configuration(
    config: KhalCalendarProviderFactoryConfig,
) -> None:
    """Persist the deterministic khal configuration expected by the factory."""
    (config.configuration_directory / "khal.conf").write_text(
        render_calendar_khal_configuration(
            runtime_layout(config),
            display_timezone=config.display_timezone,
        ),
        encoding="utf-8",
    )


def write_record(
    config: KhalCalendarProviderFactoryConfig,
    record: CalendarToolchainInstallationRecord,
) -> None:
    """Persist one strict installation record."""
    config.installation_record.write_text(
        render_calendar_toolchain_installation_record(record),
        encoding="utf-8",
    )


def managed_record(
    config: KhalCalendarProviderFactoryConfig,
    *,
    khal_version: str = KHAL_VERSION,
    khal_executable: Path | None = None,
) -> CalendarToolchainInstallationRecord:
    """Create managed toolchain evidence and executable scripts."""
    bin_directory = config.tools_root / TOOLCHAIN_VERSION / ".venv" / "bin"
    resolved_khal = khal_executable or bin_directory / "khal"
    vdirsyncer = bin_directory / "vdirsyncer"
    make_executable(
        resolved_khal,
        (f"#!{sys.executable}\nprint('khal, version {KHAL_VERSION}')\n"),
    )
    make_executable(
        vdirsyncer,
        f"#!{sys.executable}\nprint('vdirsyncer')\n",
    )
    return CalendarToolchainInstallationRecord(
        schema_version=2,
        component="calendar-toolchain",
        toolchain_version=TOOLCHAIN_VERSION,
        installation_mode=CalendarToolchainInstallMode.VERIFIED_NETWORK,
        platform="linux-aarch64",
        python_version="3.13.5",
        khal_version=khal_version,
        vdirsyncer_version=VDIRSYNCER_VERSION,
        khal_executable=resolved_khal,
        vdirsyncer_executable=vdirsyncer,
        lock_or_manifest_sha256="a" * 64,
        khal_executable_sha256=None,
        vdirsyncer_executable_sha256=None,
        smoke_test="passed",
        installed_at=INSTALLED_AT,
    )


def external_record(
    config: KhalCalendarProviderFactoryConfig,
) -> CalendarToolchainInstallationRecord:
    """Create exact external executable evidence."""
    external = config.installation_record.parent / "external"
    khal = external / "khal"
    vdirsyncer = external / "vdirsyncer"
    make_executable(
        khal,
        (f"#!{sys.executable}\nprint('khal, version {KHAL_VERSION}')\n"),
    )
    make_executable(
        vdirsyncer,
        f"#!{sys.executable}\nprint('vdirsyncer')\n",
    )
    return CalendarToolchainInstallationRecord(
        schema_version=2,
        component="calendar-toolchain",
        toolchain_version=TOOLCHAIN_VERSION,
        installation_mode=(CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES),
        platform="linux-aarch64",
        python_version=None,
        khal_version=KHAL_VERSION,
        vdirsyncer_version=VDIRSYNCER_VERSION,
        khal_executable=khal,
        vdirsyncer_executable=vdirsyncer,
        lock_or_manifest_sha256=None,
        khal_executable_sha256=digest(khal),
        vdirsyncer_executable_sha256=digest(vdirsyncer),
        smoke_test="passed",
        installed_at=INSTALLED_AT,
    )


def test_builds_managed_provider_from_exact_record_and_runtime(
    tmp_path: Path,
) -> None:
    """Managed evidence should produce one inspected provider."""
    config = make_factory_config(tmp_path)
    write_record(config, managed_record(config))

    result = build_khal_calendar_provider(config)

    assert result.success is True
    assert result.provider is not None
    assert result.provider.config.executable == (
        config.tools_root / TOOLCHAIN_VERSION / ".venv" / "bin" / "khal"
    )
    assert result.provider.config.configuration == (
        config.configuration_directory / "khal.conf"
    )
    assert result.provider.config.vdirs_directory == (config.state_root / "vdirs")
    assert result.provider.config.state_directory == (config.state_root / "khal")
    assert result.provider.config.display_timezone == "Africa/Gaborone"
    assert result.issues == ()


def test_builds_external_provider_after_digest_verification(
    tmp_path: Path,
) -> None:
    """External executables should remain bound to recorded digests."""
    config = make_factory_config(tmp_path)
    record = external_record(config)
    write_record(config, record)

    result = build_khal_calendar_provider(config)

    assert result.success is True
    assert result.provider is not None
    assert result.provider.config.executable == record.khal_executable


def test_missing_or_malformed_record_fails_closed(
    tmp_path: Path,
) -> None:
    """Record read failures must not create a provider."""
    config = make_factory_config(tmp_path)

    missing = build_khal_calendar_provider(config)

    assert missing.success is False
    assert missing.provider is None
    assert missing.issues[0].code == "khal_installation_record_invalid"
    assert missing.issues[0].operation == "build_provider"

    config.installation_record.write_text("{invalid\n", encoding="utf-8")
    malformed = build_khal_calendar_provider(config)

    assert malformed.success is False
    assert malformed.issues[0].code == "khal_installation_record_invalid"


def test_managed_record_must_use_versioned_toolchain_paths(
    tmp_path: Path,
) -> None:
    """A schema-valid managed record must not redirect executable identity."""
    config = make_factory_config(tmp_path)
    outside = tmp_path / "outside" / "khal"
    record = managed_record(
        config,
        khal_executable=outside,
    )
    write_record(config, record)

    result = build_khal_calendar_provider(config)

    assert result.success is False
    assert result.issues[0].code == "khal_managed_toolchain_path_invalid"
    assert result.issues[0].field == "khal_executable"


def test_external_checksum_drift_fails_closed(
    tmp_path: Path,
) -> None:
    """Changed external binaries must invalidate persisted evidence."""
    config = make_factory_config(tmp_path)
    record = external_record(config)
    write_record(config, record)
    record.khal_executable.write_text(
        "#!/bin/sh\nexit 1\n",
        encoding="utf-8",
    )
    record.khal_executable.chmod(0o750)

    result = build_khal_calendar_provider(config)

    assert result.success is False
    assert result.issues[0].code == ("khal_recorded_executable_checksum_mismatch")
    assert result.issues[0].field == "khal_executable"


def test_configuration_must_match_paths_and_timezone(
    tmp_path: Path,
) -> None:
    """Runtime construction should reject stale or foreign khal config."""
    config = make_factory_config(tmp_path)
    write_record(config, managed_record(config))
    (config.configuration_directory / "khal.conf").write_text(
        "[locale]\nlocal_timezone = UTC\n",
        encoding="utf-8",
    )

    result = build_khal_calendar_provider(config)

    assert result.success is False
    assert result.issues[0].code == "khal_configuration_mismatch"


def test_unsafe_runtime_directory_fails_closed(
    tmp_path: Path,
) -> None:
    """Runtime path validation must not follow directory symlinks."""
    config = make_factory_config(tmp_path)
    write_record(config, managed_record(config))
    real = tmp_path / "real-working"
    real.mkdir()
    config.working_directory.rmdir()
    config.working_directory.symlink_to(real)

    result = build_khal_calendar_provider(config)

    assert result.success is False
    assert result.issues[0].code == "khal_runtime_path_invalid"
    assert result.issues[0].field == "working_directory"


def test_recorded_version_mismatch_is_reported_under_build_boundary(
    tmp_path: Path,
) -> None:
    """Provider inspection should verify the recorded khal version."""
    config = make_factory_config(tmp_path)
    write_record(
        config,
        managed_record(
            config,
            khal_version="9.9.9",
        ),
    )

    result = build_khal_calendar_provider(config)

    assert result.success is False
    assert result.provider is None
    assert result.issues[0].code == "khal_unsupported_version"
    assert result.issues[0].operation == "build_provider"


def test_factory_configuration_validates_programming_inputs(
    tmp_path: Path,
) -> None:
    """Invalid paths, timezones and timeouts should fail immediately."""
    config = make_factory_config(tmp_path)

    with pytest.raises(ValueError, match="absolute path"):
        KhalCalendarProviderFactoryConfig(
            installation_record=Path("record.json"),
            tools_root=config.tools_root,
            configuration_directory=config.configuration_directory,
            state_root=config.state_root,
            working_directory=config.working_directory,
            display_timezone="UTC",
        )

    with pytest.raises(ValueError, match="valid IANA timezone"):
        KhalCalendarProviderFactoryConfig(
            installation_record=config.installation_record,
            tools_root=config.tools_root,
            configuration_directory=config.configuration_directory,
            state_root=config.state_root,
            working_directory=config.working_directory,
            display_timezone="Not/AZone",
        )

    with pytest.raises(TypeError, match="must be a number"):
        KhalCalendarProviderFactoryConfig(
            installation_record=config.installation_record,
            tools_root=config.tools_root,
            configuration_directory=config.configuration_directory,
            state_root=config.state_root,
            working_directory=config.working_directory,
            display_timezone="UTC",
            timeout_seconds=True,
        )

    with pytest.raises(TypeError, match="FactoryConfig"):
        build_khal_calendar_provider(
            object(),  # type: ignore[arg-type]
        )


def test_build_result_contract_is_strict() -> None:
    """Build result success and failure states should remain unambiguous."""
    issue = CalendarProviderIssue(
        code="test_failure",
        message="The test build failed.",
        provider="khal",
        operation="build_provider",
    )

    with pytest.raises(ValueError, match="contain a provider"):
        KhalCalendarProviderBuildResult(
            success=True,
            provider=None,
            issues=(),
        )

    with pytest.raises(ValueError, match="must not contain a provider"):
        KhalCalendarProviderBuildResult(
            success=False,
            provider=object(),  # type: ignore[arg-type]
            issues=(issue,),
        )

    with pytest.raises(ValueError, match="at least one issue"):
        KhalCalendarProviderBuildResult(
            success=False,
            provider=None,
            issues=(),
        )
