"""Post-install health and acceptance checks for release candidates."""

from __future__ import annotations

import grp
import os
import pwd
import stat
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from lea.adapters.taskwarrior import TaskwarriorConfig, inspect_taskwarrior
from lea.channels import load_authorised_channel_users
from lea.installers.calendar.records import (
    CalendarToolchainInstallationRecord,
    read_calendar_toolchain_installation_record,
)
from lea.installers.calendar.smoke_test import (
    CalendarToolchainSmokeTestResult,
    run_calendar_toolchain_smoke_test,
)
from lea.installers.calendar.version_check import (
    CalendarToolchainVersionCheckResult,
    validate_calendar_tool_versions,
)
from lea.installers.release_candidate.configuration import (
    read_installation_record,
)
from lea.installers.release_candidate.contracts import (
    InstallerIssue,
    InstallerIssueCode,
    InstallerStepId,
    ReleaseCandidateInstallRequest,
)
from lea.installers.release_candidate.systemd_service import (
    CommandExecutor,
    SystemCommandResult,
)
from lea.installers.release_candidate.telegram_onboarding import (
    TelegramBotValidationResult,
)
from lea.installers.taskwarrior import (
    TaskwarriorInstallationRecord,
    TaskwarriorSmokeTestResult,
    read_taskwarrior_installation_record,
    validate_taskwarrior_executable,
)
from lea.runtime import (
    ConfigurationResult,
    RuntimeConfig,
    RuntimeHealthResult,
    check_runtime_health,
    load_runtime_config,
)
from lea.runtime.telegram import TelegramRuntimeConfig
from lea.tasks import TaskProviderInspectionResult
from lea.telegram_main import load_telegram_runtime_config

RuntimeLoader = Callable[[Path], ConfigurationResult]
RuntimeHealthChecker = Callable[[RuntimeConfig], RuntimeHealthResult]
CalendarRecordReader = Callable[
    [Path],
    tuple[CalendarToolchainInstallationRecord | None, tuple[object, ...]],
]
CalendarVersionValidator = Callable[..., CalendarToolchainVersionCheckResult]
CalendarAcceptanceTester = Callable[..., CalendarToolchainSmokeTestResult]
TaskwarriorRecordReader = Callable[
    [Path],
    tuple[TaskwarriorInstallationRecord | None, tuple[object, ...]],
]
TaskwarriorInspector = Callable[[TaskwarriorConfig], TaskProviderInspectionResult]
TelegramConfigLoader = Callable[[Path], TelegramRuntimeConfig]
SystemdExecutor = CommandExecutor
TaskwarriorAcceptanceTester = Callable[..., TaskwarriorSmokeTestResult]
TelegramAcceptanceValidator = Callable[[], TelegramBotValidationResult]
AcceptanceNotifier = Callable[[str], bool]
RuntimePathAccessChecker = Callable[
    [Path, str, str, int],
    bool,
]


class PostInstallCheckState(StrEnum):
    """Possible outcomes for one post-install check."""

    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PostInstallCheck:
    """One deterministic post-install check result."""

    code: str
    message: str
    state: PostInstallCheckState
    path: Path | None = None

    def __post_init__(self) -> None:
        """Validate one check."""
        if not self.code.strip():
            raise ValueError("code must be non-empty.")
        if not self.message.strip():
            raise ValueError("message must be non-empty.")
        if self.path is not None and not self.path.is_absolute():
            raise ValueError("path must be absolute when provided.")


@dataclass(frozen=True, slots=True)
class PostInstallHealthPlan:
    """Immutable paths required for post-install health verification."""

    runtime_config_file: Path
    telegram_config_file: Path
    installation_record_file: Path
    taskwarrior_record_file: Path
    acceptance_work_directory: Path
    systemctl: Path
    telegram_service_name: str
    telegram_enabled: bool
    service_user: str = "lea"
    service_group: str = "lea"
    calendar_record_file: Path | None = None
    calendar_acceptance_work_directory: Path | None = None

    def __post_init__(self) -> None:
        """Validate health-plan fields."""
        for field_name, path in (
            ("runtime_config_file", self.runtime_config_file),
            ("telegram_config_file", self.telegram_config_file),
            ("installation_record_file", self.installation_record_file),
            ("taskwarrior_record_file", self.taskwarrior_record_file),
            ("acceptance_work_directory", self.acceptance_work_directory),
            ("systemctl", self.systemctl),
        ):
            _validate_absolute_path(path, field_name=field_name)

        if not self.telegram_service_name.strip():
            raise ValueError("telegram_service_name must be non-empty.")

        for field_name, value in (
            ("service_user", self.service_user),
            ("service_group", self.service_group),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be non-empty.")

        if (self.calendar_record_file is None) != (
            self.calendar_acceptance_work_directory is None
        ):
            raise ValueError(
                "calendar_record_file and "
                "calendar_acceptance_work_directory must be provided together."
            )

        for field_name, optional_path in (
            ("calendar_record_file", self.calendar_record_file),
            (
                "calendar_acceptance_work_directory",
                self.calendar_acceptance_work_directory,
            ),
        ):
            if optional_path is not None:
                _validate_absolute_path(
                    optional_path,
                    field_name=field_name,
                )


@dataclass(frozen=True, slots=True)
class PostInstallHealthResult:
    """Result of read-only post-install health verification."""

    healthy: bool
    checks: tuple[PostInstallCheck, ...]
    issues: tuple[InstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate health-result consistency."""
        failed = any(
            check.state is PostInstallCheckState.FAILED for check in self.checks
        )
        if self.healthy and (failed or self.issues):
            raise ValueError(
                "A healthy result must not contain failed checks or issues."
            )
        if not self.healthy and not failed and not self.issues:
            raise ValueError("An unhealthy result must contain a failure or issue.")


@dataclass(frozen=True, slots=True)
class ReleaseCandidateAcceptanceResult:
    """Result of post-install functional acceptance."""

    accepted: bool
    checks: tuple[PostInstallCheck, ...]
    summary: str
    issues: tuple[InstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate acceptance-result consistency."""
        if not self.summary.strip():
            raise ValueError("summary must be non-empty.")

        failed = any(
            check.state is PostInstallCheckState.FAILED for check in self.checks
        )
        if self.accepted and (failed or self.issues):
            raise ValueError("An accepted result must not contain failures or issues.")
        if not self.accepted and not failed and not self.issues:
            raise ValueError("A rejected result must contain a failure or issue.")


def create_post_install_health_plan(
    request: ReleaseCandidateInstallRequest,
    *,
    calendar_enabled: bool = False,
    systemctl: Path = Path("/usr/bin/systemctl"),
) -> PostInstallHealthPlan:
    """Create the deterministic post-install verification plan."""
    if not isinstance(request, ReleaseCandidateInstallRequest):
        raise TypeError("request must be a ReleaseCandidateInstallRequest value.")

    if not isinstance(calendar_enabled, bool):
        raise TypeError("calendar_enabled must be a boolean.")

    return PostInstallHealthPlan(
        runtime_config_file=request.configuration_root / "lea.toml",
        telegram_config_file=(
            request.configuration_root / "telegram" / "telegram.toml"
        ),
        installation_record_file=(
            request.state_root / "install" / "release-candidate.json"
        ),
        taskwarrior_record_file=(request.state_root / "install" / "taskwarrior.json"),
        acceptance_work_directory=(request.state_root / "acceptance" / "taskwarrior"),
        systemctl=systemctl,
        telegram_service_name="lea-telegram.service",
        telegram_enabled=request.enable_telegram,
        service_user=request.service_user,
        service_group=request.service_group,
        calendar_record_file=(
            request.state_root / "install" / "calendar-toolchain.json"
            if calendar_enabled
            else None
        ),
        calendar_acceptance_work_directory=(
            request.state_root / "acceptance" / "calendar" if calendar_enabled else None
        ),
    )


def _runtime_path_accessible(
    path: Path,
    service_user: str,
    service_group: str,
    required_mode: int,
) -> bool:
    """Check access for the service user and generic group operators."""
    if not isinstance(path, Path) or not path.is_absolute():
        return False

    try:
        user_record = pwd.getpwnam(service_user)
        group_record = grp.getgrnam(service_group)
        user_groups = frozenset(
            os.getgrouplist(
                service_user,
                user_record.pw_gid,
            )
        )

        if group_record.gr_gid not in user_groups:
            return False

        required_bits = _requested_permission_bits(required_mode)

        return _path_accessible_to_identity(
            path,
            user_id=user_record.pw_uid,
            group_ids=user_groups,
            required_bits=required_bits,
        ) and _path_accessible_to_group(
            path,
            group_id=group_record.gr_gid,
            required_bits=required_bits,
        )
    except (KeyError, OSError):
        return False


def _requested_permission_bits(required_mode: int) -> int:
    """Translate os.access-style flags into Unix rwx bits."""
    bits = 0

    if required_mode & os.R_OK:
        bits |= 0b100
    if required_mode & os.W_OK:
        bits |= 0b010
    if required_mode & os.X_OK:
        bits |= 0b001

    return bits


def _absolute_path_chain(path: Path) -> tuple[Path, ...]:
    """Return every path component from the filesystem root to target."""
    current = Path(path.anchor)
    components = [current]

    for part in path.parts[1:]:
        current /= part
        components.append(current)

    return tuple(components)


def _path_accessible_to_identity(
    path: Path,
    *,
    user_id: int,
    group_ids: frozenset[int],
    required_bits: int,
) -> bool:
    """Evaluate one path using normal Unix user/group/other selection."""
    chain = _absolute_path_chain(path)

    for ancestor in chain[:-1]:
        metadata = ancestor.stat()

        if not stat.S_ISDIR(metadata.st_mode):
            return False

        permissions = _identity_permission_bits(
            metadata,
            user_id=user_id,
            group_ids=group_ids,
        )

        if permissions & 0b001 == 0:
            return False

    target = chain[-1].stat()
    permissions = _identity_permission_bits(
        target,
        user_id=user_id,
        group_ids=group_ids,
    )
    return permissions & required_bits == required_bits


def _path_accessible_to_group(
    path: Path,
    *,
    group_id: int,
    required_bits: int,
) -> bool:
    """Evaluate access for a non-owner member of one authorised group."""
    chain = _absolute_path_chain(path)

    for ancestor in chain[:-1]:
        metadata = ancestor.stat()

        if not stat.S_ISDIR(metadata.st_mode):
            return False

        permissions = _group_operator_permission_bits(
            metadata,
            group_id=group_id,
        )

        if permissions & 0b001 == 0:
            return False

    target = chain[-1].stat()
    permissions = _group_operator_permission_bits(
        target,
        group_id=group_id,
    )
    return permissions & required_bits == required_bits


def _identity_permission_bits(
    metadata: os.stat_result,
    *,
    user_id: int,
    group_ids: frozenset[int],
) -> int:
    """Select owner, group or other permission bits for one identity."""
    mode = stat.S_IMODE(metadata.st_mode)

    if metadata.st_uid == user_id:
        return mode >> 6 & 0b111

    if metadata.st_gid in group_ids:
        return mode >> 3 & 0b111

    return mode & 0b111


def _group_operator_permission_bits(
    metadata: os.stat_result,
    *,
    group_id: int,
) -> int:
    """Select bits for an authorised group member who is not the owner."""
    mode = stat.S_IMODE(metadata.st_mode)

    if metadata.st_gid == group_id:
        return mode >> 3 & 0b111

    return mode & 0b111


def run_post_install_health(
    plan: PostInstallHealthPlan,
    *,
    runtime_loader: RuntimeLoader = load_runtime_config,
    runtime_health_checker: RuntimeHealthChecker = check_runtime_health,
    taskwarrior_record_reader: TaskwarriorRecordReader = (
        read_taskwarrior_installation_record
    ),
    taskwarrior_inspector: TaskwarriorInspector = inspect_taskwarrior,
    calendar_record_reader: CalendarRecordReader = (
        read_calendar_toolchain_installation_record
    ),
    calendar_version_validator: CalendarVersionValidator = (
        validate_calendar_tool_versions
    ),
    telegram_config_loader: TelegramConfigLoader = (load_telegram_runtime_config),
    systemd_execute: SystemdExecutor | None = None,
    runtime_path_access_checker: RuntimePathAccessChecker = (_runtime_path_accessible),
) -> PostInstallHealthResult:
    """Run read-only health checks without repair or mutation."""
    checks: list[PostInstallCheck] = []
    issues: list[InstallerIssue] = []

    runtime_read_paths = [
        (
            "runtime_configuration_access",
            plan.runtime_config_file,
            "runtime configuration",
        ),
        (
            "release_candidate_record_access",
            plan.installation_record_file,
            "release-candidate installation record",
        ),
        (
            "taskwarrior_record_access",
            plan.taskwarrior_record_file,
            "Taskwarrior installation record",
        ),
    ]

    if plan.calendar_record_file is not None:
        runtime_read_paths.append(
            (
                "calendar_record_access",
                plan.calendar_record_file,
                "calendar installation record",
            )
        )

    for code, path, description in runtime_read_paths:
        accessible = runtime_path_access_checker(
            path,
            plan.service_user,
            plan.service_group,
            os.R_OK,
        )

        if not accessible:
            return _health_failure(
                checks,
                code,
                (
                    f"The installed {description} is not readable by both "
                    "the LEA service identity and authorised LEA group "
                    "operators."
                ),
                path=path,
            )

        checks.append(
            PostInstallCheck(
                code=code,
                message=(
                    f"The installed {description} is readable through the "
                    "complete managed path."
                ),
                state=PostInstallCheckState.PASSED,
                path=path,
            )
        )

    loaded = runtime_loader(plan.runtime_config_file)
    if not loaded.success or loaded.config is None:
        return _health_failure(
            checks,
            "runtime_configuration_invalid",
            "The installed runtime configuration could not be loaded.",
            path=plan.runtime_config_file,
        )

    runtime = loaded.config
    runtime_health = runtime_health_checker(runtime)
    checks.append(
        PostInstallCheck(
            code="runtime_health",
            message=(
                "The runtime health check passed."
                if runtime_health.healthy
                else "The runtime health check failed."
            ),
            state=(
                PostInstallCheckState.PASSED
                if runtime_health.healthy
                else PostInstallCheckState.FAILED
            ),
            path=plan.runtime_config_file,
        )
    )

    record, record_issues = taskwarrior_record_reader(plan.taskwarrior_record_file)
    if record is None or record_issues:
        checks.append(
            PostInstallCheck(
                code="taskwarrior_record_invalid",
                message=("The Taskwarrior installation record failed validation."),
                state=PostInstallCheckState.FAILED,
                path=plan.taskwarrior_record_file,
            )
        )
    else:
        checks.append(
            PostInstallCheck(
                code="taskwarrior_record_valid",
                message="The Taskwarrior installation record is valid.",
                state=PostInstallCheckState.PASSED,
                path=plan.taskwarrior_record_file,
            )
        )
        inspection = taskwarrior_inspector(
            TaskwarriorConfig(
                executable=record.executable,
                taskrc=record.taskrc,
                data_dir=record.data,
                home_dir=record.home,
                timeout_seconds=10.0,
                working_dir=runtime.paths.run_dir,
            )
        )
        checks.append(
            PostInstallCheck(
                code="taskwarrior_inspection",
                message=(
                    "The managed Taskwarrior executable is available."
                    if inspection.available
                    else _render_taskwarrior_inspection_failure(inspection)
                ),
                state=(
                    PostInstallCheckState.PASSED
                    if inspection.available
                    else PostInstallCheckState.FAILED
                ),
                path=record.executable,
            )
        )

    if plan.calendar_record_file is not None:
        _check_calendar_health(
            plan,
            runtime=runtime,
            checks=checks,
            calendar_record_reader=calendar_record_reader,
            calendar_version_validator=calendar_version_validator,
        )

    _check_installation_record(
        plan.installation_record_file,
        checks=checks,
    )

    if plan.telegram_enabled:
        _check_telegram_health(
            plan,
            runtime=runtime,
            checks=checks,
            telegram_config_loader=telegram_config_loader,
            systemd_execute=systemd_execute,
        )

    healthy = not any(check.state is PostInstallCheckState.FAILED for check in checks)

    if not healthy:
        issues.append(
            InstallerIssue(
                code=InstallerIssueCode.STEP_FAILED,
                message="One or more post-install health checks failed.",
                step=InstallerStepId.HEALTH,
            )
        )

    return PostInstallHealthResult(
        healthy=healthy,
        checks=tuple(checks),
        issues=tuple(issues),
    )


def _render_taskwarrior_inspection_failure(
    inspection: TaskProviderInspectionResult,
) -> str:
    """Render bounded structured Taskwarrior inspection diagnostics."""
    details = "; ".join(
        f"[{issue.code}] {issue.message}" for issue in inspection.issues
    )

    message = "The managed Taskwarrior inspection failed."

    if details:
        return f"{message} {details}"

    return message


def _check_calendar_health(
    plan: PostInstallHealthPlan,
    *,
    runtime: RuntimeConfig,
    checks: list[PostInstallCheck],
    calendar_record_reader: CalendarRecordReader,
    calendar_version_validator: CalendarVersionValidator,
) -> None:
    """Validate the installed calendar record and exact tool versions."""
    record_path = plan.calendar_record_file

    if record_path is None:
        raise ValueError("Calendar health requires a calendar record path.")

    try:
        record, record_issues = calendar_record_reader(record_path)
    except Exception:
        record = None
        record_issues = (object(),)

    if record is None or record_issues:
        checks.append(
            PostInstallCheck(
                code="calendar_record_invalid",
                message=(
                    "The calendar toolchain installation record failed validation."
                ),
                state=PostInstallCheckState.FAILED,
                path=record_path,
            )
        )
        return

    checks.append(
        PostInstallCheck(
            code="calendar_record_valid",
            message="The calendar toolchain installation record is valid.",
            state=PostInstallCheckState.PASSED,
            path=record_path,
        )
    )

    try:
        version_result = calendar_version_validator(
            khal_executable=record.khal_executable,
            expected_khal_version=record.khal_version,
            vdirsyncer_executable=record.vdirsyncer_executable,
            expected_vdirsyncer_version=record.vdirsyncer_version,
            working_directory=runtime.paths.run_dir,
            timeout_seconds=10.0,
        )
    except Exception:
        checks.append(
            PostInstallCheck(
                code="calendar_versions",
                message=("The installed calendar toolchain version check failed."),
                state=PostInstallCheckState.FAILED,
                path=record_path,
            )
        )
        return

    checks.append(
        PostInstallCheck(
            code="calendar_versions",
            message=(
                "The installed calendar toolchain versions are valid."
                if version_result.passed
                else _render_calendar_version_failure(version_result)
            ),
            state=(
                PostInstallCheckState.PASSED
                if version_result.passed
                else PostInstallCheckState.FAILED
            ),
            path=record_path,
        )
    )


def _render_calendar_version_failure(
    result: CalendarToolchainVersionCheckResult,
) -> str:
    """Render bounded structured calendar version diagnostics."""
    details = "; ".join(f"[{issue.code}] {issue.message}" for issue in result.issues)

    message = "The installed calendar toolchain version check failed."

    if details:
        return f"{message} {details}"

    return message


def run_release_candidate_acceptance(
    plan: PostInstallHealthPlan,
    health: PostInstallHealthResult,
    *,
    taskwarrior_record_reader: TaskwarriorRecordReader = (
        read_taskwarrior_installation_record
    ),
    taskwarrior_acceptance: TaskwarriorAcceptanceTester | None = None,
    calendar_record_reader: CalendarRecordReader = (
        read_calendar_toolchain_installation_record
    ),
    calendar_acceptance: CalendarAcceptanceTester | None = None,
    telegram_validation: TelegramAcceptanceValidator | None = None,
    notifier: AcceptanceNotifier | None = None,
) -> ReleaseCandidateAcceptanceResult:
    """Run functional acceptance after required health checks pass."""
    if not health.healthy:
        issue = InstallerIssue(
            code=InstallerIssueCode.INCOMPLETE,
            message=(
                "Functional acceptance cannot run before health verification passes."
            ),
            step=InstallerStepId.ACCEPTANCE,
        )
        return ReleaseCandidateAcceptanceResult(
            accepted=False,
            checks=(
                PostInstallCheck(
                    code="health_prerequisite",
                    message="Post-install health verification did not pass.",
                    state=PostInstallCheckState.FAILED,
                ),
            ),
            summary="LEA release-candidate acceptance: FAILED\n",
            issues=(issue,),
        )

    try:
        record, record_issues = taskwarrior_record_reader(plan.taskwarrior_record_file)
    except Exception:
        return _acceptance_failure(
            "taskwarrior_record_invalid",
            "Taskwarrior acceptance could not load the installation record.",
            path=plan.taskwarrior_record_file,
        )

    if record is None or record_issues:
        return _acceptance_failure(
            "taskwarrior_record_invalid",
            "Taskwarrior acceptance could not load the installation record.",
            path=plan.taskwarrior_record_file,
        )

    tester = taskwarrior_acceptance or validate_taskwarrior_executable
    checks: list[PostInstallCheck] = [
        _run_taskwarrior_acceptance(
            plan,
            record=record,
            tester=tester,
        )
    ]

    if plan.calendar_record_file is not None:
        try:
            calendar_record, calendar_record_issues = calendar_record_reader(
                plan.calendar_record_file
            )
        except Exception:
            return _acceptance_failure(
                "calendar_record_invalid",
                "Calendar acceptance could not load the installation record.",
                path=plan.calendar_record_file,
            )

        if calendar_record is None or calendar_record_issues:
            return _acceptance_failure(
                "calendar_record_invalid",
                "Calendar acceptance could not load the installation record.",
                path=plan.calendar_record_file,
            )

        calendar_tester = calendar_acceptance or run_calendar_toolchain_smoke_test
        checks.append(
            _run_calendar_acceptance(
                plan,
                record=calendar_record,
                tester=calendar_tester,
            )
        )

    if plan.telegram_enabled:
        checks.append(_run_telegram_acceptance(telegram_validation))

        required_checks_passed = not any(
            check.state is PostInstallCheckState.FAILED for check in checks
        )
        if notifier is not None:
            checks.append(
                _run_completion_notification(
                    notifier,
                    required_checks_passed=required_checks_passed,
                )
            )

    accepted = not any(check.state is PostInstallCheckState.FAILED for check in checks)
    summary = format_release_candidate_summary(
        accepted=accepted,
        checks=tuple(checks),
        runtime_config=plan.runtime_config_file,
        taskwarrior_record=plan.taskwarrior_record_file,
        telegram_enabled=plan.telegram_enabled,
    )
    acceptance_issues = (
        ()
        if accepted
        else (
            InstallerIssue(
                code=InstallerIssueCode.STEP_FAILED,
                message="One or more functional acceptance checks failed.",
                step=InstallerStepId.ACCEPTANCE,
            ),
        )
    )

    return ReleaseCandidateAcceptanceResult(
        accepted=accepted,
        checks=tuple(checks),
        summary=summary,
        issues=acceptance_issues,
    )


def _run_taskwarrior_acceptance(
    plan: PostInstallHealthPlan,
    *,
    record: TaskwarriorInstallationRecord,
    tester: TaskwarriorAcceptanceTester,
) -> PostInstallCheck:
    """Run the disposable Taskwarrior lifecycle through a safe boundary."""
    try:
        smoke = tester(
            record.executable,
            temporary_parent=plan.acceptance_work_directory,
            timeout_seconds=15.0,
        )
        passed = smoke.passed
    except Exception:
        passed = False

    return PostInstallCheck(
        code="taskwarrior_lifecycle",
        message=(
            "The disposable Taskwarrior lifecycle passed."
            if passed
            else "The disposable Taskwarrior lifecycle failed."
        ),
        state=(
            PostInstallCheckState.PASSED if passed else PostInstallCheckState.FAILED
        ),
        path=record.executable,
    )


def _run_calendar_acceptance(
    plan: PostInstallHealthPlan,
    *,
    record: CalendarToolchainInstallationRecord,
    tester: CalendarAcceptanceTester,
) -> PostInstallCheck:
    """Run the disposable calendar lifecycle through a safe boundary."""
    working_directory = plan.calendar_acceptance_work_directory

    if working_directory is None:
        raise ValueError(
            "Calendar acceptance requires an acceptance working directory."
        )

    try:
        if working_directory.is_symlink():
            passed = False
        else:
            working_directory.mkdir(
                parents=True,
                exist_ok=True,
                mode=0o700,
            )

            if not working_directory.is_dir():
                passed = False
            else:
                working_directory.chmod(0o700)
                smoke = tester(
                    khal_executable=record.khal_executable,
                    vdirsyncer_executable=record.vdirsyncer_executable,
                    working_directory=working_directory,
                    timeout_seconds=15.0,
                )
                passed = smoke.passed
    except Exception:
        passed = False

    return PostInstallCheck(
        code="calendar_lifecycle",
        message=(
            "The disposable calendar lifecycle passed."
            if passed
            else "The disposable calendar lifecycle failed."
        ),
        state=(
            PostInstallCheckState.PASSED if passed else PostInstallCheckState.FAILED
        ),
        path=working_directory,
    )


def _run_telegram_acceptance(
    validator: TelegramAcceptanceValidator | None,
) -> PostInstallCheck:
    """Validate the Telegram identity without exposing boundary errors."""
    if validator is None:
        passed = False
        message = "Telegram identity validation was not supplied."
    else:
        try:
            passed = validator().success
        except Exception:
            passed = False
        message = (
            "Telegram bot identity validation passed."
            if passed
            else "Telegram bot identity validation failed."
        )

    return PostInstallCheck(
        code="telegram_get_me",
        message=message,
        state=(
            PostInstallCheckState.PASSED if passed else PostInstallCheckState.FAILED
        ),
    )


def _run_completion_notification(
    notifier: AcceptanceNotifier,
    *,
    required_checks_passed: bool,
) -> PostInstallCheck:
    """Send an optional completion notice after required checks pass."""
    if not required_checks_passed:
        return PostInstallCheck(
            code="telegram_completion_message",
            message=(
                "The optional completion message was skipped because "
                "required acceptance checks failed."
            ),
            state=PostInstallCheckState.WARNING,
        )

    try:
        notified = notifier("LEA release-candidate installation is complete.")
    except Exception:
        notified = False

    return PostInstallCheck(
        code="telegram_completion_message",
        message=(
            "The optional completion message was sent."
            if notified
            else "The optional completion message was not sent."
        ),
        state=(
            PostInstallCheckState.PASSED if notified else PostInstallCheckState.WARNING
        ),
    )


def format_release_candidate_summary(
    *,
    accepted: bool,
    checks: tuple[PostInstallCheck, ...],
    runtime_config: Path,
    taskwarrior_record: Path,
    telegram_enabled: bool,
) -> str:
    """Render a deterministic human-readable acceptance summary."""
    outcome = "PASSED" if accepted else "FAILED"
    lines = [
        f"LEA release-candidate acceptance: {outcome}",
        f"Runtime configuration: {runtime_config}",
        f"Taskwarrior record: {taskwarrior_record}",
        f"Telegram enabled: {'yes' if telegram_enabled else 'no'}",
        "Checks:",
    ]
    lines.extend(
        f"  [{check.state.value}] {check.code}: {check.message}" for check in checks
    )
    return "\n".join(lines) + "\n"


def _check_installation_record(
    path: Path,
    *,
    checks: list[PostInstallCheck],
) -> None:
    """Validate the canonical release-candidate installation record."""
    valid = read_installation_record(path) is not None

    checks.append(
        PostInstallCheck(
            code="installation_record",
            message=(
                "The release-candidate installation record is valid."
                if valid
                else "The release-candidate installation record is invalid."
            ),
            state=(
                PostInstallCheckState.PASSED if valid else PostInstallCheckState.FAILED
            ),
            path=path,
        )
    )


def _check_telegram_health(
    plan: PostInstallHealthPlan,
    *,
    runtime: RuntimeConfig,
    checks: list[PostInstallCheck],
    telegram_config_loader: TelegramConfigLoader,
    systemd_execute: SystemdExecutor | None,
) -> None:
    """Check Telegram configuration, authorisation, token mode and service."""
    try:
        telegram = telegram_config_loader(plan.telegram_config_file)
    except (OSError, UnicodeError, ValueError):
        checks.append(
            PostInstallCheck(
                code="telegram_configuration",
                message="The Telegram configuration failed validation.",
                state=PostInstallCheckState.FAILED,
                path=plan.telegram_config_file,
            )
        )
        return

    checks.append(
        PostInstallCheck(
            code="telegram_configuration",
            message="The Telegram configuration is valid.",
            state=PostInstallCheckState.PASSED,
            path=plan.telegram_config_file,
        )
    )

    users = load_authorised_channel_users(telegram.authorised_users_file)
    checks.append(
        PostInstallCheck(
            code="telegram_authorised_users",
            message=(
                "The Telegram authorised-user file is valid."
                if users.success and users.users
                else "The Telegram authorised-user file is invalid or empty."
            ),
            state=(
                PostInstallCheckState.PASSED
                if users.success and users.users
                else PostInstallCheckState.FAILED
            ),
            path=telegram.authorised_users_file,
        )
    )

    token_path = runtime.secrets.telegram_token_file
    token_mode_valid = False
    if token_path is not None:
        try:
            token_mode_valid = (
                token_path.is_file()
                and not token_path.is_symlink()
                and stat.S_IMODE(token_path.stat().st_mode) == 0o600
            )
        except OSError:
            token_mode_valid = False

    checks.append(
        PostInstallCheck(
            code="telegram_token_permissions",
            message=(
                "The Telegram token file has mode 0600."
                if token_mode_valid
                else "The Telegram token file does not have mode 0600."
            ),
            state=(
                PostInstallCheckState.PASSED
                if token_mode_valid
                else PostInstallCheckState.FAILED
            ),
            path=token_path,
        )
    )

    executor = systemd_execute or _execute_systemctl
    for operation in ("is-enabled", "is-active"):
        command = (
            str(plan.systemctl),
            operation,
            plan.telegram_service_name,
        )
        try:
            result = executor(command)
            passed = result.return_code == 0
        except Exception:
            passed = False

        checks.append(
            PostInstallCheck(
                code=f"telegram_service_{operation}",
                message=(
                    f"The Telegram service {operation} check passed."
                    if passed
                    else f"The Telegram service {operation} check failed."
                ),
                state=(
                    PostInstallCheckState.PASSED
                    if passed
                    else PostInstallCheckState.FAILED
                ),
            )
        )


def _execute_systemctl(command: tuple[str, ...]) -> SystemCommandResult:
    """Execute one exact systemctl query through the Slice 9 result contract."""
    import subprocess

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return SystemCommandResult(return_code=completed.returncode)


def _health_failure(
    checks: list[PostInstallCheck],
    code: str,
    message: str,
    *,
    path: Path | None = None,
) -> PostInstallHealthResult:
    check = PostInstallCheck(
        code=code,
        message=message,
        state=PostInstallCheckState.FAILED,
        path=path,
    )
    return PostInstallHealthResult(
        healthy=False,
        checks=(*checks, check),
        issues=(
            InstallerIssue(
                code=InstallerIssueCode.STEP_FAILED,
                message=message,
                step=InstallerStepId.HEALTH,
                path=path,
            ),
        ),
    )


def _acceptance_failure(
    code: str,
    message: str,
    *,
    path: Path | None = None,
) -> ReleaseCandidateAcceptanceResult:
    return ReleaseCandidateAcceptanceResult(
        accepted=False,
        checks=(
            PostInstallCheck(
                code=code,
                message=message,
                state=PostInstallCheckState.FAILED,
                path=path,
            ),
        ),
        summary="LEA release-candidate acceptance: FAILED\n",
        issues=(
            InstallerIssue(
                code=InstallerIssueCode.STEP_FAILED,
                message=message,
                step=InstallerStepId.ACCEPTANCE,
                path=path,
            ),
        ),
    )


def _validate_absolute_path(path: Path, *, field_name: str) -> None:
    if not isinstance(path, Path):
        raise TypeError(f"{field_name} must be a pathlib.Path value.")
    if not path.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path.")
    if "\x00" in str(path):
        raise ValueError(f"{field_name} must not contain a null byte.")
