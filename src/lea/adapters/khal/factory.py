"""Build one verified khal calendar provider from persisted runtime evidence."""

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lea.adapters.khal.contracts import KhalConfig
from lea.adapters.khal.provider import KhalCalendarProvider
from lea.calendars import CalendarProviderIssue
from lea.installers.calendar.configuration import (
    render_calendar_khal_configuration,
)
from lea.installers.calendar.contracts import CalendarToolchainInstallMode
from lea.installers.calendar.preflight import calculate_calendar_sha256
from lea.installers.calendar.records import (
    read_calendar_toolchain_installation_record,
)
from lea.installers.calendar.runtime_layout import (
    CalendarToolchainRuntimeLayout,
)

_PROVIDER = "khal"
_OPERATION = "build_provider"
_MAX_CONFIGURATION_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class KhalCalendarProviderFactoryConfig:
    """Immutable runtime inputs for constructing one khal calendar provider."""

    installation_record: Path
    tools_root: Path
    configuration_directory: Path
    state_root: Path
    working_directory: Path
    display_timezone: str
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        """Validate caller-supplied runtime configuration."""
        for field_name, path in (
            ("installation_record", self.installation_record),
            ("tools_root", self.tools_root),
            ("configuration_directory", self.configuration_directory),
            ("state_root", self.state_root),
            ("working_directory", self.working_directory),
        ):
            _validate_absolute_path(path, field_name=field_name)

        _validate_display_timezone(self.display_timezone)

        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds,
            (int, float),
        ):
            raise TypeError("timeout_seconds must be a number.")

        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")


@dataclass(frozen=True, slots=True)
class KhalCalendarProviderBuildResult:
    """Result of constructing and verifying one khal calendar provider."""

    success: bool
    provider: KhalCalendarProvider | None
    issues: tuple[CalendarProviderIssue, ...]

    def __post_init__(self) -> None:
        """Validate build-result consistency."""
        if not isinstance(self.success, bool):
            raise TypeError("success must be a boolean.")

        if self.success:
            if self.provider is None:
                raise ValueError("A successful provider build must contain a provider.")

            if not isinstance(self.provider, KhalCalendarProvider):
                raise TypeError("provider must be a KhalCalendarProvider value.")

            if self.issues:
                raise ValueError("A successful provider build must not contain issues.")

            return

        if self.provider is not None:
            raise ValueError("A failed provider build must not contain a provider.")

        if not self.issues:
            raise ValueError("A failed provider build must contain at least one issue.")


def build_khal_calendar_provider(
    config: KhalCalendarProviderFactoryConfig,
) -> KhalCalendarProviderBuildResult:
    """Build and inspect one provider without installing or repairing anything."""
    if not isinstance(config, KhalCalendarProviderFactoryConfig):
        raise TypeError("config must be a KhalCalendarProviderFactoryConfig value.")

    record, record_issues = read_calendar_toolchain_installation_record(
        config.installation_record
    )

    if record_issues:
        return _failure(
            tuple(
                CalendarProviderIssue(
                    code="khal_installation_record_invalid",
                    message=issue.message,
                    provider=_PROVIDER,
                    operation=_OPERATION,
                    field=issue.field,
                )
                for issue in record_issues
            )
        )

    if record is None:
        return _failure(
            (
                _issue(
                    code="khal_installation_record_invalid",
                    message=(
                        "The calendar installation record was unavailable "
                        "without a structured diagnostic."
                    ),
                    field="installation_record",
                ),
            )
        )

    executable_issue = _verify_recorded_executables(
        config=config,
        record=record,
    )

    if executable_issue is not None:
        return _failure((executable_issue,))

    layout = CalendarToolchainRuntimeLayout(
        configuration_directory=config.configuration_directory,
        khal_configuration=(config.configuration_directory / "khal.conf"),
        vdirsyncer_configuration=(config.configuration_directory / "vdirsyncer.conf"),
        state_root=config.state_root,
        vdirs=config.state_root / "vdirs",
        khal_state=config.state_root / "khal",
        vdirsyncer_status=config.state_root / "vdirsyncer-status",
    )

    runtime_issue = _verify_runtime_layout(
        layout=layout,
        working_directory=config.working_directory,
        display_timezone=config.display_timezone,
    )

    if runtime_issue is not None:
        return _failure((runtime_issue,))

    khal_config = KhalConfig(
        executable=record.khal_executable,
        configuration=layout.khal_configuration,
        vdirs_directory=layout.vdirs,
        state_directory=layout.khal_state,
        working_directory=config.working_directory,
        expected_version=record.khal_version,
        display_timezone=config.display_timezone,
        timeout_seconds=config.timeout_seconds,
    )
    provider = KhalCalendarProvider(khal_config)
    inspection = provider.inspect()

    if not inspection.available:
        return _failure(_with_build_operation(inspection.issues))

    return KhalCalendarProviderBuildResult(
        success=True,
        provider=provider,
        issues=(),
    )


def _verify_recorded_executables(
    *,
    config: KhalCalendarProviderFactoryConfig,
    record: object,
) -> CalendarProviderIssue | None:
    """Verify exact path and digest evidence for both toolchain executables."""
    from lea.installers.calendar.records import (
        CalendarToolchainInstallationRecord,
    )

    if not isinstance(record, CalendarToolchainInstallationRecord):
        return _issue(
            code="khal_installation_record_invalid",
            message=(
                "The calendar installation record had an unexpected runtime type."
            ),
            field="installation_record",
        )

    if record.installation_mode is CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES:
        expected_digests = (
            (
                "khal_executable",
                record.khal_executable,
                record.khal_executable_sha256,
            ),
            (
                "vdirsyncer_executable",
                record.vdirsyncer_executable,
                record.vdirsyncer_executable_sha256,
            ),
        )
    else:
        path_issue = _verify_managed_executable_paths(
            config=config,
            record=record,
        )

        if path_issue is not None:
            return path_issue

        expected_digests = (
            ("khal_executable", record.khal_executable, None),
            (
                "vdirsyncer_executable",
                record.vdirsyncer_executable,
                None,
            ),
        )

    for field_name, path, expected_digest in expected_digests:
        issue = _inspect_executable(path, field_name=field_name)

        if issue is not None:
            return issue

        if expected_digest is None:
            continue

        try:
            actual_digest = calculate_calendar_sha256(path)
        except OSError:
            return _issue(
                code="khal_recorded_executable_unreadable",
                message=(
                    f"The recorded {field_name.replace('_', ' ')} could not be hashed."
                ),
                field=field_name,
            )

        if actual_digest != expected_digest:
            return _issue(
                code="khal_recorded_executable_checksum_mismatch",
                message=(
                    f"The recorded {field_name.replace('_', ' ')} "
                    "checksum no longer matched its installation evidence."
                ),
                field=field_name,
            )

    return None


def _verify_managed_executable_paths(
    *,
    config: KhalCalendarProviderFactoryConfig,
    record: object,
) -> CalendarProviderIssue | None:
    """Require managed record paths to remain inside the versioned toolchain."""
    from lea.installers.calendar.records import (
        CalendarToolchainInstallationRecord,
    )

    assert isinstance(record, CalendarToolchainInstallationRecord)
    component = Path(record.toolchain_version)

    if (
        component.is_absolute()
        or component.name != record.toolchain_version
        or record.toolchain_version in {".", ".."}
    ):
        return _issue(
            code="khal_managed_toolchain_path_invalid",
            message=(
                "The managed calendar toolchain version was not one safe "
                "filesystem component."
            ),
            field="toolchain_version",
        )

    expected_root = config.tools_root / record.toolchain_version
    expected_bin = expected_root / ".venv" / "bin"

    if record.khal_executable != expected_bin / "khal":
        return _issue(
            code="khal_managed_toolchain_path_invalid",
            message=(
                "The managed khal executable did not match the versioned "
                "toolchain layout."
            ),
            field="khal_executable",
        )

    if record.vdirsyncer_executable != expected_bin / "vdirsyncer":
        return _issue(
            code="khal_managed_toolchain_path_invalid",
            message=(
                "The managed vdirsyncer executable did not match the "
                "versioned toolchain layout."
            ),
            field="vdirsyncer_executable",
        )

    return _inspect_directory(
        config.tools_root,
        field_name="tools_root",
    )


def _verify_runtime_layout(
    *,
    layout: CalendarToolchainRuntimeLayout,
    working_directory: Path,
    display_timezone: str,
) -> CalendarProviderIssue | None:
    """Verify exact managed runtime paths and deterministic khal configuration."""
    for field_name, directory in (
        ("configuration_directory", layout.configuration_directory),
        ("state_root", layout.state_root),
        ("vdirs_directory", layout.vdirs),
        ("state_directory", layout.khal_state),
        ("working_directory", working_directory),
    ):
        issue = _inspect_directory(
            directory,
            field_name=field_name,
        )

        if issue is not None:
            return issue

    expected_configuration = render_calendar_khal_configuration(
        layout,
        display_timezone=display_timezone,
    )
    actual_result = _read_configuration(layout.khal_configuration)

    if isinstance(actual_result, CalendarProviderIssue):
        return actual_result

    if actual_result != expected_configuration:
        return _issue(
            code="khal_configuration_mismatch",
            message=(
                "The managed khal configuration did not match the "
                "configured runtime paths and display timezone."
            ),
            field="configuration",
        )

    return None


def _read_configuration(
    path: Path,
) -> str | CalendarProviderIssue:
    """Read one exact bounded regular non-symbolic UTF-8 configuration file."""
    try:
        if path.is_symlink():
            return _issue(
                code="khal_configuration_invalid",
                message=("The managed khal configuration must not be a symbolic link."),
                field="configuration",
            )

        if not path.exists():
            return _issue(
                code="khal_configuration_missing",
                message=("The managed khal configuration does not exist."),
                field="configuration",
            )

        if not path.is_file():
            return _issue(
                code="khal_configuration_invalid",
                message=("The managed khal configuration is not a regular file."),
                field="configuration",
            )

        if path.stat().st_size > _MAX_CONFIGURATION_BYTES:
            return _issue(
                code="khal_configuration_invalid",
                message=("The managed khal configuration exceeded its size limit."),
                field="configuration",
            )

        contents = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return _issue(
            code="khal_configuration_unreadable",
            message=("The managed khal configuration could not be read as UTF-8."),
            field="configuration",
        )

    if len(contents.encode("utf-8")) > _MAX_CONFIGURATION_BYTES:
        return _issue(
            code="khal_configuration_invalid",
            message=("The managed khal configuration exceeded its size limit."),
            field="configuration",
        )

    return contents


def _inspect_executable(
    path: Path,
    *,
    field_name: str,
) -> CalendarProviderIssue | None:
    """Require one exact regular non-symbolic executable file."""
    try:
        if path.is_symlink():
            return _issue(
                code="khal_recorded_executable_invalid",
                message=(
                    f"The recorded {field_name.replace('_', ' ')} "
                    "must not be a symbolic link."
                ),
                field=field_name,
            )

        if not path.exists():
            return _issue(
                code="khal_recorded_executable_missing",
                message=(
                    f"The recorded {field_name.replace('_', ' ')} does not exist."
                ),
                field=field_name,
            )

        if not path.is_file() or not os.access(path, os.X_OK):
            return _issue(
                code="khal_recorded_executable_invalid",
                message=(
                    f"The recorded {field_name.replace('_', ' ')} "
                    "is not an executable regular file."
                ),
                field=field_name,
            )
    except OSError:
        return _issue(
            code="khal_recorded_executable_invalid",
            message=(
                f"The recorded {field_name.replace('_', ' ')} could not be inspected."
            ),
            field=field_name,
        )

    return None


def _inspect_directory(
    path: Path,
    *,
    field_name: str,
) -> CalendarProviderIssue | None:
    """Require one exact regular non-symbolic directory."""
    try:
        if path.is_symlink():
            return _issue(
                code="khal_runtime_path_invalid",
                message=(
                    f"The configured {field_name.replace('_', ' ')} "
                    "must not be a symbolic link."
                ),
                field=field_name,
            )

        if not path.exists():
            return _issue(
                code="khal_runtime_path_missing",
                message=(
                    f"The configured {field_name.replace('_', ' ')} does not exist."
                ),
                field=field_name,
            )

        if not path.is_dir():
            return _issue(
                code="khal_runtime_path_invalid",
                message=(
                    f"The configured {field_name.replace('_', ' ')} is not a directory."
                ),
                field=field_name,
            )
    except OSError:
        return _issue(
            code="khal_runtime_path_invalid",
            message=(
                f"The configured {field_name.replace('_', ' ')} could not be inspected."
            ),
            field=field_name,
        )

    return None


def _with_build_operation(
    issues: tuple[CalendarProviderIssue, ...],
) -> tuple[CalendarProviderIssue, ...]:
    """Preserve provider diagnostics under the provider-build boundary."""
    return tuple(
        CalendarProviderIssue(
            code=issue.code,
            message=issue.message,
            provider=issue.provider or _PROVIDER,
            operation=_OPERATION,
            calendar_id=issue.calendar_id,
            event_uid=issue.event_uid,
            field=issue.field,
            return_code=issue.return_code,
        )
        for issue in issues
    )


def _failure(
    issues: tuple[CalendarProviderIssue, ...],
) -> KhalCalendarProviderBuildResult:
    """Construct one failed provider build."""
    return KhalCalendarProviderBuildResult(
        success=False,
        provider=None,
        issues=issues,
    )


def _issue(
    *,
    code: str,
    message: str,
    field: str,
) -> CalendarProviderIssue:
    """Construct one structured provider-build issue."""
    return CalendarProviderIssue(
        code=code,
        message=message,
        provider=_PROVIDER,
        operation=_OPERATION,
        field=field,
    )


def _validate_display_timezone(value: str) -> None:
    """Validate one canonical IANA display timezone."""
    if not isinstance(value, str):
        raise TypeError("display_timezone must be a string.")

    if not value.strip():
        raise ValueError("display_timezone must be non-empty.")

    try:
        zone = ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise ValueError("display_timezone must be a valid IANA timezone.") from error

    if zone.key != value:
        raise ValueError("display_timezone must use its canonical IANA identifier.")


def _validate_absolute_path(
    path: Path,
    *,
    field_name: str,
) -> None:
    """Validate one absolute pathlib path."""
    if not isinstance(path, Path):
        raise TypeError(f"{field_name} must be a pathlib.Path value.")

    if not path.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path.")

    if "\x00" in str(path):
        raise ValueError(f"{field_name} must not contain a null byte.")
