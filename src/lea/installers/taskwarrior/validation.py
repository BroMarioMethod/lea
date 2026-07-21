"""Validation helpers for Taskwarrior installer configuration."""

import re
from pathlib import Path

from lea.installers.taskwarrior.contracts import (
    TaskwarriorInstallerConfig,
    TaskwarriorInstallerIssue,
    TaskwarriorInstallerValidationResult,
    TaskwarriorInstallFailureCode,
)

_SUPPORTED_PLATFORM_ALIASES = {
    "x86_64": "linux-x86_64",
    "amd64": "linux-x86_64",
    "linux-x86_64": "linux-x86_64",
    "aarch64": "linux-aarch64",
    "arm64": "linux-aarch64",
    "linux-aarch64": "linux-aarch64",
}

_SUPPORTED_VERSION_PATTERN = re.compile(r"^3\.4\.\d+$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def normalise_taskwarrior_platform(
    value: str,
) -> str | None:
    """Normalise one supported platform alias."""
    if not isinstance(value, str):
        raise TypeError("value must be a string.")

    return _SUPPORTED_PLATFORM_ALIASES.get(value.strip().lower())


def is_supported_taskwarrior_version(
    value: str,
) -> bool:
    """Return whether one Taskwarrior version is supported."""
    if not isinstance(value, str):
        raise TypeError("value must be a string.")

    return _SUPPORTED_VERSION_PATTERN.fullmatch(value.strip()) is not None


def is_valid_sha256(
    value: str,
) -> bool:
    """Return whether one checksum is lower-case SHA-256 text."""
    if not isinstance(value, str):
        raise TypeError("value must be a string.")

    return _SHA256_PATTERN.fullmatch(value.strip()) is not None


def validate_external_executable_path(
    path: Path,
) -> tuple[TaskwarriorInstallerIssue, ...]:
    """Validate one administrator-supplied executable path."""
    if not isinstance(path, Path):
        raise TypeError("path must be a pathlib.Path value.")

    issues: list[TaskwarriorInstallerIssue] = []

    if not path.is_absolute():
        issues.append(
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
                message=("The external Taskwarrior executable path must be absolute."),
                field="external_executable",
            )
        )
        return tuple(issues)

    if not path.exists():
        issues.append(
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.ARTEFACT_MISSING,
                message=("The external Taskwarrior executable does not exist."),
                field="external_executable",
                path=path,
            )
        )
        return tuple(issues)

    if not path.is_file():
        issues.append(
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
                message=("The external Taskwarrior executable is not a regular file."),
                field="external_executable",
                path=path,
            )
        )

    if path.is_file() and not path.stat().st_mode & 0o111:
        issues.append(
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.PERMISSION_DENIED,
                message=("The external Taskwarrior executable is not executable."),
                field="external_executable",
                path=path,
            )
        )

    return tuple(issues)


def validate_taskwarrior_installer_config(
    config: TaskwarriorInstallerConfig,
) -> TaskwarriorInstallerValidationResult:
    """Validate one immutable Taskwarrior installer configuration."""
    issues: list[TaskwarriorInstallerIssue] = []

    canonical_platform = normalise_taskwarrior_platform(config.platform)

    if canonical_platform is None:
        issues.append(
            TaskwarriorInstallerIssue(
                code=(TaskwarriorInstallFailureCode.UNSUPPORTED_PLATFORM),
                message="The requested Taskwarrior platform is unsupported.",
                field="platform",
            )
        )

    if not is_supported_taskwarrior_version(config.version):
        issues.append(
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.UNSUPPORTED_VERSION,
                message="The requested Taskwarrior version is unsupported.",
                field="version",
            )
        )

    if config.expected_sha256 is not None and not is_valid_sha256(
        config.expected_sha256
    ):
        issues.append(
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
                message=(
                    "The expected Taskwarrior checksum must be lower-case SHA-256 text."
                ),
                field="expected_sha256",
            )
        )

    if config.external_executable is not None:
        issues.extend(validate_external_executable_path(config.external_executable))

    if issues:
        return TaskwarriorInstallerValidationResult(
            valid=False,
            config=None,
            issues=tuple(issues),
        )

    if canonical_platform is None:
        raise RuntimeError("Validated platform unexpectedly remained unresolved.")

    normalised = TaskwarriorInstallerConfig(
        mode=config.mode,
        version=config.version.strip(),
        platform=canonical_platform,
        tools_root=config.tools_root,
        configuration_dir=config.configuration_dir,
        state_root=config.state_root,
        installation_record=config.installation_record,
        service_user=config.service_user.strip(),
        service_group=config.service_group.strip(),
        artefact_path=config.artefact_path,
        source_archive=config.source_archive,
        external_executable=config.external_executable,
        expected_sha256=(
            config.expected_sha256.strip()
            if config.expected_sha256 is not None
            else None
        ),
        build_directory=config.build_directory,
        build_concurrency=config.build_concurrency,
        non_interactive=config.non_interactive,
    )

    return TaskwarriorInstallerValidationResult(
        valid=True,
        config=normalised,
        issues=(),
    )
