"""Immutable Taskwarrior installer contracts."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class TaskwarriorInstallMode(StrEnum):
    """Supported Taskwarrior installation modes."""

    BUNDLED_BINARY = "bundled-binary"
    SOURCE_BUILD = "source-build"
    EXTERNAL_EXECUTABLE = "external-executable"


class TaskwarriorInstallFailureCode(StrEnum):
    """Reserved Taskwarrior installer failure codes."""

    INVALID_ARGUMENT = "taskwarrior_install_invalid_argument"
    PERMISSION_DENIED = "taskwarrior_install_permission_denied"
    UNSUPPORTED_PLATFORM = "taskwarrior_install_unsupported_platform"
    UNSUPPORTED_VERSION = "taskwarrior_install_unsupported_version"
    ARTEFACT_MISSING = "taskwarrior_install_artefact_missing"
    CHECKSUM_MISMATCH = "taskwarrior_install_checksum_mismatch"
    ARCHIVE_UNSAFE = "taskwarrior_install_archive_unsafe"
    DEPENDENCY_MISSING = "taskwarrior_install_dependency_missing"
    BUILD_FAILED = "taskwarrior_install_build_failed"
    BUILD_TIMEOUT = "taskwarrior_install_build_timeout"
    COPY_FAILED = "taskwarrior_install_copy_failed"
    VERSION_CHECK_FAILED = "taskwarrior_install_version_check_failed"
    SMOKE_TEST_FAILED = "taskwarrior_install_smoke_test_failed"
    ACTIVATION_FAILED = "taskwarrior_install_activation_failed"
    RECORD_FAILED = "taskwarrior_install_record_failed"
    ALREADY_INSTALLED = "taskwarrior_install_already_installed"


@dataclass(frozen=True, slots=True)
class TaskwarriorInstallerIssue:
    """One structured Taskwarrior installer issue."""

    code: TaskwarriorInstallFailureCode
    message: str
    field: str | None = None
    path: Path | None = None

    def __post_init__(self) -> None:
        """Validate structured issue fields."""
        if not self.message.strip():
            raise ValueError("message must be non-empty.")

        if self.field is not None and not self.field.strip():
            raise ValueError("field must be non-empty when provided.")

        if self.path is not None and not self.path.is_absolute():
            raise ValueError("path must be absolute when provided.")


@dataclass(frozen=True, slots=True)
class TaskwarriorInstallerConfig:
    """Immutable configuration for one Taskwarrior installation."""

    mode: TaskwarriorInstallMode
    version: str
    platform: str
    tools_root: Path
    configuration_dir: Path
    state_root: Path
    installation_record: Path
    service_user: str
    service_group: str
    artefact_path: Path | None = None
    source_archive: Path | None = None
    external_executable: Path | None = None
    expected_sha256: str | None = None
    build_directory: Path | None = None
    build_concurrency: int = 1
    non_interactive: bool = True

    def __post_init__(self) -> None:
        """Validate mode-independent and mode-specific configuration."""
        if not self.version.strip():
            raise ValueError("version must be non-empty.")

        if not self.platform.strip():
            raise ValueError("platform must be non-empty.")

        for field_name, required_path in (
            ("tools_root", self.tools_root),
            ("configuration_dir", self.configuration_dir),
            ("state_root", self.state_root),
            ("installation_record", self.installation_record),
        ):
            _validate_absolute_path(
                required_path,
                field_name=field_name,
            )

        for field_name, value in (
            ("service_user", self.service_user),
            ("service_group", self.service_group),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty.")

        if self.build_concurrency <= 0:
            raise ValueError("build_concurrency must be greater than zero.")

        optional_paths = (
            ("artefact_path", self.artefact_path),
            ("source_archive", self.source_archive),
            ("external_executable", self.external_executable),
            ("build_directory", self.build_directory),
        )

        for field_name, optional_path in optional_paths:
            if optional_path is not None:
                _validate_absolute_path(
                    optional_path,
                    field_name=field_name,
                )

        _validate_mode_specific_fields(self)


@dataclass(frozen=True, slots=True)
class TaskwarriorInstallerValidationResult:
    """Immutable result of validating installer configuration."""

    valid: bool
    config: TaskwarriorInstallerConfig | None
    issues: tuple[TaskwarriorInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate result consistency."""
        if self.valid:
            if self.config is None:
                raise ValueError("A valid result must contain installer configuration.")
            if self.issues:
                raise ValueError("A valid result must not contain issues.")
            return

        if self.config is not None:
            raise ValueError(
                "An invalid result must not contain installer configuration."
            )

        if not self.issues:
            raise ValueError("An invalid result must contain at least one issue.")


def _validate_mode_specific_fields(
    config: TaskwarriorInstallerConfig,
) -> None:
    """Validate exact fields required by the selected mode."""
    if config.mode is TaskwarriorInstallMode.BUNDLED_BINARY:
        _require_path(config.artefact_path, field_name="artefact_path")
        _require_checksum(config.expected_sha256)

        if config.source_archive is not None:
            raise ValueError("source_archive must not be set for bundled-binary mode.")

        if config.external_executable is not None:
            raise ValueError(
                "external_executable must not be set for bundled-binary mode."
            )

        return

    if config.mode is TaskwarriorInstallMode.SOURCE_BUILD:
        _require_path(config.source_archive, field_name="source_archive")
        _require_path(config.build_directory, field_name="build_directory")
        _require_checksum(config.expected_sha256)

        if config.artefact_path is not None:
            raise ValueError("artefact_path must not be set for source-build mode.")

        if config.external_executable is not None:
            raise ValueError(
                "external_executable must not be set for source-build mode."
            )

        return

    _require_path(
        config.external_executable,
        field_name="external_executable",
    )

    if config.artefact_path is not None:
        raise ValueError("artefact_path must not be set for external-executable mode.")

    if config.source_archive is not None:
        raise ValueError("source_archive must not be set for external-executable mode.")

    if config.expected_sha256 is not None:
        raise ValueError(
            "expected_sha256 must not be set for external-executable mode."
        )


def _require_path(
    path: Path | None,
    *,
    field_name: str,
) -> None:
    """Require one absolute path."""
    if path is None:
        raise ValueError(f"{field_name} is required.")

    _validate_absolute_path(path, field_name=field_name)


def _require_checksum(value: str | None) -> None:
    """Require one checksum value."""
    if value is None or not value.strip():
        raise ValueError("expected_sha256 is required.")


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
