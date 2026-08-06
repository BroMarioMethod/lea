"""Immutable calendar toolchain installer contracts."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class CalendarToolchainInstallMode(StrEnum):
    """Supported calendar toolchain installation modes."""

    VERIFIED_NETWORK = "verified-network"
    BUNDLED_WHEELHOUSE = "bundled-wheelhouse"
    EXTERNAL_EXECUTABLES = "external-executables"


class CalendarToolchainInstallFailureCode(StrEnum):
    """Reserved calendar toolchain installer failure codes."""

    INVALID_ARGUMENT = "calendar_toolchain_install_invalid_argument"
    PERMISSION_DENIED = "calendar_toolchain_install_permission_denied"
    UNSUPPORTED_PLATFORM = "calendar_toolchain_install_unsupported_platform"
    UNSUPPORTED_VERSION = "calendar_toolchain_install_unsupported_version"
    ARTEFACT_MISSING = "calendar_toolchain_install_artefact_missing"
    CHECKSUM_MISMATCH = "calendar_toolchain_install_checksum_mismatch"
    ARCHIVE_UNSAFE = "calendar_toolchain_install_archive_unsafe"
    MANIFEST_INVALID = "calendar_toolchain_install_manifest_invalid"
    LOCK_INVALID = "calendar_toolchain_install_lock_invalid"
    DEPENDENCY_MISSING = "calendar_toolchain_install_dependency_missing"
    DOWNLOAD_FAILED = "calendar_toolchain_install_download_failed"
    ENVIRONMENT_CREATION_FAILED = (
        "calendar_toolchain_install_environment_creation_failed"
    )
    PACKAGE_INSTALL_FAILED = "calendar_toolchain_install_package_install_failed"
    INSTALL_TIMEOUT = "calendar_toolchain_install_timeout"
    COPY_FAILED = "calendar_toolchain_install_copy_failed"
    VERSION_CHECK_FAILED = "calendar_toolchain_install_version_check_failed"
    SMOKE_TEST_FAILED = "calendar_toolchain_install_smoke_test_failed"
    ACTIVATION_FAILED = "calendar_toolchain_install_activation_failed"
    RECORD_FAILED = "calendar_toolchain_install_record_failed"
    ALREADY_INSTALLED = "calendar_toolchain_install_already_installed"


@dataclass(frozen=True, slots=True)
class CalendarToolchainInstallerIssue:
    """One structured calendar toolchain installer issue."""

    code: CalendarToolchainInstallFailureCode
    message: str
    field: str | None = None
    path: Path | None = None

    def __post_init__(self) -> None:
        """Validate structured issue fields."""
        if not isinstance(self.code, CalendarToolchainInstallFailureCode):
            raise TypeError("code must be a CalendarToolchainInstallFailureCode value.")

        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message must be non-empty.")

        if self.field is not None and (
            not isinstance(self.field, str) or not self.field.strip()
        ):
            raise ValueError("field must be non-empty when provided.")

        if self.path is not None:
            _validate_absolute_path(
                self.path,
                field_name="path",
            )


@dataclass(frozen=True, slots=True)
class CalendarToolchainInstallerConfig:
    """Immutable configuration for one calendar toolchain installation."""

    mode: CalendarToolchainInstallMode
    toolchain_version: str
    khal_version: str
    vdirsyncer_version: str
    platform: str
    tools_root: Path
    configuration_dir: Path
    state_root: Path
    installation_record: Path
    service_user: str
    service_group: str
    uv_executable: Path | None = None
    python_executable: Path | None = None
    requirements_lock: Path | None = None
    expected_lock_sha256: str | None = None
    package_index_url: str | None = None
    wheelhouse_archive: Path | None = None
    expected_wheelhouse_sha256: str | None = None
    external_khal_executable: Path | None = None
    external_vdirsyncer_executable: Path | None = None
    timeout_seconds: float = 600.0
    non_interactive: bool = True

    def __post_init__(self) -> None:
        """Validate mode-independent and mode-specific configuration."""
        if not isinstance(self.mode, CalendarToolchainInstallMode):
            raise TypeError("mode must be a CalendarToolchainInstallMode value.")

        for field_name, value in (
            ("toolchain_version", self.toolchain_version),
            ("khal_version", self.khal_version),
            ("vdirsyncer_version", self.vdirsyncer_version),
            ("platform", self.platform),
            ("service_user", self.service_user),
            ("service_group", self.service_group),
        ):
            _validate_non_empty_string(
                value,
                field_name=field_name,
            )

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

        for field_name, optional_path in (
            ("uv_executable", self.uv_executable),
            ("python_executable", self.python_executable),
            ("requirements_lock", self.requirements_lock),
            ("wheelhouse_archive", self.wheelhouse_archive),
            ("external_khal_executable", self.external_khal_executable),
            (
                "external_vdirsyncer_executable",
                self.external_vdirsyncer_executable,
            ),
        ):
            if optional_path is not None:
                _validate_absolute_path(
                    optional_path,
                    field_name=field_name,
                )

        if self.package_index_url is not None:
            _validate_non_empty_string(
                self.package_index_url,
                field_name="package_index_url",
            )

        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds,
            (int, float),
        ):
            raise TypeError("timeout_seconds must be a number.")

        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")

        if not isinstance(self.non_interactive, bool):
            raise TypeError("non_interactive must be a boolean.")

        _validate_mode_specific_fields(self)


@dataclass(frozen=True, slots=True)
class CalendarToolchainInstallerValidationResult:
    """Immutable result of validating installer configuration."""

    valid: bool
    config: CalendarToolchainInstallerConfig | None
    issues: tuple[CalendarToolchainInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate result consistency."""
        if not isinstance(self.valid, bool):
            raise TypeError("valid must be a boolean.")

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
    config: CalendarToolchainInstallerConfig,
) -> None:
    """Validate exact fields required by the selected mode."""
    if config.mode is CalendarToolchainInstallMode.VERIFIED_NETWORK:
        _require_managed_environment_inputs(config)
        _require_non_empty_string(
            config.package_index_url,
            field_name="package_index_url",
        )
        _reject_wheelhouse_inputs(config)
        _reject_external_executables(config)
        return

    if config.mode is CalendarToolchainInstallMode.BUNDLED_WHEELHOUSE:
        _require_managed_environment_inputs(config)
        _require_path(
            config.wheelhouse_archive,
            field_name="wheelhouse_archive",
        )
        _require_sha256(
            config.expected_wheelhouse_sha256,
            field_name="expected_wheelhouse_sha256",
        )

        if config.package_index_url is not None:
            raise ValueError(
                "package_index_url must not be set for bundled-wheelhouse mode."
            )

        _reject_external_executables(config)
        return

    _require_path(
        config.external_khal_executable,
        field_name="external_khal_executable",
    )
    _require_path(
        config.external_vdirsyncer_executable,
        field_name="external_vdirsyncer_executable",
    )
    _reject_managed_environment_inputs(config)


def _require_managed_environment_inputs(
    config: CalendarToolchainInstallerConfig,
) -> None:
    """Require inputs shared by managed online and offline installation."""
    _require_path(
        config.uv_executable,
        field_name="uv_executable",
    )
    _require_path(
        config.python_executable,
        field_name="python_executable",
    )
    _require_path(
        config.requirements_lock,
        field_name="requirements_lock",
    )
    _require_sha256(
        config.expected_lock_sha256,
        field_name="expected_lock_sha256",
    )


def _reject_wheelhouse_inputs(
    config: CalendarToolchainInstallerConfig,
) -> None:
    """Reject offline-only inputs from verified-network mode."""
    if config.wheelhouse_archive is not None:
        raise ValueError(
            "wheelhouse_archive must not be set for verified-network mode."
        )

    if config.expected_wheelhouse_sha256 is not None:
        raise ValueError(
            "expected_wheelhouse_sha256 must not be set for verified-network mode."
        )


def _reject_external_executables(
    config: CalendarToolchainInstallerConfig,
) -> None:
    """Reject external executable paths from managed modes."""
    if config.external_khal_executable is not None:
        raise ValueError("external_khal_executable must not be set for managed modes.")

    if config.external_vdirsyncer_executable is not None:
        raise ValueError(
            "external_vdirsyncer_executable must not be set for managed modes."
        )


def _reject_managed_environment_inputs(
    config: CalendarToolchainInstallerConfig,
) -> None:
    """Reject managed-environment fields from external mode."""
    forbidden_values = (
        ("uv_executable", config.uv_executable),
        ("python_executable", config.python_executable),
        ("requirements_lock", config.requirements_lock),
        ("expected_lock_sha256", config.expected_lock_sha256),
        ("package_index_url", config.package_index_url),
        ("wheelhouse_archive", config.wheelhouse_archive),
        (
            "expected_wheelhouse_sha256",
            config.expected_wheelhouse_sha256,
        ),
    )

    for field_name, value in forbidden_values:
        if value is not None:
            raise ValueError(
                f"{field_name} must not be set for external-executables mode."
            )


def _require_path(
    path: Path | None,
    *,
    field_name: str,
) -> None:
    """Require one absolute path."""
    if path is None:
        raise ValueError(f"{field_name} is required.")

    _validate_absolute_path(
        path,
        field_name=field_name,
    )


def _require_sha256(
    value: str | None,
    *,
    field_name: str,
) -> None:
    """Require one canonical lower-case SHA-256 value."""
    if value is None:
        raise ValueError(f"{field_name} is required.")

    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")

    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{field_name} must be lower-case hexadecimal SHA-256 text.")


def _require_non_empty_string(
    value: str | None,
    *,
    field_name: str,
) -> None:
    """Require one non-empty string."""
    if value is None:
        raise ValueError(f"{field_name} is required.")

    _validate_non_empty_string(
        value,
        field_name=field_name,
    )


def _validate_non_empty_string(
    value: str,
    *,
    field_name: str,
) -> None:
    """Validate one non-empty string."""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")

    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty.")


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
