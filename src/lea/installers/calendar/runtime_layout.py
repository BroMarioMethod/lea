"""Safe managed runtime-directory provisioning for calendar tools."""

from dataclasses import dataclass
from pathlib import Path

from lea.installers.calendar.contracts import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallFailureCode,
)
from lea.installers.calendar.ownership import (
    CalendarOwnershipApplier,
    ignore_calendar_ownership,
)

_CONFIGURATION_DIRECTORY_MODE = 0o750
_STATE_DIRECTORY_MODE = 0o750


@dataclass(frozen=True, slots=True)
class CalendarToolchainRuntimeLayout:
    """Canonical LEA-managed calendar runtime paths."""

    configuration_directory: Path
    khal_configuration: Path
    vdirsyncer_configuration: Path
    state_root: Path
    vdirs: Path
    khal_state: Path
    vdirsyncer_status: Path

    def __post_init__(self) -> None:
        """Validate canonical absolute path relationships."""
        for field_name, path in (
            ("configuration_directory", self.configuration_directory),
            ("khal_configuration", self.khal_configuration),
            ("vdirsyncer_configuration", self.vdirsyncer_configuration),
            ("state_root", self.state_root),
            ("vdirs", self.vdirs),
            ("khal_state", self.khal_state),
            ("vdirsyncer_status", self.vdirsyncer_status),
        ):
            _validate_absolute_path(path, field_name=field_name)

        if self.khal_configuration != (self.configuration_directory / "khal.conf"):
            raise ValueError(
                "khal_configuration must be inside configuration_directory."
            )

        if self.vdirsyncer_configuration != (
            self.configuration_directory / "vdirsyncer.conf"
        ):
            raise ValueError(
                "vdirsyncer_configuration must be inside configuration_directory."
            )

        expected_state_paths = (
            ("vdirs", self.vdirs, self.state_root / "vdirs"),
            ("khal_state", self.khal_state, self.state_root / "khal"),
            (
                "vdirsyncer_status",
                self.vdirsyncer_status,
                self.state_root / "vdirsyncer-status",
            ),
        )

        for field_name, actual, expected in expected_state_paths:
            if actual != expected:
                raise ValueError(f"{field_name} must be inside state_root.")


@dataclass(frozen=True, slots=True)
class CalendarToolchainRuntimeLayoutResult:
    """Result of provisioning calendar runtime directories."""

    success: bool
    layout: CalendarToolchainRuntimeLayout | None
    directories_changed: tuple[Path, ...]
    issues: tuple[CalendarToolchainInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate result consistency and mutation reporting."""
        if not isinstance(self.success, bool):
            raise TypeError("success must be a boolean.")

        if len(set(self.directories_changed)) != len(self.directories_changed):
            raise ValueError("directories_changed must not contain duplicate paths.")

        for path in self.directories_changed:
            _validate_absolute_path(
                path,
                field_name="directories_changed",
            )

        if self.success:
            if self.layout is None:
                raise ValueError(
                    "A successful runtime-layout result must contain a layout."
                )

            if self.issues:
                raise ValueError(
                    "A successful runtime-layout result must not contain issues."
                )

            return

        if self.layout is not None:
            raise ValueError(
                "A failed runtime-layout result must not contain a layout."
            )

        if not self.issues:
            raise ValueError("A failed runtime-layout result must contain issues.")


@dataclass(frozen=True, slots=True)
class _ManagedDirectory:
    """One exact calendar runtime directory policy."""

    field: str
    path: Path
    owner: str
    group: str
    mode: int

    def __post_init__(self) -> None:
        """Validate one internal managed-directory policy."""
        if not self.field.strip():
            raise ValueError("field must be non-empty.")

        _validate_absolute_path(
            self.path,
            field_name="path",
        )

        for field_name, value in (
            ("owner", self.owner),
            ("group", self.group),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty.")

        if self.mode not in {
            _CONFIGURATION_DIRECTORY_MODE,
            _STATE_DIRECTORY_MODE,
        }:
            raise ValueError("mode is not a supported calendar policy.")


def create_calendar_toolchain_runtime_layout(
    config: CalendarToolchainInstallerConfig,
) -> CalendarToolchainRuntimeLayout:
    """Create the immutable canonical path model without mutating disk."""
    if not isinstance(config, CalendarToolchainInstallerConfig):
        raise TypeError("config must be a CalendarToolchainInstallerConfig value.")

    return CalendarToolchainRuntimeLayout(
        configuration_directory=config.configuration_dir,
        khal_configuration=config.configuration_dir / "khal.conf",
        vdirsyncer_configuration=(config.configuration_dir / "vdirsyncer.conf"),
        state_root=config.state_root,
        vdirs=config.state_root / "vdirs",
        khal_state=config.state_root / "khal",
        vdirsyncer_status=config.state_root / "vdirsyncer-status",
    )


def provision_calendar_toolchain_runtime_layout(
    config: CalendarToolchainInstallerConfig,
    *,
    apply_ownership: CalendarOwnershipApplier = (ignore_calendar_ownership),
) -> CalendarToolchainRuntimeLayoutResult:
    """Create or validate the LEA-managed calendar runtime directories."""
    layout = create_calendar_toolchain_runtime_layout(config)
    managed_directories = _managed_directories(
        config=config,
        layout=layout,
    )
    changed: list[Path] = []

    parent_issue = _validate_required_parent(
        field="configuration_dir_parent",
        path=config.configuration_dir.parent,
    )

    if parent_issue is not None:
        return _failure(
            changed=changed,
            issue=parent_issue,
        )

    parent_issue = _validate_required_parent(
        field="state_root_parent",
        path=config.state_root.parent,
    )

    if parent_issue is not None:
        return _failure(
            changed=changed,
            issue=parent_issue,
        )

    for managed in managed_directories:
        issue = _inspect_existing_directory(managed)

        if issue is not None:
            return _failure(
                changed=changed,
                issue=issue,
            )

    for managed in managed_directories:
        existed_before = managed.path.exists()

        try:
            managed.path.mkdir(
                mode=managed.mode,
                parents=False,
                exist_ok=True,
            )
        except OSError as error:
            return _failure(
                changed=changed,
                issue=_filesystem_issue(
                    message=(
                        f"The {managed.field} directory could not be "
                        f"provisioned: {_error_detail(error)}."
                    ),
                    field=managed.field,
                    path=managed.path,
                ),
            )

        issue = _inspect_existing_directory(managed)

        if issue is not None:
            return _failure(
                changed=changed,
                issue=issue,
            )

        if not existed_before:
            _record_change(changed, managed.path)

        try:
            current_mode = managed.path.stat().st_mode & 0o777

            if current_mode != managed.mode:
                managed.path.chmod(managed.mode)
                _record_change(changed, managed.path)

            ownership_changed = apply_ownership(
                managed.path,
                managed.owner,
                managed.group,
            )

            if ownership_changed:
                _record_change(changed, managed.path)
        except (KeyError, OSError) as error:
            return _failure(
                changed=changed,
                issue=_filesystem_issue(
                    message=(
                        f"The {managed.field} ownership or permissions "
                        f"could not be applied: {_error_detail(error)}."
                    ),
                    field=managed.field,
                    path=managed.path,
                ),
            )

    return CalendarToolchainRuntimeLayoutResult(
        success=True,
        layout=layout,
        directories_changed=tuple(changed),
        issues=(),
    )


def _managed_directories(
    *,
    config: CalendarToolchainInstallerConfig,
    layout: CalendarToolchainRuntimeLayout,
) -> tuple[_ManagedDirectory, ...]:
    """Return canonical runtime-directory policies in creation order."""
    return (
        _ManagedDirectory(
            field="configuration_dir",
            path=layout.configuration_directory,
            owner="root",
            group=config.service_group,
            mode=_CONFIGURATION_DIRECTORY_MODE,
        ),
        _ManagedDirectory(
            field="state_root",
            path=layout.state_root,
            owner=config.service_user,
            group=config.service_group,
            mode=_STATE_DIRECTORY_MODE,
        ),
        _ManagedDirectory(
            field="vdirs",
            path=layout.vdirs,
            owner=config.service_user,
            group=config.service_group,
            mode=_STATE_DIRECTORY_MODE,
        ),
        _ManagedDirectory(
            field="khal_state",
            path=layout.khal_state,
            owner=config.service_user,
            group=config.service_group,
            mode=_STATE_DIRECTORY_MODE,
        ),
        _ManagedDirectory(
            field="vdirsyncer_status",
            path=layout.vdirsyncer_status,
            owner=config.service_user,
            group=config.service_group,
            mode=_STATE_DIRECTORY_MODE,
        ),
    )


def _validate_required_parent(
    *,
    field: str,
    path: Path,
) -> CalendarToolchainInstallerIssue | None:
    """Require an existing non-symbolic parent owned by another boundary."""
    try:
        if path.is_symlink():
            return _filesystem_issue(
                message=f"The {field} must not be a symbolic link.",
                field=field,
                path=path,
            )

        if not path.exists():
            return _filesystem_issue(
                message=(
                    f"The {field} does not exist; the base LEA system "
                    "layout must be provisioned first."
                ),
                field=field,
                path=path,
            )

        if not path.is_dir():
            return _filesystem_issue(
                message=f"The {field} is not a directory.",
                field=field,
                path=path,
            )
    except OSError as error:
        return _filesystem_issue(
            message=(f"The {field} could not be inspected: {_error_detail(error)}."),
            field=field,
            path=path,
        )

    return None


def _inspect_existing_directory(
    managed: _ManagedDirectory,
) -> CalendarToolchainInstallerIssue | None:
    """Reject unsafe or incompatible existing runtime paths."""
    try:
        if managed.path.is_symlink():
            return _filesystem_issue(
                message=(f"The {managed.field} path must not be a symbolic link."),
                field=managed.field,
                path=managed.path,
            )

        if managed.path.exists() and not managed.path.is_dir():
            return _filesystem_issue(
                message=(f"The {managed.field} path exists but is not a directory."),
                field=managed.field,
                path=managed.path,
            )
    except OSError as error:
        return _filesystem_issue(
            message=(
                f"The {managed.field} path could not be inspected: "
                f"{_error_detail(error)}."
            ),
            field=managed.field,
            path=managed.path,
        )

    return None


def _record_change(
    changed: list[Path],
    path: Path,
) -> None:
    """Record one mutated directory exactly once in canonical order."""
    if path not in changed:
        changed.append(path)


def _filesystem_issue(
    *,
    message: str,
    field: str,
    path: Path,
) -> CalendarToolchainInstallerIssue:
    """Create one structured runtime-layout failure."""
    return CalendarToolchainInstallerIssue(
        code=CalendarToolchainInstallFailureCode.ACTIVATION_FAILED,
        message=message,
        field=field,
        path=path,
    )


def _failure(
    *,
    changed: list[Path],
    issue: CalendarToolchainInstallerIssue,
) -> CalendarToolchainRuntimeLayoutResult:
    """Create one failed runtime-layout result with mutation evidence."""
    return CalendarToolchainRuntimeLayoutResult(
        success=False,
        layout=None,
        directories_changed=tuple(changed),
        issues=(issue,),
    )


def _error_detail(error: BaseException) -> str:
    """Return bounded filesystem or account-lookup error text."""
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
