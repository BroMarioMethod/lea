"""Tests for guided release-candidate orchestration contracts."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from lea.installers.release_candidate import (
    InstallerInteraction,
    InstallerInteractionKind,
    InstallerIssue,
    InstallerIssueCode,
    InstallerStepId,
    InstallerStepResult,
    InstallerStepState,
    ReleaseCandidateInstallMode,
    ReleaseCandidateInstallRequest,
    ReleaseCandidateOrchestrationRequest,
    ReleaseCandidateOrchestrationResult,
    ReleaseCandidateOrchestrationState,
    ReleaseCandidateTaskwarriorInputs,
)


def _installation(
    *,
    enable_telegram: bool = True,
    non_interactive: bool = False,
) -> ReleaseCandidateInstallRequest:
    return ReleaseCandidateInstallRequest(
        mode=ReleaseCandidateInstallMode.FRESH_INSTALL,
        display_timezone="Africa/Gaborone",
        enable_telegram=enable_telegram,
        non_interactive=non_interactive,
    )


def _taskwarrior() -> ReleaseCandidateTaskwarriorInputs:
    return ReleaseCandidateTaskwarriorInputs(
        version="3.4.2",
        platform="linux-aarch64",
        source_archive=Path("/tmp/task-3.4.2.tar.gz"),
        expected_sha256="a" * 64,
        build_directory=Path("/tmp/lea-taskwarrior-build"),
    )


def _request(
    *,
    enable_telegram: bool = True,
    non_interactive: bool = False,
    plan_approved: bool = True,
) -> ReleaseCandidateOrchestrationRequest:
    return ReleaseCandidateOrchestrationRequest(
        installation=_installation(
            enable_telegram=enable_telegram,
            non_interactive=non_interactive,
        ),
        taskwarrior=_taskwarrior(),
        lea_version="0.1.0",
        plan_approved=plan_approved,
    )


def _completed(step: InstallerStepId) -> InstallerStepResult:
    return InstallerStepResult(
        step=step,
        state=InstallerStepState.COMPLETED,
        message=f"{step.value} completed.",
    )


def _failed(step: InstallerStepId) -> InstallerStepResult:
    issue = InstallerIssue(
        code=InstallerIssueCode.STEP_FAILED,
        message=f"{step.value} failed.",
        step=step,
    )
    return InstallerStepResult(
        step=step,
        state=InstallerStepState.FAILED,
        message=f"{step.value} failed.",
        issues=(issue,),
    )


def test_orchestration_request_is_immutable() -> None:
    request = _request()

    with pytest.raises(FrozenInstanceError):
        request.plan_approved = False  # type: ignore[misc]


def test_non_interactive_request_requires_plan_approval() -> None:
    with pytest.raises(
        ValueError,
        match="requires prior plan approval",
    ):
        _request(
            non_interactive=True,
            plan_approved=False,
        )


def test_telegram_token_interaction_must_be_secret() -> None:
    with pytest.raises(
        ValueError,
        match="must be secret",
    ):
        InstallerInteraction(
            kind=InstallerInteractionKind.TELEGRAM_TOKEN,
            prompt="Telegram bot token:",
            step=InstallerStepId.TELEGRAM_ONBOARDING,
        )


def test_waiting_result_requires_matching_interaction() -> None:
    interaction = InstallerInteraction(
        kind=InstallerInteractionKind.TELEGRAM_IDENTITY_CONFIRMATION,
        prompt="Confirm the discovered Telegram identity.",
        step=InstallerStepId.TELEGRAM_ONBOARDING,
        choices=("confirm", "cancel"),
    )

    result = ReleaseCandidateOrchestrationResult(
        state=ReleaseCandidateOrchestrationState.WAITING_FOR_INTERACTION,
        request=_request(),
        current_step=InstallerStepId.TELEGRAM_ONBOARDING,
        step_results=(_completed(InstallerStepId.PREFLIGHT),),
        telegram_selected=True,
        pending_interaction=interaction,
        issues=(),
    )

    assert result.pending_interaction == interaction


def test_plan_approval_may_wait_without_current_step() -> None:
    interaction = InstallerInteraction(
        kind=InstallerInteractionKind.PLAN_APPROVAL,
        prompt="Approve the installation plan.",
        choices=("approve", "cancel"),
    )

    result = ReleaseCandidateOrchestrationResult(
        state=ReleaseCandidateOrchestrationState.WAITING_FOR_INTERACTION,
        request=_request(plan_approved=False),
        current_step=None,
        step_results=(),
        telegram_selected=True,
        pending_interaction=interaction,
        issues=(),
    )

    assert result.current_step is None


def test_running_result_requires_current_step() -> None:
    with pytest.raises(
        ValueError,
        match="must contain a current step",
    ):
        ReleaseCandidateOrchestrationResult(
            state=ReleaseCandidateOrchestrationState.RUNNING,
            request=_request(),
            current_step=None,
            step_results=(),
            telegram_selected=True,
            pending_interaction=None,
            issues=(),
        )


def test_success_rejects_failed_step() -> None:
    with pytest.raises(
        ValueError,
        match="must not contain failures",
    ):
        ReleaseCandidateOrchestrationResult(
            state=ReleaseCandidateOrchestrationState.SUCCEEDED,
            request=_request(),
            current_step=None,
            step_results=(_failed(InstallerStepId.TASKWARRIOR),),
            telegram_selected=True,
            pending_interaction=None,
            issues=(),
        )


def test_failed_result_requires_failure_information() -> None:
    with pytest.raises(
        ValueError,
        match="must contain a failed step or issue",
    ):
        ReleaseCandidateOrchestrationResult(
            state=ReleaseCandidateOrchestrationState.FAILED,
            request=_request(),
            current_step=None,
            step_results=(_completed(InstallerStepId.PREFLIGHT),),
            telegram_selected=True,
            pending_interaction=None,
            issues=(),
        )


def test_cancelled_result_remains_separate_from_failure() -> None:
    result = ReleaseCandidateOrchestrationResult(
        state=ReleaseCandidateOrchestrationState.CANCELLED,
        request=_request(),
        current_step=None,
        step_results=(_completed(InstallerStepId.PREFLIGHT),),
        telegram_selected=True,
        pending_interaction=None,
        issues=(),
    )

    assert result.state is ReleaseCandidateOrchestrationState.CANCELLED

    with pytest.raises(
        ValueError,
        match="separate from failure",
    ):
        ReleaseCandidateOrchestrationResult(
            state=ReleaseCandidateOrchestrationState.CANCELLED,
            request=_request(),
            current_step=None,
            step_results=(_failed(InstallerStepId.TASKWARRIOR),),
            telegram_selected=True,
            pending_interaction=None,
            issues=(),
        )


def test_telegram_disabled_result_rejects_telegram_steps() -> None:
    with pytest.raises(
        ValueError,
        match="must not contain Telegram steps",
    ):
        ReleaseCandidateOrchestrationResult(
            state=ReleaseCandidateOrchestrationState.RUNNING,
            request=_request(enable_telegram=False),
            current_step=InstallerStepId.TELEGRAM_CONFIGURATION,
            step_results=(_completed(InstallerStepId.PREFLIGHT),),
            telegram_selected=False,
            pending_interaction=None,
            issues=(),
        )


def test_step_results_reject_duplicates_and_planned_states() -> None:
    completed = _completed(InstallerStepId.PREFLIGHT)

    with pytest.raises(
        ValueError,
        match="duplicate step identifiers",
    ):
        ReleaseCandidateOrchestrationResult(
            state=ReleaseCandidateOrchestrationState.SUCCEEDED,
            request=_request(),
            current_step=None,
            step_results=(completed, completed),
            telegram_selected=True,
            pending_interaction=None,
            issues=(),
        )

    planned = InstallerStepResult(
        step=InstallerStepId.FILESYSTEM,
        state=InstallerStepState.PLANNED,
        message="Filesystem provisioning is planned.",
    )
    with pytest.raises(
        ValueError,
        match="attempted step outcomes",
    ):
        ReleaseCandidateOrchestrationResult(
            state=ReleaseCandidateOrchestrationState.RUNNING,
            request=_request(),
            current_step=InstallerStepId.FILESYSTEM,
            step_results=(planned,),
            telegram_selected=True,
            pending_interaction=None,
            issues=(),
        )


def test_successful_result_is_constructible() -> None:
    result = ReleaseCandidateOrchestrationResult(
        state=ReleaseCandidateOrchestrationState.SUCCEEDED,
        request=_request(),
        current_step=None,
        step_results=(
            _completed(InstallerStepId.PREFLIGHT),
            _completed(InstallerStepId.SYSTEM_ACCOUNT),
            _completed(InstallerStepId.FILESYSTEM),
            _completed(InstallerStepId.BASE_CONFIGURATION),
            _completed(InstallerStepId.TASKWARRIOR),
            _completed(InstallerStepId.TELEGRAM_ONBOARDING),
            _completed(InstallerStepId.TELEGRAM_CONFIGURATION),
            _completed(InstallerStepId.SYSTEMD_SERVICE),
            _completed(InstallerStepId.HEALTH),
            _completed(InstallerStepId.ACCEPTANCE),
        ),
        telegram_selected=True,
        pending_interaction=None,
        issues=(),
    )

    assert result.state is ReleaseCandidateOrchestrationState.SUCCEEDED
