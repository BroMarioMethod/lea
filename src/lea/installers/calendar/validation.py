"""Validation helpers for calendar toolchain installer configuration."""

import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit

from lea.installers.calendar.contracts import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallerValidationResult,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
)

_SUPPORTED_PLATFORM_ALIASES = {
    "x86_64": "linux-x86_64",
    "amd64": "linux-x86_64",
    "linux-x86_64": "linux-x86_64",
    "aarch64": "linux-aarch64",
    "arm64": "linux-aarch64",
    "linux-aarch64": "linux-aarch64",
}

_SUPPORTED_KHAL_VERSION = "0.11.4"
_SUPPORTED_VDIRSYNCER_VERSION = "0.19.3"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def normalise_calendar_platform(
    value: str,
) -> str | None:
    """Normalise one supported calendar-toolchain platform alias."""
    if not isinstance(value, str):
        raise TypeError("value must be a string.")

    return _SUPPORTED_PLATFORM_ALIASES.get(value.strip().lower())


def is_supported_khal_version(
    value: str,
) -> bool:
    """Return whether one khal version is supported."""
    if not isinstance(value, str):
        raise TypeError("value must be a string.")

    return value.strip() == _SUPPORTED_KHAL_VERSION


def is_supported_vdirsyncer_version(
    value: str,
) -> bool:
    """Return whether one vdirsyncer version is supported."""
    if not isinstance(value, str):
        raise TypeError("value must be a string.")

    return value.strip() == _SUPPORTED_VDIRSYNCER_VERSION


def is_valid_calendar_sha256(
    value: str,
) -> bool:
    """Return whether one checksum is lower-case SHA-256 text."""
    if not isinstance(value, str):
        raise TypeError("value must be a string.")

    return _SHA256_PATTERN.fullmatch(value.strip()) is not None


def is_valid_https_package_index_url(
    value: str,
) -> bool:
    """Return whether one package-index URL is explicit and HTTPS-only."""
    if not isinstance(value, str):
        raise TypeError("value must be a string.")

    candidate = value.strip()

    try:
        parsed = urlsplit(candidate)
        _ = parsed.port
    except ValueError:
        return False

    return (
        parsed.scheme.lower() == "https"
        and parsed.hostname is not None
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def validate_calendar_executable_path(
    path: Path,
    *,
    field_name: str,
    tool_name: str,
) -> tuple[CalendarToolchainInstallerIssue, ...]:
    """Validate one explicitly configured calendar-tool executable."""
    if not isinstance(path, Path):
        raise TypeError("path must be a pathlib.Path value.")

    if not isinstance(field_name, str) or not field_name.strip():
        raise ValueError("field_name must be non-empty.")

    if not isinstance(tool_name, str) or not tool_name.strip():
        raise ValueError("tool_name must be non-empty.")

    if not path.is_absolute():
        return (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=f"The {tool_name} executable path must be absolute.",
                field=field_name,
            ),
        )

    try:
        if not path.exists():
            return (
                CalendarToolchainInstallerIssue(
                    code=CalendarToolchainInstallFailureCode.ARTEFACT_MISSING,
                    message=f"The {tool_name} executable does not exist.",
                    field=field_name,
                    path=path,
                ),
            )

        if not path.is_file():
            return (
                CalendarToolchainInstallerIssue(
                    code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                    message=f"The {tool_name} executable is not a regular file.",
                    field=field_name,
                    path=path,
                ),
            )

        if not path.stat().st_mode & 0o111:
            return (
                CalendarToolchainInstallerIssue(
                    code=CalendarToolchainInstallFailureCode.PERMISSION_DENIED,
                    message=f"The {tool_name} executable is not executable.",
                    field=field_name,
                    path=path,
                ),
            )
    except OSError:
        return (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.PERMISSION_DENIED,
                message=f"The {tool_name} executable could not be inspected.",
                field=field_name,
                path=path,
            ),
        )

    return ()


def validate_calendar_toolchain_installer_config(
    config: CalendarToolchainInstallerConfig,
) -> CalendarToolchainInstallerValidationResult:
    """Validate one immutable calendar toolchain installer configuration."""
    if not isinstance(config, CalendarToolchainInstallerConfig):
        raise TypeError("config must be a CalendarToolchainInstallerConfig value.")

    issues: list[CalendarToolchainInstallerIssue] = []
    canonical_platform = normalise_calendar_platform(config.platform)

    if canonical_platform is None:
        issues.append(
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.UNSUPPORTED_PLATFORM,
                message="The requested calendar toolchain platform is unsupported.",
                field="platform",
            )
        )

    if not is_supported_khal_version(config.khal_version):
        issues.append(
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.UNSUPPORTED_VERSION,
                message="The requested khal version is unsupported.",
                field="khal_version",
            )
        )

    if not is_supported_vdirsyncer_version(config.vdirsyncer_version):
        issues.append(
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.UNSUPPORTED_VERSION,
                message="The requested vdirsyncer version is unsupported.",
                field="vdirsyncer_version",
            )
        )

    if config.mode in (
        CalendarToolchainInstallMode.VERIFIED_NETWORK,
        CalendarToolchainInstallMode.BUNDLED_WHEELHOUSE,
    ):
        _validate_managed_inputs(
            config,
            issues=issues,
        )

    if config.mode is CalendarToolchainInstallMode.VERIFIED_NETWORK:
        package_index_url = config.package_index_url

        if package_index_url is None or not is_valid_https_package_index_url(
            package_index_url
        ):
            issues.append(
                CalendarToolchainInstallerIssue(
                    code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                    message=(
                        "The package index URL must be an explicit HTTPS URL "
                        "without credentials, query text or a fragment."
                    ),
                    field="package_index_url",
                )
            )

    if config.mode is CalendarToolchainInstallMode.BUNDLED_WHEELHOUSE:
        _validate_hashed_file(
            config.wheelhouse_archive,
            expected_sha256=config.expected_wheelhouse_sha256,
            field_name="wheelhouse_archive",
            checksum_field="expected_wheelhouse_sha256",
            label="calendar wheelhouse archive",
            issues=issues,
        )

    if config.mode is CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES:
        _validate_external_inputs(
            config,
            issues=issues,
        )

    if issues:
        return CalendarToolchainInstallerValidationResult(
            valid=False,
            config=None,
            issues=tuple(issues),
        )

    if canonical_platform is None:
        raise RuntimeError("Validated platform unexpectedly remained unresolved.")

    normalised = CalendarToolchainInstallerConfig(
        mode=config.mode,
        toolchain_version=config.toolchain_version.strip(),
        khal_version=config.khal_version.strip(),
        vdirsyncer_version=config.vdirsyncer_version.strip(),
        platform=canonical_platform,
        tools_root=config.tools_root,
        configuration_dir=config.configuration_dir,
        state_root=config.state_root,
        installation_record=config.installation_record,
        service_user=config.service_user.strip(),
        service_group=config.service_group.strip(),
        uv_executable=config.uv_executable,
        python_executable=config.python_executable,
        requirements_lock=config.requirements_lock,
        expected_lock_sha256=(
            config.expected_lock_sha256.strip()
            if config.expected_lock_sha256 is not None
            else None
        ),
        package_index_url=(
            config.package_index_url.strip()
            if config.package_index_url is not None
            else None
        ),
        wheelhouse_archive=config.wheelhouse_archive,
        expected_wheelhouse_sha256=(
            config.expected_wheelhouse_sha256.strip()
            if config.expected_wheelhouse_sha256 is not None
            else None
        ),
        external_khal_executable=config.external_khal_executable,
        external_vdirsyncer_executable=(config.external_vdirsyncer_executable),
        timeout_seconds=float(config.timeout_seconds),
        non_interactive=config.non_interactive,
    )

    return CalendarToolchainInstallerValidationResult(
        valid=True,
        config=normalised,
        issues=(),
    )


def _validate_managed_inputs(
    config: CalendarToolchainInstallerConfig,
    *,
    issues: list[CalendarToolchainInstallerIssue],
) -> None:
    """Validate exact executables and the locked requirements document."""
    _extend_executable_issues(
        config.uv_executable,
        field_name="uv_executable",
        tool_name="uv",
        issues=issues,
    )
    _extend_executable_issues(
        config.python_executable,
        field_name="python_executable",
        tool_name="Python",
        issues=issues,
    )
    _validate_hashed_file(
        config.requirements_lock,
        expected_sha256=config.expected_lock_sha256,
        field_name="requirements_lock",
        checksum_field="expected_lock_sha256",
        label="calendar requirements lock",
        issues=issues,
    )


def _validate_external_inputs(
    config: CalendarToolchainInstallerConfig,
    *,
    issues: list[CalendarToolchainInstallerIssue],
) -> None:
    """Validate exact administrator-selected calendar executables."""
    _extend_executable_issues(
        config.external_khal_executable,
        field_name="external_khal_executable",
        tool_name="external khal",
        issues=issues,
    )
    _extend_executable_issues(
        config.external_vdirsyncer_executable,
        field_name="external_vdirsyncer_executable",
        tool_name="external vdirsyncer",
        issues=issues,
    )


def _extend_executable_issues(
    path: Path | None,
    *,
    field_name: str,
    tool_name: str,
    issues: list[CalendarToolchainInstallerIssue],
) -> None:
    """Append executable-path issues without assuming contract invariants."""
    if path is None:
        issues.append(
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=f"The {tool_name} executable path is missing.",
                field=field_name,
            )
        )
        return

    issues.extend(
        validate_calendar_executable_path(
            path,
            field_name=field_name,
            tool_name=tool_name,
        )
    )


def _validate_hashed_file(
    path: Path | None,
    *,
    expected_sha256: str | None,
    field_name: str,
    checksum_field: str,
    label: str,
    issues: list[CalendarToolchainInstallerIssue],
) -> None:
    """Validate one exact regular file and its expected SHA-256 digest."""
    if path is None:
        issues.append(
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=f"The {label} path is missing.",
                field=field_name,
            )
        )
        return

    if expected_sha256 is None or not is_valid_calendar_sha256(expected_sha256):
        issues.append(
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=(
                    f"The expected {label} checksum must be lower-case SHA-256 text."
                ),
                field=checksum_field,
                path=path,
            )
        )
        return

    try:
        if not path.exists():
            issues.append(
                CalendarToolchainInstallerIssue(
                    code=CalendarToolchainInstallFailureCode.ARTEFACT_MISSING,
                    message=f"The {label} does not exist.",
                    field=field_name,
                    path=path,
                )
            )
            return

        if not path.is_file():
            issues.append(
                CalendarToolchainInstallerIssue(
                    code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                    message=f"The {label} is not a regular file.",
                    field=field_name,
                    path=path,
                )
            )
            return

        actual_sha256 = _calculate_sha256(path)
    except OSError:
        issues.append(
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.PERMISSION_DENIED,
                message=f"The {label} could not be read.",
                field=field_name,
                path=path,
            )
        )
        return

    if actual_sha256 != expected_sha256:
        issues.append(
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.CHECKSUM_MISMATCH,
                message=f"The {label} checksum did not match.",
                field=checksum_field,
                path=path,
            )
        )


def _calculate_sha256(path: Path) -> str:
    """Calculate one file's lower-case SHA-256 digest."""
    digest = hashlib.sha256()

    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()
