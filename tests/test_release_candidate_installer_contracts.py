"""Tests for immutable release-candidate installer contracts."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from lea.installers.release_candidate import (
    InstallerIssue,
    InstallerIssueCode,
    InstallerMutation,
    InstallerMutationKind,
    InstallerStepId,
    InstallerStepPlan,
    InstallerStepResult,
    InstallerStepState,
    ReleaseCandidateInstallMode,
    ReleaseCandidateInstallPlan,
    ReleaseCandidateInstallRequest,
    ReleaseCandidateInstallResult,
)


def _request(
    *,
    enable_telegram: bool = True,
) -> ReleaseCandidateInstallRequest:
    """Return one valid installation request."""
    return ReleaseCandidateInstallRequest(
        mode=ReleaseCandidateInstallMode.FRESH_INSTALL,
        display_timezone="Africa/Gaborone",
        enable_telegram=enable_telegram,
    )


def _step(
    step: InstallerStepId,
) -> InstallerStepPlan:
    """Return one valid step plan."""
    return InstallerStepPlan(
        step=step,
        summary=f"Plan {step.value}.",
        mutations=(),
    )


def _telegram_plan() -> ReleaseCandidateInstallPlan:
    """Return one valid Telegram-enabled plan."""
    return ReleaseCandidateInstallPlan(
        request=_request(),
        steps=(
            _step(InstallerStepId.PREFLIGHT),
            _step(InstallerStepId.TELEGRAM_ONBOARDING),
            _step(InstallerStepId.TELEGRAM_CONFIGURATION),
            _step(InstallerStepId.SYSTEMD_SERVICE),
        ),
    )


def test_install_request_is_immutable() -> None:
    """Installation requests should remain frozen."""
    request = _request()

    with pytest.raises(FrozenInstanceError):
        request.enable_telegram = False  # type: ignore[misc]


def test_install_request_requires_absolute_paths() -> None:
    """Managed installation paths must be absolute."""
    with pytest.raises(
        ValueError,
        match="installation_root must be an absolute path",
    ):
        ReleaseCandidateInstallRequest(
            mode=ReleaseCandidateInstallMode.FRESH_INSTALL,
            display_timezone="Africa/Gaborone",
            enable_telegram=True,
            installation_root=Path("opt/lea"),
        )


def test_mutation_requires_absolute_target() -> None:
    """Mutation targets should remain unambiguous."""
    with pytest.raises(
        ValueError,
        match="target must be an absolute path",
    ):
        InstallerMutation(
            kind=InstallerMutationKind.WRITE_FILE,
            summary="Write configuration.",
            target=Path("etc/lea/lea.toml"),
        )


def test_step_plan_rejects_duplicate_mutations() -> None:
    """A step must not contain duplicate mutations."""
    mutation = InstallerMutation(
        kind=InstallerMutationKind.CREATE_DIRECTORY,
        summary="Create state root.",
        target=Path("/var/lib/lea"),
    )

    with pytest.raises(
        ValueError,
        match="mutations must not contain duplicates",
    ):
        InstallerStepPlan(
            step=InstallerStepId.FILESYSTEM,
            summary="Provision filesystem.",
            mutations=(mutation, mutation),
        )


def test_telegram_enabled_plan_requires_all_channel_steps() -> None:
    """Telegram-enabled plans must contain the complete channel sequence."""
    with pytest.raises(
        ValueError,
        match="must contain onboarding",
    ):
        ReleaseCandidateInstallPlan(
            request=_request(),
            steps=(
                _step(InstallerStepId.PREFLIGHT),
                _step(InstallerStepId.TELEGRAM_ONBOARDING),
            ),
        )


def test_telegram_disabled_plan_rejects_channel_steps() -> None:
    """Telegram-disabled plans must not contain channel mutations."""
    with pytest.raises(
        ValueError,
        match="must not contain Telegram service steps",
    ):
        ReleaseCandidateInstallPlan(
            request=_request(enable_telegram=False),
            steps=(
                _step(InstallerStepId.PREFLIGHT),
                _step(InstallerStepId.SYSTEMD_SERVICE),
            ),
        )


def test_install_plan_rejects_duplicate_step_identifiers() -> None:
    """Each plan step identifier must occur once."""
    with pytest.raises(
        ValueError,
        match="duplicate step identifiers",
    ):
        ReleaseCandidateInstallPlan(
            request=_request(enable_telegram=False),
            steps=(
                _step(InstallerStepId.PREFLIGHT),
                _step(InstallerStepId.PREFLIGHT),
            ),
        )


def test_failed_step_requires_issue() -> None:
    """Failed steps must explain their failure."""
    with pytest.raises(
        ValueError,
        match="failed step must contain at least one issue",
    ):
        InstallerStepResult(
            step=InstallerStepId.PREFLIGHT,
            state=InstallerStepState.FAILED,
            message="Preflight failed.",
        )


def test_non_failed_step_rejects_issues() -> None:
    """Completed, skipped and planned steps must not carry failure issues."""
    issue = InstallerIssue(
        code=InstallerIssueCode.PREFLIGHT_FAILED,
        message="Unsupported host.",
        step=InstallerStepId.PREFLIGHT,
    )

    with pytest.raises(
        ValueError,
        match="non-failed step must not contain issues",
    ):
        InstallerStepResult(
            step=InstallerStepId.PREFLIGHT,
            state=InstallerStepState.COMPLETED,
            message="Preflight complete.",
            issues=(issue,),
        )


def test_success_result_rejects_failed_steps() -> None:
    """Successful results must not contain failed work."""
    issue = InstallerIssue(
        code=InstallerIssueCode.STEP_FAILED,
        message="Step failed.",
        step=InstallerStepId.FILESYSTEM,
    )
    failed = InstallerStepResult(
        step=InstallerStepId.FILESYSTEM,
        state=InstallerStepState.FAILED,
        message="Filesystem provisioning failed.",
        issues=(issue,),
    )

    with pytest.raises(
        ValueError,
        match="must not contain failed steps",
    ):
        ReleaseCandidateInstallResult(
            success=True,
            mode=ReleaseCandidateInstallMode.FRESH_INSTALL,
            steps=(failed,),
            issues=(),
        )


def test_valid_plan_and_results_are_constructible() -> None:
    """Consistent plans and installation results should be accepted."""
    plan = _telegram_plan()
    completed = InstallerStepResult(
        step=InstallerStepId.PREFLIGHT,
        state=InstallerStepState.COMPLETED,
        message="Preflight complete.",
    )
    result = ReleaseCandidateInstallResult(
        success=True,
        mode=ReleaseCandidateInstallMode.FRESH_INSTALL,
        steps=(completed,),
        issues=(),
    )

    assert plan.request.enable_telegram is True
    assert result.success is True
