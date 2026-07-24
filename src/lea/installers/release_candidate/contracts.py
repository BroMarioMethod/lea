"""Immutable release-candidate installer contracts."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class ReleaseCandidateInstallMode(StrEnum):
    """Supported release-candidate installation modes."""

    FRESH_INSTALL = "fresh-install"
    UPGRADE = "upgrade"
    REPAIR = "repair"


class InstallerStepId(StrEnum):
    """Stable identifiers for release-candidate installer steps."""

    PREFLIGHT = "preflight"
    SYSTEM_ACCOUNT = "system-account"
    FILESYSTEM = "filesystem"
    BASE_CONFIGURATION = "base-configuration"
    TASKWARRIOR = "taskwarrior"
    TELEGRAM_ONBOARDING = "telegram-onboarding"
    TELEGRAM_CONFIGURATION = "telegram-configuration"
    SYSTEMD_SERVICE = "systemd-service"
    HEALTH = "health"
    ACCEPTANCE = "acceptance"


class InstallerStepState(StrEnum):
    """Possible states for one installer step."""

    PLANNED = "planned"
    SKIPPED = "skipped"
    COMPLETED = "completed"
    FAILED = "failed"


class InstallerMutationKind(StrEnum):
    """Kinds of privileged mutation that an installer may plan."""

    CREATE_GROUP = "create-group"
    CREATE_USER = "create-user"
    CREATE_DIRECTORY = "create-directory"
    WRITE_FILE = "write-file"
    INSTALL_COMPONENT = "install-component"
    INSTALL_SERVICE = "install-service"
    ENABLE_SERVICE = "enable-service"
    START_SERVICE = "start-service"


class InstallerIssueCode(StrEnum):
    """Reserved release-candidate installer issue codes."""

    INVALID_ARGUMENT = "release_candidate_install_invalid_argument"
    UNSUPPORTED_PLATFORM = "release_candidate_install_unsupported_platform"
    PERMISSION_DENIED = "release_candidate_install_permission_denied"
    EXISTING_INSTALLATION = "release_candidate_install_existing_installation"
    PREFLIGHT_FAILED = "release_candidate_install_preflight_failed"
    STEP_FAILED = "release_candidate_install_step_failed"
    ROLLBACK_FAILED = "release_candidate_install_rollback_failed"
    INCOMPLETE = "release_candidate_install_incomplete"


@dataclass(frozen=True, slots=True)
class InstallerMutation:
    """One deterministic, non-executing installer mutation description."""

    kind: InstallerMutationKind
    summary: str
    target: Path | None = None
    requires_root: bool = True

    def __post_init__(self) -> None:
        """Validate mutation fields."""
        if not self.summary.strip():
            raise ValueError("summary must be non-empty.")

        if self.target is not None:
            _validate_absolute_path(self.target, field_name="target")


@dataclass(frozen=True, slots=True)
class InstallerIssue:
    """One structured release-candidate installer issue."""

    code: InstallerIssueCode
    message: str
    step: InstallerStepId | None = None
    field: str | None = None
    path: Path | None = None

    def __post_init__(self) -> None:
        """Validate issue fields."""
        if not self.message.strip():
            raise ValueError("message must be non-empty.")

        if self.field is not None and not self.field.strip():
            raise ValueError("field must be non-empty when provided.")

        if self.path is not None:
            _validate_absolute_path(self.path, field_name="path")


@dataclass(frozen=True, slots=True)
class InstallerStepPlan:
    """Immutable plan for one installer step."""

    step: InstallerStepId
    summary: str
    mutations: tuple[InstallerMutation, ...]
    optional: bool = False

    def __post_init__(self) -> None:
        """Validate step-plan fields."""
        if not self.summary.strip():
            raise ValueError("summary must be non-empty.")

        if len(set(self.mutations)) != len(self.mutations):
            raise ValueError("mutations must not contain duplicates.")


@dataclass(frozen=True, slots=True)
class ReleaseCandidateInstallRequest:
    """Validated request for one release-candidate installation plan."""

    mode: ReleaseCandidateInstallMode
    display_timezone: str
    enable_telegram: bool
    non_interactive: bool = False
    service_user: str = "lea"
    service_group: str = "lea"
    installation_root: Path = Path("/opt/lea")
    configuration_root: Path = Path("/etc/lea")
    state_root: Path = Path("/var/lib/lea")
    log_root: Path = Path("/var/log/lea")

    def __post_init__(self) -> None:
        """Validate request fields."""
        if not self.display_timezone.strip():
            raise ValueError("display_timezone must be non-empty.")

        for field_name, value in (
            ("service_user", self.service_user),
            ("service_group", self.service_group),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty.")

        for field_name, path in (
            ("installation_root", self.installation_root),
            ("configuration_root", self.configuration_root),
            ("state_root", self.state_root),
            ("log_root", self.log_root),
        ):
            _validate_absolute_path(path, field_name=field_name)


@dataclass(frozen=True, slots=True)
class ReleaseCandidateInstallPlan:
    """Complete immutable, non-mutating release-candidate installation plan."""

    request: ReleaseCandidateInstallRequest
    steps: tuple[InstallerStepPlan, ...]

    def __post_init__(self) -> None:
        """Validate plan consistency."""
        if not self.steps:
            raise ValueError("steps must not be empty.")

        step_ids = tuple(step.step for step in self.steps)
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("steps must not contain duplicate step identifiers.")

        telegram_steps = {
            InstallerStepId.TELEGRAM_ONBOARDING,
            InstallerStepId.TELEGRAM_CONFIGURATION,
            InstallerStepId.SYSTEMD_SERVICE,
        }
        supplied = set(step_ids)

        if self.request.enable_telegram:
            missing = telegram_steps - supplied
            if missing:
                raise ValueError(
                    "Telegram-enabled plans must contain onboarding, "
                    "configuration and service steps."
                )
        elif telegram_steps & supplied:
            raise ValueError(
                "Telegram-disabled plans must not contain Telegram service steps."
            )


@dataclass(frozen=True, slots=True)
class InstallerStepResult:
    """Result of one installer step."""

    step: InstallerStepId
    state: InstallerStepState
    message: str
    issues: tuple[InstallerIssue, ...] = ()

    def __post_init__(self) -> None:
        """Validate step-result consistency."""
        if not self.message.strip():
            raise ValueError("message must be non-empty.")

        if self.state is InstallerStepState.FAILED:
            if not self.issues:
                raise ValueError("A failed step must contain at least one issue.")
            return

        if self.issues:
            raise ValueError("A non-failed step must not contain issues.")


@dataclass(frozen=True, slots=True)
class ReleaseCandidateInstallResult:
    """Complete result of one release-candidate installation attempt."""

    success: bool
    mode: ReleaseCandidateInstallMode
    steps: tuple[InstallerStepResult, ...]
    issues: tuple[InstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate installation-result consistency."""
        failed_steps = tuple(
            step for step in self.steps if step.state is InstallerStepState.FAILED
        )

        if self.success:
            if failed_steps:
                raise ValueError("A successful result must not contain failed steps.")
            if self.issues:
                raise ValueError("A successful result must not contain issues.")
            return

        if not failed_steps and not self.issues:
            raise ValueError(
                "An unsuccessful result must contain a failed step or issue."
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

    if "\x00" in str(path):
        raise ValueError(f"{field_name} must not contain a null byte.")
