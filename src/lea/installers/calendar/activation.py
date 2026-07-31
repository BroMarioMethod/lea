"""Atomic activation of verified managed calendar toolchains."""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from lea.installers.calendar.contracts import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
)
from lea.installers.calendar.ownership import (
    CalendarOwnershipApplier,
    ignore_calendar_ownership,
)
from lea.installers.calendar.preflight import (
    calculate_calendar_sha256,
)
from lea.installers.calendar.staging import (
    CalendarToolchainStagingLayout,
)
from lea.installers.calendar.version_check import (
    validate_calendar_tool_versions,
)

_DIRECTORY_MODE = 0o750
_EXECUTABLE_MODE = 0o750
_REGULAR_FILE_MODE = 0o640


@dataclass(frozen=True, slots=True)
class CalendarToolchainActivatedLayout:
    """Exact paths exposed by one activated managed toolchain."""

    toolchain_root: Path
    environment_root: Path
    python_executable: Path
    khal_executable: Path
    vdirsyncer_executable: Path

    def __post_init__(self) -> None:
        """Validate canonical absolute path relationships."""
        for field_name, path in (
            ("toolchain_root", self.toolchain_root),
            ("environment_root", self.environment_root),
            ("python_executable", self.python_executable),
            ("khal_executable", self.khal_executable),
            ("vdirsyncer_executable", self.vdirsyncer_executable),
        ):
            _validate_absolute_path(path, field_name=field_name)

        if self.environment_root != self.toolchain_root / ".venv":
            raise ValueError("environment_root must be the activated .venv path.")

        expected_bin = self.environment_root / "bin"

        if self.python_executable != expected_bin / "python":
            raise ValueError(
                "python_executable must be inside the activated environment."
            )

        if self.khal_executable != expected_bin / "khal":
            raise ValueError(
                "khal_executable must be inside the activated environment."
            )

        if self.vdirsyncer_executable != expected_bin / "vdirsyncer":
            raise ValueError(
                "vdirsyncer_executable must be inside the activated environment."
            )


@dataclass(frozen=True, slots=True)
class CalendarToolchainActivationResult:
    """Result of atomically activating one verified calendar toolchain."""

    success: bool
    changed: bool
    activated: CalendarToolchainActivatedLayout | None
    issues: tuple[CalendarToolchainInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate activation-result consistency."""
        if not isinstance(self.success, bool):
            raise TypeError("success must be a boolean.")

        if not isinstance(self.changed, bool):
            raise TypeError("changed must be a boolean.")

        if self.success:
            if self.activated is None:
                raise ValueError(
                    "A successful activation must contain its final layout."
                )

            if not self.changed:
                raise ValueError(
                    "A successful new activation must report a filesystem change."
                )

            if self.issues:
                raise ValueError("A successful activation must not contain issues.")

            return

        if self.activated is not None:
            raise ValueError("A failed activation must not expose an activated layout.")

        if not self.issues:
            raise ValueError("A failed activation must contain at least one issue.")


def activate_staged_calendar_toolchain(
    config: CalendarToolchainInstallerConfig,
    staged: CalendarToolchainStagingLayout,
    *,
    fsync: bool = False,
    apply_ownership: CalendarOwnershipApplier = (ignore_calendar_ownership),
) -> CalendarToolchainActivationResult:
    """Move one verified relocatable toolchain into its versioned root."""
    if not isinstance(config, CalendarToolchainInstallerConfig):
        raise TypeError("config must be a CalendarToolchainInstallerConfig value.")

    if not isinstance(staged, CalendarToolchainStagingLayout):
        raise TypeError("staged must be a CalendarToolchainStagingLayout value.")

    if config.mode is CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES:
        return _failure(
            changed=False,
            issue=CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=(
                    "External-executables mode does not activate a managed "
                    "calendar toolchain."
                ),
                field="mode",
            ),
        )

    final_root_issue, final_root = _final_toolchain_root(config)

    if final_root_issue is not None or final_root is None:
        return _failure(
            changed=False,
            issue=final_root_issue
            or CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message="The final calendar toolchain root is invalid.",
                field="toolchain_version",
            ),
        )

    relationship_issue = _validate_staging_relationship(
        config=config,
        staged=staged,
    )

    if relationship_issue is not None:
        return _failure(
            changed=False,
            issue=relationship_issue,
        )

    tools_root_issue = _inspect_tools_root(config.tools_root)

    if tools_root_issue is not None:
        return _failure(
            changed=False,
            issue=tools_root_issue,
        )

    if final_root.is_symlink() or final_root.exists():
        return _failure(
            changed=False,
            issue=CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.ALREADY_INSTALLED,
                message=(
                    "The target calendar toolchain version already exists "
                    "and was not replaced."
                ),
                field="toolchain_version",
                path=final_root,
            ),
        )

    staged_issue = _inspect_managed_toolchain(
        toolchain_root=staged.toolchain_root,
        environment_root=staged.environment_root,
        khal_executable=staged.khal_executable,
        vdirsyncer_executable=staged.vdirsyncer_executable,
        trusted_python=config.python_executable,
    )

    if staged_issue is not None:
        return _failure(
            changed=False,
            issue=staged_issue,
        )

    activated = CalendarToolchainActivatedLayout(
        toolchain_root=final_root,
        environment_root=final_root / ".venv",
        python_executable=final_root / ".venv" / "bin" / "python",
        khal_executable=final_root / ".venv" / "bin" / "khal",
        vdirsyncer_executable=(final_root / ".venv" / "bin" / "vdirsyncer"),
    )

    moved = False

    try:
        os.replace(staged.toolchain_root, final_root)
        moved = True

        versions = validate_calendar_tool_versions(
            khal_executable=activated.khal_executable,
            expected_khal_version=config.khal_version,
            vdirsyncer_executable=activated.vdirsyncer_executable,
            expected_vdirsyncer_version=config.vdirsyncer_version,
            working_directory=activated.toolchain_root,
            timeout_seconds=config.timeout_seconds,
        )

        if not versions.passed:
            rollback_issue = _rollback_activated_toolchain(final_root)

            if rollback_issue is None:
                return CalendarToolchainActivationResult(
                    success=False,
                    changed=False,
                    activated=None,
                    issues=versions.issues,
                )

            return CalendarToolchainActivationResult(
                success=False,
                changed=True,
                activated=None,
                issues=(*versions.issues, rollback_issue),
            )

        _normalise_activated_toolchain(
            tools_root=config.tools_root,
            activated=activated,
            service_group=config.service_group,
            trusted_python=config.python_executable,
            apply_ownership=apply_ownership,
        )

        if fsync:
            _fsync_directory(config.tools_root)
    except (KeyError, OSError) as error:
        activation_issue = CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.ACTIVATION_FAILED,
            message=(
                "The staged calendar toolchain could not be activated: "
                f"{_error_detail(error)}."
            ),
            field="tools_root",
            path=final_root,
        )

        if not moved:
            return _failure(
                changed=False,
                issue=activation_issue,
            )

        rollback_issue = _rollback_activated_toolchain(final_root)

        if rollback_issue is None:
            return _failure(
                changed=False,
                issue=activation_issue,
            )

        return CalendarToolchainActivationResult(
            success=False,
            changed=True,
            activated=None,
            issues=(activation_issue, rollback_issue),
        )

    return CalendarToolchainActivationResult(
        success=True,
        changed=True,
        activated=activated,
        issues=(),
    )


def _final_toolchain_root(
    config: CalendarToolchainInstallerConfig,
) -> tuple[
    CalendarToolchainInstallerIssue | None,
    Path | None,
]:
    """Resolve one safe direct child of the managed tools root."""
    component = Path(config.toolchain_version)

    if (
        component.name != config.toolchain_version
        or config.toolchain_version in {".", ".."}
        or component.is_absolute()
    ):
        return (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=("toolchain_version must be one safe filesystem component."),
                field="toolchain_version",
            ),
            None,
        )

    final_root = config.tools_root / config.toolchain_version

    if final_root.parent != config.tools_root:
        return (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=(
                    "The final calendar toolchain root must be directly "
                    "inside tools_root."
                ),
                field="toolchain_version",
                path=final_root,
            ),
            None,
        )

    return None, final_root


def _validate_staging_relationship(
    *,
    config: CalendarToolchainInstallerConfig,
    staged: CalendarToolchainStagingLayout,
) -> CalendarToolchainInstallerIssue | None:
    """Require staging to belong to the same managed installation."""
    if staged.staging_parent != config.tools_root:
        return CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
            message=(
                "The staged layout does not belong to the configured "
                "calendar tools root."
            ),
            field="tools_root",
            path=staged.staging_root,
        )

    if staged.staging_root.parent != config.tools_root:
        return CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
            message=("The calendar staging root is outside the configured tools root."),
            field="staging_root",
            path=staged.staging_root,
        )

    if staged.toolchain_root.parent != staged.staging_root:
        return CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
            message=("The staged calendar toolchain root has an invalid relationship."),
            field="toolchain_root",
            path=staged.toolchain_root,
        )

    expected_lock_sha256 = config.expected_lock_sha256

    if (
        expected_lock_sha256 is None
        or staged.requirements_lock_sha256 != expected_lock_sha256
    ):
        return CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.CHECKSUM_MISMATCH,
            message=(
                "The staged calendar lock checksum does not match the "
                "requested installation."
            ),
            field="expected_lock_sha256",
            path=staged.requirements_lock,
        )

    try:
        if (
            staged.requirements_lock.is_symlink()
            or not staged.requirements_lock.is_file()
        ):
            return CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.LOCK_INVALID,
                message=(
                    "The staged calendar requirements lock is not a "
                    "regular managed file."
                ),
                field="requirements_lock",
                path=staged.requirements_lock,
            )

        actual_lock_sha256 = calculate_calendar_sha256(staged.requirements_lock)
    except OSError as error:
        return CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.PERMISSION_DENIED,
            message=(
                "The staged calendar requirements lock could not be "
                f"rechecked: {_error_detail(error)}."
            ),
            field="requirements_lock",
            path=staged.requirements_lock,
        )

    if actual_lock_sha256 != expected_lock_sha256:
        return CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.CHECKSUM_MISMATCH,
            message=(
                "The staged calendar requirements lock changed before activation."
            ),
            field="expected_lock_sha256",
            path=staged.requirements_lock,
        )

    return None


def _inspect_tools_root(
    tools_root: Path,
) -> CalendarToolchainInstallerIssue | None:
    """Require the existing real directory created by staging."""
    try:
        if tools_root.is_symlink():
            return CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.ACTIVATION_FAILED,
                message="The calendar tools root must not be a symbolic link.",
                field="tools_root",
                path=tools_root,
            )

        if not tools_root.exists() or not tools_root.is_dir():
            return CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.ACTIVATION_FAILED,
                message=(
                    "The calendar tools root must be an existing real "
                    "directory before activation."
                ),
                field="tools_root",
                path=tools_root,
            )
    except OSError as error:
        return CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.ACTIVATION_FAILED,
            message=(
                "The calendar tools root could not be inspected: "
                f"{_error_detail(error)}."
            ),
            field="tools_root",
            path=tools_root,
        )

    return None


def _inspect_managed_toolchain(
    *,
    toolchain_root: Path,
    environment_root: Path,
    khal_executable: Path,
    vdirsyncer_executable: Path,
    trusted_python: Path | None,
) -> CalendarToolchainInstallerIssue | None:
    """Reject unsafe staged or activated toolchain filesystem content."""
    for field, directory in (
        ("toolchain_root", toolchain_root),
        ("environment_root", environment_root),
    ):
        try:
            if directory.is_symlink():
                return _activation_issue(
                    message=f"The {field} must not be a symbolic link.",
                    field=field,
                    path=directory,
                )

            if not directory.exists() or not directory.is_dir():
                return _activation_issue(
                    message=f"The {field} is not a real directory.",
                    field=field,
                    path=directory,
                )
        except OSError as error:
            return _activation_issue(
                message=(
                    f"The {field} could not be inspected: {_error_detail(error)}."
                ),
                field=field,
                path=directory,
            )

    for field, executable in (
        ("khal_executable", khal_executable),
        ("vdirsyncer_executable", vdirsyncer_executable),
    ):
        issue = _inspect_expected_executable(
            executable,
            field=field,
        )

        if issue is not None:
            return issue

    try:
        candidates = (
            toolchain_root,
            *sorted(toolchain_root.rglob("*")),
        )

        for candidate in candidates:
            if candidate.is_symlink():
                issue = _inspect_environment_symlink(
                    candidate,
                    environment_root=environment_root,
                    trusted_python=trusted_python,
                )

                if issue is not None:
                    return issue

                continue

            if candidate.is_dir() or candidate.is_file():
                continue

            return _activation_issue(
                message=(
                    "The managed calendar toolchain contains an "
                    "unsupported special filesystem object."
                ),
                field="toolchain_root",
                path=candidate,
            )
    except OSError as error:
        return _activation_issue(
            message=(
                "The managed calendar toolchain could not be inspected: "
                f"{_error_detail(error)}."
            ),
            field="toolchain_root",
            path=toolchain_root,
        )

    return None


def _inspect_expected_executable(
    executable: Path,
    *,
    field: str,
) -> CalendarToolchainInstallerIssue | None:
    """Require one regular non-symbolic executable."""
    try:
        if executable.is_symlink():
            return _activation_issue(
                message=f"The {field} must not be a symbolic link.",
                field=field,
                path=executable,
            )

        if not executable.exists() or not executable.is_file():
            return _activation_issue(
                message=f"The {field} is not a regular file.",
                field=field,
                path=executable,
            )

        if not executable.stat().st_mode & 0o111:
            return _activation_issue(
                message=f"The {field} is not executable.",
                field=field,
                path=executable,
            )
    except OSError as error:
        return _activation_issue(
            message=(f"The {field} could not be inspected: {_error_detail(error)}."),
            field=field,
            path=executable,
        )

    return None


def _inspect_environment_symlink(
    candidate: Path,
    *,
    environment_root: Path,
    trusted_python: Path | None,
) -> CalendarToolchainInstallerIssue | None:
    """Allow only uv's expected interpreter and lib64 links."""
    try:
        target_text = os.readlink(candidate)
        target = Path(target_text)

        if candidate == environment_root / "lib64":
            if target_text == "lib":
                return None

            return _activation_issue(
                message=(
                    "The activated lib64 link does not target the "
                    "environment lib directory."
                ),
                field="environment_root",
                path=candidate,
            )

        expected_bin = environment_root / "bin"

        if candidate.parent != expected_bin or not candidate.name.startswith("python"):
            return _activation_issue(
                message=(
                    "The managed calendar toolchain contains an "
                    "unexpected symbolic link."
                ),
                field="toolchain_root",
                path=candidate,
            )

        if target.is_absolute():
            if trusted_python is None:
                return _activation_issue(
                    message=(
                        "The activated Python link cannot be checked "
                        "without a trusted interpreter path."
                    ),
                    field="python_executable",
                    path=candidate,
                )

            if target.resolve() != trusted_python.resolve():
                return _activation_issue(
                    message=(
                        "The activated Python link does not target the "
                        "trusted interpreter."
                    ),
                    field="python_executable",
                    path=candidate,
                )

            return None

        if (
            target.name != target_text
            or target_text in {".", ".."}
            or not target.name.startswith("python")
        ):
            return _activation_issue(
                message=(
                    "The relative Python link escapes the activated "
                    "environment bin directory."
                ),
                field="python_executable",
                path=candidate,
            )
    except OSError as error:
        return _activation_issue(
            message=(
                "The activated environment link could not be inspected: "
                f"{_error_detail(error)}."
            ),
            field="environment_root",
            path=candidate,
        )

    return None


def _normalise_activated_toolchain(
    *,
    tools_root: Path,
    activated: CalendarToolchainActivatedLayout,
    service_group: str,
    trusted_python: Path | None,
    apply_ownership: CalendarOwnershipApplier,
) -> None:
    """Apply canonical modes and ownership without following symlinks."""
    issue = _inspect_managed_toolchain(
        toolchain_root=activated.toolchain_root,
        environment_root=activated.environment_root,
        khal_executable=activated.khal_executable,
        vdirsyncer_executable=activated.vdirsyncer_executable,
        trusted_python=trusted_python,
    )

    if issue is not None:
        raise OSError(issue.message)

    for candidate in (
        activated.toolchain_root,
        *sorted(activated.toolchain_root.rglob("*")),
    ):
        if candidate.is_symlink():
            continue

        if candidate.is_dir():
            candidate.chmod(_DIRECTORY_MODE)
        elif candidate.is_file():
            current_mode = candidate.stat().st_mode

            if current_mode & 0o111:
                candidate.chmod(_EXECUTABLE_MODE)
            else:
                candidate.chmod(_REGULAR_FILE_MODE)
        else:
            raise OSError(
                "The activated calendar toolchain contains an "
                "unsupported filesystem object."
            )

        apply_ownership(candidate, "root", service_group)

    tools_root.chmod(_DIRECTORY_MODE)
    apply_ownership(tools_root, "root", service_group)


def rollback_activated_calendar_toolchain(
    config: CalendarToolchainInstallerConfig,
    activated: CalendarToolchainActivatedLayout,
) -> tuple[CalendarToolchainInstallerIssue, ...]:
    """Remove only the exact newly activated managed toolchain."""
    if not isinstance(config, CalendarToolchainInstallerConfig):
        raise TypeError("config must be a CalendarToolchainInstallerConfig value.")

    if not isinstance(activated, CalendarToolchainActivatedLayout):
        raise TypeError("activated must be a CalendarToolchainActivatedLayout value.")

    if config.mode is CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES:
        return (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=(
                    "External-executables mode has no managed calendar "
                    "toolchain activation to roll back."
                ),
                field="mode",
            ),
        )

    final_root_issue, expected_root = _final_toolchain_root(config)

    if final_root_issue is not None or expected_root is None:
        return (
            final_root_issue
            or CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=("The configured calendar toolchain root is invalid."),
                field="toolchain_version",
            ),
        )

    if activated.toolchain_root != expected_root:
        return (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=(
                    "The activated calendar layout does not match the "
                    "configured versioned toolchain root."
                ),
                field="tools_root",
                path=activated.toolchain_root,
            ),
        )

    issue = _rollback_activated_toolchain(activated.toolchain_root)

    if issue is None:
        return ()

    return (issue,)


def _rollback_activated_toolchain(
    final_root: Path,
) -> CalendarToolchainInstallerIssue | None:
    """Remove only the newly moved versioned toolchain root."""
    try:
        shutil.rmtree(final_root)
    except FileNotFoundError:
        return None
    except OSError as error:
        return CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.ACTIVATION_FAILED,
            message=(
                "The failed calendar activation could not be rolled back: "
                f"{_error_detail(error)}."
            ),
            field="tools_root",
            path=final_root,
        )

    return None


def _activation_issue(
    *,
    message: str,
    field: str,
    path: Path,
) -> CalendarToolchainInstallerIssue:
    """Create one structured activation issue."""
    return CalendarToolchainInstallerIssue(
        code=CalendarToolchainInstallFailureCode.ACTIVATION_FAILED,
        message=message,
        field=field,
        path=path,
    )


def _failure(
    *,
    changed: bool,
    issue: CalendarToolchainInstallerIssue,
) -> CalendarToolchainActivationResult:
    """Create one failed activation result."""
    return CalendarToolchainActivationResult(
        success=False,
        changed=changed,
        activated=None,
        issues=(issue,),
    )


def _fsync_directory(directory: Path) -> None:
    """Request filesystem synchronisation for one directory."""
    descriptor = os.open(directory, os.O_RDONLY)

    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _error_detail(error: BaseException) -> str:
    """Return bounded filesystem or account-lookup diagnostics."""
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
