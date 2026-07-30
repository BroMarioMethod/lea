"""Private staging for managed calendar toolchain installations."""

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from lea.installers.calendar.contracts import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
)
from lea.installers.calendar.preflight import calculate_calendar_sha256

_STAGING_PREFIX = ".calendar-"


@dataclass(frozen=True, slots=True)
class CalendarToolchainStagingLayout:
    """Paths reserved for one private managed-toolchain staging operation."""

    staging_parent: Path
    staging_root: Path
    toolchain_root: Path
    environment_root: Path
    khal_executable: Path
    vdirsyncer_executable: Path
    requirements_lock: Path
    requirements_lock_sha256: str
    wheelhouse_directory: Path | None

    def __post_init__(self) -> None:
        """Validate staging containment and deterministic path relationships."""
        for field_name, path in (
            ("staging_parent", self.staging_parent),
            ("staging_root", self.staging_root),
            ("toolchain_root", self.toolchain_root),
            ("environment_root", self.environment_root),
            ("khal_executable", self.khal_executable),
            ("vdirsyncer_executable", self.vdirsyncer_executable),
            ("requirements_lock", self.requirements_lock),
        ):
            _validate_absolute_path(path, field_name=field_name)

        if self.wheelhouse_directory is not None:
            _validate_absolute_path(
                self.wheelhouse_directory,
                field_name="wheelhouse_directory",
            )

        if self.staging_root.parent != self.staging_parent:
            raise ValueError("staging_root must be directly inside staging_parent.")

        if not self.staging_root.name.startswith(_STAGING_PREFIX):
            raise ValueError("staging_root must use the private calendar prefix.")

        if self.toolchain_root != self.staging_root / "toolchain":
            raise ValueError("toolchain_root must be inside staging_root.")

        if self.environment_root != self.toolchain_root / ".venv":
            raise ValueError("environment_root must be the staged .venv path.")

        expected_bin = self.environment_root / "bin"

        if self.khal_executable != expected_bin / "khal":
            raise ValueError("khal_executable must be inside the staged environment.")

        if self.vdirsyncer_executable != expected_bin / "vdirsyncer":
            raise ValueError(
                "vdirsyncer_executable must be inside the staged environment."
            )

        if self.requirements_lock != self.staging_root / "inputs" / "requirements.lock":
            raise ValueError("requirements_lock must use the staged inputs path.")

        if self.wheelhouse_directory is not None and (
            self.wheelhouse_directory != self.staging_root / "wheelhouse"
        ):
            raise ValueError(
                "wheelhouse_directory must use the staged wheelhouse path."
            )

        _validate_sha256(
            self.requirements_lock_sha256,
            field_name="requirements_lock_sha256",
        )


@dataclass(frozen=True, slots=True)
class CalendarToolchainStagingResult:
    """Result of provisioning one private calendar staging layout."""

    staged: CalendarToolchainStagingLayout | None
    issues: tuple[CalendarToolchainInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate success and failure consistency."""
        if self.staged is not None:
            if self.issues:
                raise ValueError("A successful staging result must not contain issues.")
            return

        if not self.issues:
            raise ValueError("A failed staging result must contain at least one issue.")


def create_calendar_toolchain_staging(
    config: CalendarToolchainInstallerConfig,
) -> CalendarToolchainStagingResult:
    """Create private managed staging without running uv or installing packages."""
    if not isinstance(config, CalendarToolchainInstallerConfig):
        raise TypeError("config must be a CalendarToolchainInstallerConfig value.")

    if config.mode is CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES:
        return _failure(
            code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
            message=(
                "External-executables mode does not use managed toolchain staging."
            ),
            field="mode",
        )

    source_lock = config.requirements_lock
    expected_sha256 = config.expected_lock_sha256

    if source_lock is None:
        return _failure(
            code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
            message="The calendar requirements lock path is missing.",
            field="requirements_lock",
        )

    if expected_sha256 is None:
        return _failure(
            code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
            message="The expected calendar requirements lock checksum is missing.",
            field="expected_lock_sha256",
            path=source_lock,
        )

    source_issue = _inspect_source_lock(
        source_lock,
        expected_sha256=expected_sha256,
    )

    if source_issue is not None:
        return CalendarToolchainStagingResult(
            staged=None,
            issues=(source_issue,),
        )

    staging_root: Path | None = None

    try:
        config.tools_root.mkdir(
            mode=0o750,
            parents=True,
            exist_ok=True,
        )

        if config.tools_root.is_symlink() or not config.tools_root.is_dir():
            return _failure(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message="The calendar tools root must be a real directory.",
                field="tools_root",
                path=config.tools_root,
            )

        staging_root = Path(
            tempfile.mkdtemp(
                prefix=_STAGING_PREFIX,
                dir=config.tools_root,
            )
        )
        staging_root.chmod(0o750)

        toolchain_root = staging_root / "toolchain"
        toolchain_root.mkdir(mode=0o750)

        inputs_directory = staging_root / "inputs"
        inputs_directory.mkdir(mode=0o750)

        staged_lock = inputs_directory / "requirements.lock"
        shutil.copyfile(source_lock, staged_lock)
        staged_lock.chmod(0o640)

        staged_sha256 = calculate_calendar_sha256(staged_lock)

        if staged_sha256 != expected_sha256:
            shutil.rmtree(staging_root, ignore_errors=True)
            staging_root = None
            return _failure(
                code=CalendarToolchainInstallFailureCode.CHECKSUM_MISMATCH,
                message=(
                    "The staged calendar requirements lock checksum did not "
                    "match the expected SHA-256 value."
                ),
                field="expected_lock_sha256",
                path=staged_lock,
            )

        wheelhouse_directory: Path | None = None

        if config.mode is CalendarToolchainInstallMode.BUNDLED_WHEELHOUSE:
            wheelhouse_directory = staging_root / "wheelhouse"
            wheelhouse_directory.mkdir(mode=0o750)

        environment_root = toolchain_root / ".venv"
        bin_directory = environment_root / "bin"

        return CalendarToolchainStagingResult(
            staged=CalendarToolchainStagingLayout(
                staging_parent=config.tools_root,
                staging_root=staging_root,
                toolchain_root=toolchain_root,
                environment_root=environment_root,
                khal_executable=bin_directory / "khal",
                vdirsyncer_executable=bin_directory / "vdirsyncer",
                requirements_lock=staged_lock,
                requirements_lock_sha256=staged_sha256,
                wheelhouse_directory=wheelhouse_directory,
            ),
            issues=(),
        )
    except OSError as error:
        if staging_root is not None:
            shutil.rmtree(staging_root, ignore_errors=True)

        return _failure(
            code=CalendarToolchainInstallFailureCode.COPY_FAILED,
            message=(
                "The private calendar staging layout could not be created: "
                f"{error.strerror or type(error).__name__}."
            ),
            field="tools_root",
            path=config.tools_root,
        )


def remove_calendar_toolchain_staging(
    staged: CalendarToolchainStagingLayout,
) -> tuple[CalendarToolchainInstallerIssue, ...]:
    """Remove one private staging root without touching activated versions."""
    if not isinstance(staged, CalendarToolchainStagingLayout):
        raise TypeError("staged must be a CalendarToolchainStagingLayout value.")

    root = staged.staging_root

    if root.parent != staged.staging_parent or not root.name.startswith(
        _STAGING_PREFIX
    ):
        return (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=(
                    "The calendar staging root is outside the private "
                    "staging namespace."
                ),
                field="staging_root",
                path=root,
            ),
        )

    if root.is_symlink():
        return (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message="The calendar staging root must not be a symbolic link.",
                field="staging_root",
                path=root,
            ),
        )

    try:
        shutil.rmtree(root)
    except FileNotFoundError:
        return ()
    except OSError as error:
        return (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.COPY_FAILED,
                message=(
                    "The calendar staging directory could not be removed: "
                    f"{error.strerror or type(error).__name__}."
                ),
                field="staging_root",
                path=root,
            ),
        )

    return ()


def _inspect_source_lock(
    path: Path,
    *,
    expected_sha256: str,
) -> CalendarToolchainInstallerIssue | None:
    """Recheck the source lock immediately before copying it into staging."""
    if path.is_symlink():
        return CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
            message=(
                "The calendar requirements lock must be a regular non-symbolic file."
            ),
            field="requirements_lock",
            path=path,
        )

    if not path.exists():
        return CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.ARTEFACT_MISSING,
            message="The calendar requirements lock does not exist.",
            field="requirements_lock",
            path=path,
        )

    if not path.is_file():
        return CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
            message="The calendar requirements lock is not a regular file.",
            field="requirements_lock",
            path=path,
        )

    try:
        actual_sha256 = calculate_calendar_sha256(path)
    except OSError:
        return CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.PERMISSION_DENIED,
            message="The calendar requirements lock could not be read.",
            field="requirements_lock",
            path=path,
        )

    if actual_sha256 != expected_sha256:
        return CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.CHECKSUM_MISMATCH,
            message=(
                "The calendar requirements lock checksum did not match before staging."
            ),
            field="expected_lock_sha256",
            path=path,
        )

    return None


def _failure(
    *,
    code: CalendarToolchainInstallFailureCode,
    message: str,
    field: str,
    path: Path | None = None,
) -> CalendarToolchainStagingResult:
    """Create one failed calendar staging result."""
    return CalendarToolchainStagingResult(
        staged=None,
        issues=(
            CalendarToolchainInstallerIssue(
                code=code,
                message=message,
                field=field,
                path=path,
            ),
        ),
    )


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


def _validate_sha256(
    value: str,
    *,
    field_name: str,
) -> None:
    """Validate one canonical lower-case SHA-256 value."""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")

    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{field_name} must be lower-case hexadecimal SHA-256 text.")
