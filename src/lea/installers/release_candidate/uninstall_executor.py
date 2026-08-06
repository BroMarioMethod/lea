"""Safe deterministic execution of release-candidate purge plans."""

from __future__ import annotations

import grp
import pwd
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from lea.installers.release_candidate.uninstall_contracts import (
    ReleaseCandidateUninstallIssue,
    ReleaseCandidateUninstallIssueCode,
    ReleaseCandidateUninstallPlan,
    ReleaseCandidateUninstallResult,
    ReleaseCandidateUninstallStepId,
    ReleaseCandidateUninstallStepPlan,
    ReleaseCandidateUninstallStepResult,
    ReleaseCandidateUninstallStepState,
)

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
IdentityLookup = Callable[[str], bool]


def execute_release_candidate_uninstall(
    plan: ReleaseCandidateUninstallPlan,
    *,
    command_runner: CommandRunner = subprocess.run,
    user_exists: IdentityLookup | None = None,
    group_exists: IdentityLookup | None = None,
) -> ReleaseCandidateUninstallResult:
    """Execute one validated purge plan without following symlinks."""
    if not isinstance(plan, ReleaseCandidateUninstallPlan):
        raise TypeError("plan must be a ReleaseCandidateUninstallPlan value.")

    resolved_user_exists = user_exists or _user_exists
    resolved_group_exists = group_exists or _group_exists

    results: list[ReleaseCandidateUninstallStepResult] = []
    issues: list[ReleaseCandidateUninstallIssue] = []

    service_result = _remove_systemd_service(
        plan,
        command_runner=command_runner,
    )
    results.append(service_result)
    issues.extend(service_result.issues)

    if service_result.state is ReleaseCandidateUninstallStepState.FAILED:
        results.extend(
            _skipped_after_failure(
                plan,
                completed_steps={ReleaseCandidateUninstallStepId.SYSTEMD_SERVICE},
                reason=(
                    "Skipped because the managed service could not be "
                    "stopped and removed safely."
                ),
            )
        )
        return ReleaseCandidateUninstallResult(
            success=False,
            steps=tuple(results),
            issues=tuple(issues),
        )

    file_removal_failed = False

    runtime_result = _remove_runtime_resources(plan)
    results.append(runtime_result)
    issues.extend(runtime_result.issues)

    if runtime_result.state is ReleaseCandidateUninstallStepState.FAILED:
        file_removal_failed = True

    for step_id in (
        ReleaseCandidateUninstallStepId.TASKWARRIOR,
        ReleaseCandidateUninstallStepId.CALENDAR_TOOLCHAIN,
        ReleaseCandidateUninstallStepId.CONFIGURATION,
        ReleaseCandidateUninstallStepId.STATE,
        ReleaseCandidateUninstallStepId.LOGS,
    ):
        step_result = _remove_managed_path(plan, step_id)
        results.append(step_result)
        issues.extend(step_result.issues)

        if step_result.state is ReleaseCandidateUninstallStepState.FAILED:
            file_removal_failed = True

    if file_removal_failed:
        results.append(
            ReleaseCandidateUninstallStepResult(
                step=ReleaseCandidateUninstallStepId.SYSTEM_ACCOUNT,
                state=ReleaseCandidateUninstallStepState.SKIPPED,
                message=(
                    "Service account removal was skipped because one or "
                    "more managed paths could not be removed safely."
                ),
            )
        )
    else:
        account_result = _remove_system_account(
            plan,
            command_runner=command_runner,
            user_exists=resolved_user_exists,
            group_exists=resolved_group_exists,
        )
        results.append(account_result)
        issues.extend(account_result.issues)

    return ReleaseCandidateUninstallResult(
        success=not issues,
        steps=tuple(results),
        issues=tuple(issues),
    )


def _remove_systemd_service(
    plan: ReleaseCandidateUninstallPlan,
    *,
    command_runner: CommandRunner,
) -> ReleaseCandidateUninstallStepResult:
    """Stop, disable and remove the managed systemd unit."""
    step = _step(
        plan,
        ReleaseCandidateUninstallStepId.SYSTEMD_SERVICE,
    )
    unit = plan.request.systemd_unit

    if unit.is_symlink():
        return _unsafe_path_result(
            step=step.step,
            path=unit,
            message="The managed systemd unit is a symbolic link.",
        )

    if unit.exists() and not unit.is_file():
        return _unsafe_path_result(
            step=step.step,
            path=unit,
            message="The managed systemd unit is not a regular file.",
        )

    commands = tuple(
        mutation.command for mutation in step.mutations if mutation.command is not None
    )

    if len(commands) != 3:
        return _failed_step(
            step=step.step,
            message=(
                "The uninstall plan did not contain the expected systemd commands."
            ),
            path=unit,
        )

    unit_existed = unit.exists()

    try:
        _run_idempotent_systemctl(
            command_runner,
            commands[0],
        )
        _run_idempotent_systemctl(
            command_runner,
            commands[1],
        )

        if unit_existed:
            unit.unlink()

        _run_checked(
            command_runner,
            commands[2],
        )

    except (OSError, subprocess.CalledProcessError) as error:
        return _failed_step(
            step=step.step,
            message=(
                f"Managed systemd service removal failed: {type(error).__name__}."
            ),
            path=unit,
        )

    state = (
        ReleaseCandidateUninstallStepState.COMPLETED
        if unit_existed
        else ReleaseCandidateUninstallStepState.SKIPPED
    )
    message = (
        "The managed systemd service was removed."
        if unit_existed
        else (
            "The managed systemd unit was already absent; "
            "stop, disable and daemon-reload were completed."
        )
    )

    return ReleaseCandidateUninstallStepResult(
        step=step.step,
        state=state,
        message=message,
    )


def _run_idempotent_systemctl(
    command_runner: CommandRunner,
    command: tuple[str, ...],
) -> None:
    """Run stop or disable while tolerating an already absent unit."""
    try:
        _run_checked(command_runner, command)
    except subprocess.CalledProcessError as error:
        stderr = error.stderr or ""
        tolerated = (
            "not loaded" in stderr.lower()
            or "not found" in stderr.lower()
            or "does not exist" in stderr.lower()
        )
        if not tolerated:
            raise


def _remove_runtime_resources(
    plan: ReleaseCandidateUninstallPlan,
) -> ReleaseCandidateUninstallStepResult:
    """Remove the exact managed tmpfiles rule and volatile runtime directory."""
    step = _step(
        plan,
        ReleaseCandidateUninstallStepId.RUNTIME_RESOURCES,
    )
    targets = tuple(
        mutation.target for mutation in step.mutations if mutation.target is not None
    )

    if targets != (
        plan.request.tmpfiles_configuration,
        plan.request.runtime_directory,
    ):
        return _failed_step(
            step=step.step,
            message=(
                "The uninstall plan did not contain the expected "
                "runtime-resource targets."
            ),
        )

    tmpfiles = plan.request.tmpfiles_configuration
    runtime = plan.request.runtime_directory

    if tmpfiles.is_symlink():
        return _unsafe_path_result(
            step=step.step,
            path=tmpfiles,
            message=("The managed tmpfiles configuration is a symbolic link."),
        )

    if tmpfiles.exists() and not tmpfiles.is_file():
        return _unsafe_path_result(
            step=step.step,
            path=tmpfiles,
            message=("The managed tmpfiles configuration is not a regular file."),
        )

    if runtime.is_symlink():
        return _unsafe_path_result(
            step=step.step,
            path=runtime,
            message=("The managed runtime-directory target is a symbolic link."),
        )

    if runtime.exists() and not runtime.is_dir():
        return _unsafe_path_result(
            step=step.step,
            path=runtime,
            message=("The managed runtime-directory target is not a directory."),
        )

    tmpfiles_existed = tmpfiles.exists()
    runtime_existed = runtime.exists()

    try:
        if tmpfiles_existed:
            tmpfiles.unlink()

        if runtime_existed:
            shutil.rmtree(runtime)
    except OSError as error:
        return _failed_step(
            step=step.step,
            message=(
                f"Managed runtime-resource removal failed: {type(error).__name__}."
            ),
        )

    if not tmpfiles_existed and not runtime_existed:
        return ReleaseCandidateUninstallStepResult(
            step=step.step,
            state=ReleaseCandidateUninstallStepState.SKIPPED,
            message="Managed runtime resources were already absent.",
        )

    removed: list[str] = []
    if tmpfiles_existed:
        removed.append(str(tmpfiles))
    if runtime_existed:
        removed.append(str(runtime))

    return ReleaseCandidateUninstallStepResult(
        step=step.step,
        state=ReleaseCandidateUninstallStepState.COMPLETED,
        message=f"Removed managed runtime resources: {', '.join(removed)}.",
    )


def _remove_managed_path(
    plan: ReleaseCandidateUninstallPlan,
    step_id: ReleaseCandidateUninstallStepId,
) -> ReleaseCandidateUninstallStepResult:
    """Remove one exact managed directory without following symlinks."""
    step = _step(plan, step_id)
    targets = tuple(
        mutation.target for mutation in step.mutations if mutation.target is not None
    )

    if len(targets) != 1:
        return _failed_step(
            step=step.step,
            message=(
                "The uninstall plan did not contain exactly one managed "
                "directory target."
            ),
        )

    target = targets[0]

    if target.is_symlink():
        return _unsafe_path_result(
            step=step.step,
            path=target,
            message="The managed directory target is a symbolic link.",
        )

    if not target.exists():
        return ReleaseCandidateUninstallStepResult(
            step=step.step,
            state=ReleaseCandidateUninstallStepState.SKIPPED,
            message=f"The managed path was already absent: {target}.",
        )

    if not target.is_dir():
        return _unsafe_path_result(
            step=step.step,
            path=target,
            message="The managed directory target is not a directory.",
        )

    try:
        shutil.rmtree(target)
    except OSError as error:
        return _failed_step(
            step=step.step,
            message=(f"Managed directory removal failed: {type(error).__name__}."),
            path=target,
        )

    return ReleaseCandidateUninstallStepResult(
        step=step.step,
        state=ReleaseCandidateUninstallStepState.COMPLETED,
        message=f"Removed managed path: {target}.",
    )


def _remove_system_account(
    plan: ReleaseCandidateUninstallPlan,
    *,
    command_runner: CommandRunner,
    user_exists: IdentityLookup,
    group_exists: IdentityLookup,
) -> ReleaseCandidateUninstallStepResult:
    """Remove the managed user and group after managed files are gone."""
    step = _step(
        plan,
        ReleaseCandidateUninstallStepId.SYSTEM_ACCOUNT,
    )
    commands = tuple(
        mutation.command for mutation in step.mutations if mutation.command is not None
    )

    if len(commands) != 2:
        return _failed_step(
            step=step.step,
            message=(
                "The uninstall plan did not contain the expected account "
                "removal commands."
            ),
        )

    user_removed = False
    group_removed = False

    try:
        if user_exists(plan.request.service_user):
            _run_checked(command_runner, commands[0])
            user_removed = True

        # userdel may also remove a matching private group. Re-query after
        # user removal instead of relying on group state captured earlier.
        if group_exists(plan.request.service_group):
            _run_checked(command_runner, commands[1])
            group_removed = True

    except (OSError, subprocess.CalledProcessError) as error:
        completed: list[str] = []

        if user_removed:
            completed.append(f"user {plan.request.service_user}")
        if group_removed:
            completed.append(f"group {plan.request.service_group}")

        partial = (
            f" Successfully removed {', '.join(completed)} before the failure."
            if completed
            else ""
        )

        return _failed_step(
            step=step.step,
            message=(
                "Managed service-account removal failed: "
                f"{type(error).__name__}.{partial}"
            ),
        )

    if not user_removed and not group_removed:
        return ReleaseCandidateUninstallStepResult(
            step=step.step,
            state=ReleaseCandidateUninstallStepState.SKIPPED,
            message="The managed service user and group were already absent.",
        )

    removed: list[str] = []
    if user_removed:
        removed.append(f"user {plan.request.service_user}")
    if group_removed:
        removed.append(f"group {plan.request.service_group}")

    return ReleaseCandidateUninstallStepResult(
        step=step.step,
        state=ReleaseCandidateUninstallStepState.COMPLETED,
        message=f"Removed managed {' and '.join(removed)}.",
    )


def _step(
    plan: ReleaseCandidateUninstallPlan,
    step_id: ReleaseCandidateUninstallStepId,
) -> ReleaseCandidateUninstallStepPlan:
    """Return one required plan step."""
    matches = tuple(step for step in plan.steps if step.step is step_id)

    if len(matches) != 1:
        raise ValueError(
            f"Uninstall plan must contain exactly one {step_id.value} step."
        )

    return matches[0]


def _skipped_after_failure(
    plan: ReleaseCandidateUninstallPlan,
    *,
    completed_steps: set[ReleaseCandidateUninstallStepId],
    reason: str,
) -> tuple[ReleaseCandidateUninstallStepResult, ...]:
    """Render remaining plan steps as safely skipped."""
    return tuple(
        ReleaseCandidateUninstallStepResult(
            step=step.step,
            state=ReleaseCandidateUninstallStepState.SKIPPED,
            message=reason,
        )
        for step in plan.steps
        if step.step not in completed_steps
    )


def _unsafe_path_result(
    *,
    step: ReleaseCandidateUninstallStepId,
    path: Path,
    message: str,
) -> ReleaseCandidateUninstallStepResult:
    """Return one unsafe-path failure."""
    issue = ReleaseCandidateUninstallIssue(
        code=ReleaseCandidateUninstallIssueCode.UNSAFE_PATH,
        message=message,
        step=step,
        path=path,
    )
    return ReleaseCandidateUninstallStepResult(
        step=step,
        state=ReleaseCandidateUninstallStepState.FAILED,
        message=message,
        issues=(issue,),
    )


def _failed_step(
    *,
    step: ReleaseCandidateUninstallStepId,
    message: str,
    path: Path | None = None,
) -> ReleaseCandidateUninstallStepResult:
    """Return one ordinary uninstall-step failure."""
    issue = ReleaseCandidateUninstallIssue(
        code=ReleaseCandidateUninstallIssueCode.STEP_FAILED,
        message=message,
        step=step,
        path=path,
    )
    return ReleaseCandidateUninstallStepResult(
        step=step,
        state=ReleaseCandidateUninstallStepState.FAILED,
        message=message,
        issues=(issue,),
    )


def _run_checked(
    command_runner: CommandRunner,
    command: tuple[str, ...],
) -> None:
    """Run one exact finite command without a shell."""
    command_runner(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=30.0,
    )


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
