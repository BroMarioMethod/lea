"""Deterministic managed configuration for calendar tools."""

import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lea.installers.calendar.contracts import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallFailureCode,
)
from lea.installers.calendar.ownership import (
    CalendarOwnershipApplier,
    ignore_calendar_ownership,
)
from lea.installers.calendar.runtime_layout import (
    CalendarToolchainRuntimeLayout,
    create_calendar_toolchain_runtime_layout,
)

_CONFIGURATION_FILE_MODE = 0o640


@dataclass(frozen=True, slots=True)
class CalendarToolchainConfigurationPlan:
    """Exact managed calendar configuration documents and destinations."""

    layout: CalendarToolchainRuntimeLayout
    display_timezone: str
    khal_contents: str
    vdirsyncer_contents: str

    def __post_init__(self) -> None:
        """Validate one immutable configuration plan."""
        if not isinstance(self.layout, CalendarToolchainRuntimeLayout):
            raise TypeError("layout must be a CalendarToolchainRuntimeLayout value.")

        _validate_display_timezone(self.display_timezone)

        for field_name, contents in (
            ("khal_contents", self.khal_contents),
            ("vdirsyncer_contents", self.vdirsyncer_contents),
        ):
            if not isinstance(contents, str) or not contents:
                raise ValueError(f"{field_name} must be non-empty.")

            if not contents.endswith("\n"):
                raise ValueError(f"{field_name} must end with one newline.")


@dataclass(frozen=True, slots=True)
class CalendarToolchainConfigurationResult:
    """Result of persisting deterministic calendar configuration."""

    success: bool
    plan: CalendarToolchainConfigurationPlan | None
    files_changed: tuple[Path, ...]
    issues: tuple[CalendarToolchainInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate result consistency and mutation reporting."""
        if not isinstance(self.success, bool):
            raise TypeError("success must be a boolean.")

        if len(set(self.files_changed)) != len(self.files_changed):
            raise ValueError("files_changed must not contain duplicate paths.")

        for path in self.files_changed:
            _validate_absolute_path(
                path,
                field_name="files_changed",
            )

        if self.success:
            if self.plan is None:
                raise ValueError(
                    "A successful configuration result must contain a plan."
                )

            if self.issues:
                raise ValueError(
                    "A successful configuration result must not contain issues."
                )

            return

        if not self.issues:
            raise ValueError("A failed configuration result must contain issues.")


@dataclass(frozen=True, slots=True)
class _ManagedConfigurationFile:
    """One exact managed calendar configuration file."""

    field: str
    destination: Path
    contents: str

    def __post_init__(self) -> None:
        """Validate one internal managed-file description."""
        if not self.field.strip():
            raise ValueError("field must be non-empty.")

        _validate_absolute_path(
            self.destination,
            field_name="destination",
        )

        if not self.contents:
            raise ValueError("contents must be non-empty.")


def render_calendar_khal_configuration(
    layout: CalendarToolchainRuntimeLayout,
    *,
    display_timezone: str,
) -> str:
    """Render minimal deterministic khal configuration."""
    if not isinstance(layout, CalendarToolchainRuntimeLayout):
        raise TypeError("layout must be a CalendarToolchainRuntimeLayout value.")

    timezone = _validate_display_timezone(display_timezone)
    vdir_pattern = f"{_config_path(layout.vdirs, field_name='vdirs')}/*"
    database = _config_path(
        layout.khal_state / "khal.db",
        field_name="khal_database",
    )

    return (
        "[calendars]\n"
        "[[managed]]\n"
        f"path = {vdir_pattern}\n"
        "type = discover\n"
        "\n"
        "[sqlite]\n"
        f"path = {database}\n"
        "\n"
        "[locale]\n"
        f"local_timezone = {timezone}\n"
        f"default_timezone = {timezone}\n"
        "timeformat = %H:%M\n"
        "dateformat = %Y-%m-%d\n"
        "longdateformat = %Y-%m-%d\n"
        "datetimeformat = %Y-%m-%d %H:%M\n"
        "longdatetimeformat = %Y-%m-%d %H:%M\n"
        "firstweekday = 0\n"
    )


def render_calendar_vdirsyncer_configuration(
    layout: CalendarToolchainRuntimeLayout,
) -> str:
    """Render minimal local-only vdirsyncer configuration."""
    if not isinstance(layout, CalendarToolchainRuntimeLayout):
        raise TypeError("layout must be a CalendarToolchainRuntimeLayout value.")

    status_path = _quoted_config_path(
        layout.vdirsyncer_status,
        field_name="vdirsyncer_status",
    )

    return f"[general]\nstatus_path = {status_path}\n"


def create_calendar_toolchain_configuration_plan(
    config: CalendarToolchainInstallerConfig,
    layout: CalendarToolchainRuntimeLayout,
    *,
    display_timezone: str,
) -> CalendarToolchainConfigurationPlan:
    """Create exact managed documents without mutating disk."""
    if not isinstance(config, CalendarToolchainInstallerConfig):
        raise TypeError("config must be a CalendarToolchainInstallerConfig value.")

    expected_layout = create_calendar_toolchain_runtime_layout(config)

    if layout != expected_layout:
        raise ValueError("layout does not match the configured calendar runtime paths.")

    timezone = _validate_display_timezone(display_timezone)

    return CalendarToolchainConfigurationPlan(
        layout=layout,
        display_timezone=timezone,
        khal_contents=render_calendar_khal_configuration(
            layout,
            display_timezone=timezone,
        ),
        vdirsyncer_contents=(render_calendar_vdirsyncer_configuration(layout)),
    )


def persist_calendar_toolchain_configuration(
    config: CalendarToolchainInstallerConfig,
    layout: CalendarToolchainRuntimeLayout,
    *,
    display_timezone: str,
    fsync: bool = False,
    apply_ownership: CalendarOwnershipApplier = (ignore_calendar_ownership),
) -> CalendarToolchainConfigurationResult:
    """Create or validate LEA-managed calendar configuration files."""
    try:
        plan = create_calendar_toolchain_configuration_plan(
            config,
            layout,
            display_timezone=display_timezone,
        )
    except (TypeError, ValueError, ZoneInfoNotFoundError) as error:
        return _failure(
            plan=None,
            changed=[],
            issue=CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=(
                    "The calendar configuration plan is invalid: "
                    f"{_error_detail(error)}."
                ),
                field="display_timezone",
            ),
        )

    runtime_issue = _validate_runtime_layout(plan.layout)

    if runtime_issue is not None:
        return _failure(
            plan=plan,
            changed=[],
            issue=runtime_issue,
        )

    managed_files = _managed_files(plan)
    changed: list[Path] = []

    for managed in managed_files:
        issue = _inspect_existing_file(managed)

        if issue is not None:
            return _failure(
                plan=plan,
                changed=changed,
                issue=issue,
            )

    for managed in managed_files:
        created = False

        if not managed.destination.exists():
            issue = _write_new_file(
                managed,
                fsync=fsync,
            )

            if issue is not None:
                return _failure(
                    plan=plan,
                    changed=changed,
                    issue=issue,
                )

            created = True
            _record_change(changed, managed.destination)

        try:
            current_mode = managed.destination.stat().st_mode & 0o777

            if current_mode != _CONFIGURATION_FILE_MODE:
                managed.destination.chmod(_CONFIGURATION_FILE_MODE)
                _record_change(changed, managed.destination)

            ownership_changed = apply_ownership(
                managed.destination,
                "root",
                config.service_group,
            )

            if ownership_changed:
                _record_change(changed, managed.destination)
        except (KeyError, OSError) as error:
            return _failure(
                plan=plan,
                changed=changed,
                issue=CalendarToolchainInstallerIssue(
                    code=(CalendarToolchainInstallFailureCode.ACTIVATION_FAILED),
                    message=(
                        f"The {managed.field} permissions could not be "
                        f"applied: {_error_detail(error)}."
                    ),
                    field=managed.field,
                    path=managed.destination,
                ),
            )

        if created and fsync:
            try:
                _fsync_directory(managed.destination.parent)
            except OSError as error:
                return _failure(
                    plan=plan,
                    changed=changed,
                    issue=CalendarToolchainInstallerIssue(
                        code=(CalendarToolchainInstallFailureCode.ACTIVATION_FAILED),
                        message=(
                            f"The {managed.field} directory could not be "
                            f"synchronised: {_error_detail(error)}."
                        ),
                        field=managed.field,
                        path=managed.destination.parent,
                    ),
                )

    return CalendarToolchainConfigurationResult(
        success=True,
        plan=plan,
        files_changed=tuple(changed),
        issues=(),
    )


def _managed_files(
    plan: CalendarToolchainConfigurationPlan,
) -> tuple[_ManagedConfigurationFile, ...]:
    """Return managed configuration files in deterministic order."""
    return (
        _ManagedConfigurationFile(
            field="khal_configuration",
            destination=plan.layout.khal_configuration,
            contents=plan.khal_contents,
        ),
        _ManagedConfigurationFile(
            field="vdirsyncer_configuration",
            destination=plan.layout.vdirsyncer_configuration,
            contents=plan.vdirsyncer_contents,
        ),
    )


def _validate_runtime_layout(
    layout: CalendarToolchainRuntimeLayout,
) -> CalendarToolchainInstallerIssue | None:
    """Require every runtime directory before configuration persistence."""
    for field, path in (
        ("configuration_directory", layout.configuration_directory),
        ("state_root", layout.state_root),
        ("vdirs", layout.vdirs),
        ("khal_state", layout.khal_state),
        ("vdirsyncer_status", layout.vdirsyncer_status),
    ):
        try:
            if path.is_symlink():
                return _filesystem_issue(
                    message=f"The {field} must not be a symbolic link.",
                    field=field,
                    path=path,
                )

            if not path.exists() or not path.is_dir():
                return _filesystem_issue(
                    message=(
                        f"The {field} must be a provisioned directory "
                        "before calendar configuration is written."
                    ),
                    field=field,
                    path=path,
                )
        except OSError as error:
            return _filesystem_issue(
                message=(
                    f"The {field} could not be inspected: {_error_detail(error)}."
                ),
                field=field,
                path=path,
            )

    return None


def _inspect_existing_file(
    managed: _ManagedConfigurationFile,
) -> CalendarToolchainInstallerIssue | None:
    """Accept identical regular files and reject unsafe differences."""
    try:
        if managed.destination.is_symlink():
            return _filesystem_issue(
                message=(f"The {managed.field} must not be a symbolic link."),
                field=managed.field,
                path=managed.destination,
            )

        if not managed.destination.exists():
            return None

        if not managed.destination.is_file():
            return _filesystem_issue(
                message=(f"The {managed.field} exists but is not a regular file."),
                field=managed.field,
                path=managed.destination,
            )

        current = managed.destination.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return _filesystem_issue(
            message=(f"The {managed.field} could not be read: {_error_detail(error)}."),
            field=managed.field,
            path=managed.destination,
        )

    if current != managed.contents:
        return _filesystem_issue(
            message=(
                f"The existing {managed.field} differs from the "
                "LEA-managed configuration and was not overwritten."
            ),
            field=managed.field,
            path=managed.destination,
        )

    return None


def _write_new_file(
    managed: _ManagedConfigurationFile,
    *,
    fsync: bool,
) -> CalendarToolchainInstallerIssue | None:
    """Atomically create one managed file without overwriting."""
    temporary_path: Path | None = None

    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{managed.destination.name}.",
            suffix=".tmp",
            dir=managed.destination.parent,
            text=True,
        )
        temporary_path = Path(temporary_name)

        with os.fdopen(
            descriptor,
            mode="w",
            encoding="utf-8",
            newline="\n",
        ) as stream:
            stream.write(managed.contents)
            stream.flush()

            if fsync:
                os.fsync(stream.fileno())

        temporary_path.chmod(_CONFIGURATION_FILE_MODE)
        os.link(temporary_path, managed.destination)
    except FileExistsError:
        return _filesystem_issue(
            message=(
                f"The {managed.field} appeared during persistence and "
                "was not overwritten."
            ),
            field=managed.field,
            path=managed.destination,
        )
    except OSError as error:
        return _filesystem_issue(
            message=(
                f"The {managed.field} could not be written: {_error_detail(error)}."
            ),
            field=managed.field,
            path=managed.destination,
        )
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)

    return None


def _record_change(
    changed: list[Path],
    path: Path,
) -> None:
    """Record one changed managed file exactly once."""
    if path not in changed:
        changed.append(path)


def _filesystem_issue(
    *,
    message: str,
    field: str,
    path: Path,
) -> CalendarToolchainInstallerIssue:
    """Create one structured configuration filesystem issue."""
    return CalendarToolchainInstallerIssue(
        code=CalendarToolchainInstallFailureCode.ACTIVATION_FAILED,
        message=message,
        field=field,
        path=path,
    )


def _failure(
    *,
    plan: CalendarToolchainConfigurationPlan | None,
    changed: list[Path],
    issue: CalendarToolchainInstallerIssue,
) -> CalendarToolchainConfigurationResult:
    """Create one failed managed-configuration result."""
    return CalendarToolchainConfigurationResult(
        success=False,
        plan=plan,
        files_changed=tuple(changed),
        issues=(issue,),
    )


def _validate_display_timezone(
    display_timezone: str,
) -> str:
    """Validate and normalise one IANA display timezone."""
    if not isinstance(display_timezone, str):
        raise TypeError("display_timezone must be a string.")

    value = display_timezone.strip()

    if not value:
        raise ValueError("display_timezone must be non-empty.")

    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError:
        raise ValueError(
            "display_timezone must be a recognised IANA timezone."
        ) from None

    return value


def _config_path(
    path: Path,
    *,
    field_name: str,
) -> str:
    """Render one safe unquoted configuration path."""
    _validate_absolute_path(path, field_name=field_name)
    rendered = str(path)

    if any(character in rendered for character in ("\x00", "\r", "\n")):
        raise ValueError(f"{field_name} contains an unsafe configuration character.")

    return rendered


def _quoted_config_path(
    path: Path,
    *,
    field_name: str,
) -> str:
    """Render one safe double-quoted configuration path."""
    rendered = _config_path(path, field_name=field_name)

    if '"' in rendered or "\\" in rendered:
        raise ValueError(f"{field_name} contains an unsupported quoted-path character.")

    return f'"{rendered}"'


def _fsync_directory(directory: Path) -> None:
    """Request filesystem synchronisation for one directory."""
    descriptor = os.open(directory, os.O_RDONLY)

    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _error_detail(error: BaseException) -> str:
    """Return bounded deterministic diagnostic text."""
    strerror = getattr(error, "strerror", None)

    if isinstance(strerror, str) and strerror:
        return strerror

    rendered = str(error).strip()
    return rendered or type(error).__name__


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
