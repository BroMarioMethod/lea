"""Non-mutating host preflight for release-candidate installation."""

from __future__ import annotations

import grp
import os
import platform
import pwd
import shutil
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from lea.installers.release_candidate.contracts import (
    InstallerIssue,
    InstallerIssueCode,
    InstallerStepId,
    ReleaseCandidateInstallMode,
    ReleaseCandidateInstallRequest,
)


class HostPreflightCheckState(StrEnum):
    """Possible states for one host preflight check."""

    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class HostFacts:
    """Immutable facts collected from one installation host."""

    operating_system_id: str
    operating_system_version: str
    architecture: str
    python_version: tuple[int, int, int]
    systemd_available: bool
    dietpi_available: bool
    required_executables: tuple[Path, ...]
    missing_executables: tuple[Path, ...]
    service_user_exists: bool
    service_group_exists: bool
    managed_paths_present: tuple[Path, ...]

    def __post_init__(self) -> None:
        """Validate collected host facts."""
        if not self.operating_system_id.strip():
            raise ValueError("operating_system_id must be non-empty.")

        if not self.operating_system_version.strip():
            raise ValueError("operating_system_version must be non-empty.")

        if not self.architecture.strip():
            raise ValueError("architecture must be non-empty.")

        if len(self.python_version) != 3 or any(
            component < 0 for component in self.python_version
        ):
            raise ValueError("python_version must contain three non-negative values.")

        for field_name, paths in (
            ("required_executables", self.required_executables),
            ("missing_executables", self.missing_executables),
            ("managed_paths_present", self.managed_paths_present),
        ):
            for path in paths:
                _validate_absolute_path(path, field_name=field_name)

        if len(set(self.required_executables)) != len(self.required_executables):
            raise ValueError("required_executables must not contain duplicates.")

        if len(set(self.missing_executables)) != len(self.missing_executables):
            raise ValueError("missing_executables must not contain duplicates.")

        if not set(self.missing_executables).issubset(self.required_executables):
            raise ValueError(
                "missing_executables must be a subset of required_executables."
            )

        if len(set(self.managed_paths_present)) != len(self.managed_paths_present):
            raise ValueError("managed_paths_present must not contain duplicates.")


@dataclass(frozen=True, slots=True)
class HostPreflightCheck:
    """One deterministic host preflight check result."""

    name: str
    state: HostPreflightCheckState
    message: str
    field: str | None = None
    path: Path | None = None

    def __post_init__(self) -> None:
        """Validate check fields."""
        if not self.name.strip():
            raise ValueError("name must be non-empty.")

        if not self.message.strip():
            raise ValueError("message must be non-empty.")

        if self.field is not None and not self.field.strip():
            raise ValueError("field must be non-empty when provided.")

        if self.path is not None:
            _validate_absolute_path(self.path, field_name="path")


@dataclass(frozen=True, slots=True)
class HostPreflightResult:
    """Complete non-mutating host preflight result."""

    supported: bool
    facts: HostFacts
    checks: tuple[HostPreflightCheck, ...]
    issues: tuple[InstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate result consistency."""
        failed = tuple(
            check
            for check in self.checks
            if check.state is HostPreflightCheckState.FAILED
        )

        if self.supported:
            if failed:
                raise ValueError("A supported result must not contain failed checks.")
            if self.issues:
                raise ValueError("A supported result must not contain issues.")
            return

        if not failed:
            raise ValueError("An unsupported result must contain a failed check.")

        if not self.issues:
            raise ValueError("An unsupported result must contain at least one issue.")


_REQUIRED_EXECUTABLES = (
    Path("/usr/bin/bash"),
    Path("/usr/bin/git"),
    Path("/usr/bin/python3"),
    Path("/usr/bin/sudo"),
    Path("/usr/bin/systemctl"),
)

_MANAGED_PATHS = (
    Path("/opt/lea"),
    Path("/etc/lea"),
    Path("/var/lib/lea"),
    Path("/var/log/lea"),
    Path("/etc/systemd/system/lea-telegram.service"),
)

_SUPPORTED_ARCHITECTURES = frozenset({"aarch64", "arm64"})
_MINIMUM_PYTHON_VERSION = (3, 12, 0)


def collect_host_facts() -> HostFacts:
    """Collect host facts without mutating the system."""
    os_release = _read_os_release(Path("/etc/os-release"))
    required = _REQUIRED_EXECUTABLES
    missing = tuple(path for path in required if not _executable_available(path))

    return HostFacts(
        operating_system_id=os_release.get("ID", "unknown"),
        operating_system_version=os_release.get("VERSION_ID", "unknown"),
        architecture=platform.machine(),
        python_version=(
            sys.version_info.major,
            sys.version_info.minor,
            sys.version_info.micro,
        ),
        systemd_available=Path("/run/systemd/system").is_dir(),
        dietpi_available=Path("/boot/dietpi/.version").is_file(),
        required_executables=required,
        missing_executables=missing,
        service_user_exists=_user_exists("lea"),
        service_group_exists=_group_exists("lea"),
        managed_paths_present=tuple(path for path in _MANAGED_PATHS if path.exists()),
    )


def evaluate_host_preflight(
    request: ReleaseCandidateInstallRequest,
    facts: HostFacts,
) -> HostPreflightResult:
    """Evaluate collected host facts against release-candidate policy."""
    if not isinstance(request, ReleaseCandidateInstallRequest):
        raise TypeError("request must be a ReleaseCandidateInstallRequest value.")

    if not isinstance(facts, HostFacts):
        raise TypeError("facts must be a HostFacts value.")

    checks: list[HostPreflightCheck] = []
    issues: list[InstallerIssue] = []

    _record_check(
        checks,
        issues,
        name="operating_system",
        passed=facts.operating_system_id == "debian",
        success_message=(
            f"Supported Debian host detected: {facts.operating_system_version}."
        ),
        failure_message=(
            "The release candidate currently supports Debian-family DietPi hosts."
        ),
        field="operating_system_id",
    )
    _record_check(
        checks,
        issues,
        name="architecture",
        passed=facts.architecture in _SUPPORTED_ARCHITECTURES,
        success_message=f"Supported architecture detected: {facts.architecture}.",
        failure_message=(
            "The release candidate currently supports 64-bit ARM hosts only."
        ),
        field="architecture",
    )
    _record_check(
        checks,
        issues,
        name="python_version",
        passed=facts.python_version >= _MINIMUM_PYTHON_VERSION,
        success_message=(
            "Supported Python version detected: "
            f"{_format_version(facts.python_version)}."
        ),
        failure_message="Python 3.12 or newer is required.",
        field="python_version",
    )
    _record_check(
        checks,
        issues,
        name="systemd",
        passed=facts.systemd_available,
        success_message="systemd is available.",
        failure_message="systemd is required as the service manager.",
        field="systemd_available",
    )
    _record_check(
        checks,
        issues,
        name="dietpi",
        passed=facts.dietpi_available,
        success_message="DietPi installation markers are present.",
        failure_message="DietPi installation markers are missing.",
        field="dietpi_available",
    )

    for executable in facts.required_executables:
        missing = executable in facts.missing_executables
        _record_check(
            checks,
            issues,
            name=f"executable:{executable.name}",
            passed=not missing,
            success_message=f"Required executable is available: {executable}.",
            failure_message=f"Required executable is missing: {executable}.",
            path=executable,
        )

    existing_installation = bool(
        facts.managed_paths_present
        or facts.service_user_exists
        or facts.service_group_exists
    )
    fresh_install_conflict = (
        request.mode is ReleaseCandidateInstallMode.FRESH_INSTALL
        and existing_installation
    )

    if fresh_install_conflict:
        checks.append(
            HostPreflightCheck(
                name="existing_installation",
                state=HostPreflightCheckState.FAILED,
                message=(
                    "Fresh-install mode found existing LEA users, groups or "
                    "managed paths."
                ),
                field="mode",
            )
        )
        issues.append(
            InstallerIssue(
                code=InstallerIssueCode.EXISTING_INSTALLATION,
                message=(
                    "Fresh-install mode cannot continue over an existing LEA "
                    "installation."
                ),
                step=InstallerStepId.PREFLIGHT,
                field="mode",
            )
        )
    else:
        state = (
            HostPreflightCheckState.WARNING
            if existing_installation
            else HostPreflightCheckState.PASSED
        )
        message = (
            "Existing LEA installation markers were detected and are permitted "
            f"for {request.mode.value} mode."
            if existing_installation
            else "No existing LEA installation markers were detected."
        )
        checks.append(
            HostPreflightCheck(
                name="existing_installation",
                state=state,
                message=message,
                field="mode",
            )
        )

    supported = not any(
        check.state is HostPreflightCheckState.FAILED for check in checks
    )

    return HostPreflightResult(
        supported=supported,
        facts=facts,
        checks=tuple(checks),
        issues=tuple(issues),
    )


def run_host_preflight(
    request: ReleaseCandidateInstallRequest,
) -> HostPreflightResult:
    """Collect and evaluate host facts without mutation."""
    return evaluate_host_preflight(request, collect_host_facts())


def _record_check(
    checks: list[HostPreflightCheck],
    issues: list[InstallerIssue],
    *,
    name: str,
    passed: bool,
    success_message: str,
    failure_message: str,
    field: str | None = None,
    path: Path | None = None,
) -> None:
    """Append one check and matching issue when required."""
    checks.append(
        HostPreflightCheck(
            name=name,
            state=(
                HostPreflightCheckState.PASSED
                if passed
                else HostPreflightCheckState.FAILED
            ),
            message=success_message if passed else failure_message,
            field=field,
            path=path,
        )
    )

    if not passed:
        issues.append(
            InstallerIssue(
                code=InstallerIssueCode.PREFLIGHT_FAILED,
                message=failure_message,
                step=InstallerStepId.PREFLIGHT,
                field=field,
                path=path,
            )
        )


def _read_os_release(path: Path) -> dict[str, str]:
    """Read simple key-value operating-system metadata."""
    try:
        contents = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {}

    values: dict[str, str] = {}
    for line in contents.splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')

    return values


def _user_exists(name: str) -> bool:
    """Return whether one local user exists."""
    try:
        pwd.getpwnam(name)
    except KeyError:
        return False
    return True


def _group_exists(name: str) -> bool:
    """Return whether one local group exists."""
    try:
        grp.getgrnam(name)
    except KeyError:
        return False
    return True


def _executable_available(path: Path) -> bool:
    """Return whether one exact executable path is usable."""
    return (
        path.is_file()
        and os.access(path, os.X_OK)
        and shutil.which(path.name) is not None
    )


def _format_version(version: tuple[int, int, int]) -> str:
    """Render one three-part version."""
    return ".".join(str(component) for component in version)


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
