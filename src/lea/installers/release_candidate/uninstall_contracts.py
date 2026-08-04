"""Immutable contracts for release-candidate uninstallation."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class ReleaseCandidateUninstallStepId(StrEnum):
    """Stable release-candidate uninstall step identifiers."""

    SYSTEMD_SERVICE = "systemd-service"
    RUNTIME_RESOURCES = "runtime-resources"
    TASKWARRIOR = "taskwarrior"
    CALENDAR_TOOLCHAIN = "calendar-toolchain"
    CONFIGURATION = "configuration"
    STATE = "state"
    LOGS = "logs"
    SYSTEM_ACCOUNT = "system-account"


class ReleaseCandidateUninstallStepState(StrEnum):
    """Possible states for one uninstall step."""

    PLANNED = "planned"
    SKIPPED = "skipped"
    COMPLETED = "completed"
    FAILED = "failed"


class ReleaseCandidateUninstallIssueCode(StrEnum):
    """Stable release-candidate uninstall issue codes."""

    INVALID_ARGUMENT = "release_candidate_uninstall_invalid_argument"
    PERMISSION_DENIED = "release_candidate_uninstall_permission_denied"
    UNSAFE_PATH = "release_candidate_uninstall_unsafe_path"
    STEP_FAILED = "release_candidate_uninstall_step_failed"
    INCOMPLETE = "release_candidate_uninstall_incomplete"


class ReleaseCandidateUninstallMutationKind(StrEnum):
    """Kinds of destructive uninstall mutation."""

    STOP_SERVICE = "stop-service"
    DISABLE_SERVICE = "disable-service"
    REMOVE_FILE = "remove-file"
    REMOVE_DIRECTORY = "remove-directory"
    RELOAD_SERVICE_MANAGER = "reload-service-manager"
    REMOVE_USER = "remove-user"
    REMOVE_GROUP = "remove-group"


@dataclass(frozen=True, slots=True)
class ReleaseCandidateUninstallRequest:
    """Validated request for one release-candidate uninstall."""

    purge: bool
    confirmed: bool
    service_user: str = "lea"
    service_group: str = "lea"
    installation_root: Path = Path("/opt/lea")
    configuration_root: Path = Path("/etc/lea")
    state_root: Path = Path("/var/lib/lea")
    log_root: Path = Path("/var/log/lea")
    taskwarrior_root: Path = Path("/opt/lea-tools/taskwarrior")
    calendar_toolchain_root: Path = Path("/opt/lea-tools/calendar")
    systemd_unit: Path = Path("/etc/systemd/system/lea-telegram.service")
    tmpfiles_configuration: Path = Path("/etc/tmpfiles.d/lea.conf")
    runtime_directory: Path = Path("/run/lea")
    systemctl: Path = Path("/usr/bin/systemctl")

    def __post_init__(self) -> None:
        """Validate uninstall request fields."""
        if not self.purge:
            raise ValueError("purge must be true.")

        if not self.confirmed:
            raise ValueError("confirmed must be true.")

        for field_name, value in (
            ("service_user", self.service_user),
            ("service_group", self.service_group),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be non-empty.")

        for field_name, path in (
            ("installation_root", self.installation_root),
            ("configuration_root", self.configuration_root),
            ("state_root", self.state_root),
            ("log_root", self.log_root),
            ("taskwarrior_root", self.taskwarrior_root),
            ("calendar_toolchain_root", self.calendar_toolchain_root),
            ("systemd_unit", self.systemd_unit),
            ("tmpfiles_configuration", self.tmpfiles_configuration),
            ("runtime_directory", self.runtime_directory),
            ("systemctl", self.systemctl),
        ):
            _validate_absolute_path(path, field_name=field_name)

        protected = {
            Path("/"),
            Path("/opt"),
            Path("/etc"),
            Path("/var"),
            Path("/var/lib"),
            Path("/var/log"),
            self.installation_root,
        }
        destructive_roots = {
            self.configuration_root,
            self.state_root,
            self.log_root,
            self.taskwarrior_root,
            self.calendar_toolchain_root,
        }

        unsafe = destructive_roots & protected
        if unsafe:
            rendered = ", ".join(str(path) for path in sorted(unsafe, key=str))
            raise ValueError(f"Destructive uninstall paths are unsafe: {rendered}.")


@dataclass(frozen=True, slots=True)
class ReleaseCandidateUninstallMutation:
    """One deterministic destructive mutation."""

    kind: ReleaseCandidateUninstallMutationKind
    summary: str
    target: Path | None = None
    command: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        """Validate mutation fields."""
        if not self.summary.strip():
            raise ValueError("summary must be non-empty.")

        if self.target is None and self.command is None:
            raise ValueError("A mutation must contain a target or command.")

        if self.target is not None:
            _validate_absolute_path(self.target, field_name="target")

        if self.command is not None:
            if not self.command:
                raise ValueError("command must not be empty.")
            if not Path(self.command[0]).is_absolute():
                raise ValueError("command executable must be an absolute path.")


@dataclass(frozen=True, slots=True)
class ReleaseCandidateUninstallStepPlan:
    """Immutable plan for one uninstall step."""

    step: ReleaseCandidateUninstallStepId
    summary: str
    mutations: tuple[ReleaseCandidateUninstallMutation, ...]

    def __post_init__(self) -> None:
        """Validate step-plan consistency."""
        if not self.summary.strip():
            raise ValueError("summary must be non-empty.")

        if not self.mutations:
            raise ValueError("mutations must not be empty.")

        if len(set(self.mutations)) != len(self.mutations):
            raise ValueError("mutations must not contain duplicates.")


@dataclass(frozen=True, slots=True)
class ReleaseCandidateUninstallPlan:
    """Complete immutable release-candidate purge plan."""

    request: ReleaseCandidateUninstallRequest
    steps: tuple[ReleaseCandidateUninstallStepPlan, ...]

    def __post_init__(self) -> None:
        """Validate uninstall-plan consistency."""
        if not self.steps:
            raise ValueError("steps must not be empty.")

        step_ids = tuple(step.step for step in self.steps)
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("steps must not contain duplicate identifiers.")


@dataclass(frozen=True, slots=True)
class ReleaseCandidateUninstallIssue:
    """One structured release-candidate uninstall issue."""

    code: ReleaseCandidateUninstallIssueCode
    message: str
    step: ReleaseCandidateUninstallStepId | None = None
    path: Path | None = None

    def __post_init__(self) -> None:
        """Validate uninstall issue fields."""
        if not self.message.strip():
            raise ValueError("message must be non-empty.")

        if self.path is not None:
            _validate_absolute_path(self.path, field_name="path")


@dataclass(frozen=True, slots=True)
class ReleaseCandidateUninstallStepResult:
    """Result of executing one uninstall step."""

    step: ReleaseCandidateUninstallStepId
    state: ReleaseCandidateUninstallStepState
    message: str
    issues: tuple[ReleaseCandidateUninstallIssue, ...] = ()

    def __post_init__(self) -> None:
        """Validate uninstall step-result consistency."""
        if not self.message.strip():
            raise ValueError("message must be non-empty.")

        if self.state is ReleaseCandidateUninstallStepState.FAILED:
            if not self.issues:
                raise ValueError("A failed uninstall step must contain an issue.")
            return

        if self.issues:
            raise ValueError("A non-failed uninstall step must not contain issues.")


@dataclass(frozen=True, slots=True)
class ReleaseCandidateUninstallResult:
    """Complete result of one release-candidate purge attempt."""

    success: bool
    steps: tuple[ReleaseCandidateUninstallStepResult, ...]
    issues: tuple[ReleaseCandidateUninstallIssue, ...]

    def __post_init__(self) -> None:
        """Validate uninstall-result consistency."""
        if not self.steps:
            raise ValueError("steps must not be empty.")

        failed = tuple(
            step
            for step in self.steps
            if step.state is ReleaseCandidateUninstallStepState.FAILED
        )

        if self.success:
            if failed:
                raise ValueError(
                    "A successful uninstall must not contain failed steps."
                )
            if self.issues:
                raise ValueError("A successful uninstall must not contain issues.")
            return

        if not failed or not self.issues:
            raise ValueError(
                "An unsuccessful uninstall must contain failures and issues."
            )


def _validate_absolute_path(
    path: Path,
    *,
    field_name: str,
) -> None:
    """Validate one absolute filesystem path."""
    if not isinstance(path, Path):
        raise TypeError(f"{field_name} must be a pathlib.Path value.")

    if not path.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path.")

    if "\x00" in str(path):
        raise ValueError(f"{field_name} must not contain a null byte.")
