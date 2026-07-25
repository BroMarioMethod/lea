"""Deterministic release-candidate installer orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lea.installers.release_candidate.configuration import (
    BaseConfigurationResult,
    create_base_configuration_plan,
    create_installation_record,
    install_base_configuration,
)
from lea.installers.release_candidate.contracts import (
    InstallerIssue,
    InstallerIssueCode,
    InstallerStepId,
    InstallerStepResult,
    InstallerStepState,
    ReleaseCandidateInstallMode,
    ReleaseCandidateInstallRequest,
)
from lea.installers.release_candidate.orchestration import (
    InstallerInteraction,
    InstallerInteractionKind,
    ReleaseCandidateOrchestrationRequest,
    ReleaseCandidateOrchestrationResult,
    ReleaseCandidateOrchestrationState,
)
from lea.installers.release_candidate.post_install import (
    PostInstallHealthResult,
    ReleaseCandidateAcceptanceResult,
    create_post_install_health_plan,
    run_post_install_health,
    run_release_candidate_acceptance,
)
from lea.installers.release_candidate.preflight import (
    HostPreflightResult,
    run_host_preflight,
)
from lea.installers.release_candidate.provisioning import (
    SystemProvisioningResult,
    create_system_provisioning_plan,
    provision_system_layout,
)
from lea.installers.release_candidate.systemd_service import (
    TelegramSystemdServiceResult,
    create_telegram_systemd_service_plan,
    deploy_telegram_systemd_service,
)
from lea.installers.release_candidate.taskwarrior import (
    ReleaseCandidateTaskwarriorInputs,
    ReleaseCandidateTaskwarriorResult,
    create_taskwarrior_installation_plan,
    install_release_candidate_taskwarrior,
)
from lea.installers.release_candidate.telegram_configuration import (
    TelegramConfigurationResult,
    apply_posix_ownership,
    create_telegram_configuration_plan,
    persist_telegram_configuration,
)
from lea.installers.release_candidate.telegram_onboarding import (
    TelegramBotValidationResult,
    TelegramOnboardingConfirmation,
    validate_bot_token_shape,
)
from lea.installers.taskwarrior import TaskwarriorSmokeTestResult

CancellationSignal = Callable[[], bool]
TaskwarriorAcceptanceTester = Callable[..., TaskwarriorSmokeTestResult]
TelegramAcceptanceValidator = Callable[[], TelegramBotValidationResult]
AcceptanceNotifier = Callable[[str], bool]

PreflightRunner = Callable[[ReleaseCandidateInstallRequest], HostPreflightResult]
ProvisioningRunner = Callable[
    [ReleaseCandidateInstallRequest],
    SystemProvisioningResult,
]
BaseConfigurationRunner = Callable[
    [ReleaseCandidateInstallRequest, str],
    BaseConfigurationResult,
]
TaskwarriorRunner = Callable[
    [ReleaseCandidateInstallRequest, ReleaseCandidateTaskwarriorInputs],
    ReleaseCandidateTaskwarriorResult,
]
TelegramOnboardingVerifier = Callable[
    [str, TelegramOnboardingConfirmation],
    tuple[InstallerIssue, ...],
]
TelegramConfigurationRunner = Callable[
    [
        ReleaseCandidateInstallRequest,
        TelegramOnboardingConfirmation,
        str,
        bool,
    ],
    TelegramConfigurationResult,
]
SystemdServiceRunner = Callable[
    [ReleaseCandidateInstallRequest, bool],
    TelegramSystemdServiceResult,
]
HealthRunner = Callable[
    [ReleaseCandidateInstallRequest],
    PostInstallHealthResult,
]
AcceptanceRunner = Callable[
    [ReleaseCandidateInstallRequest, PostInstallHealthResult],
    ReleaseCandidateAcceptanceResult,
]


@dataclass(frozen=True, slots=True)
class ReleaseCandidateOrchestrationDependencies:
    """Injected boundaries used by the deterministic coordinator."""

    preflight: PreflightRunner
    provisioning: ProvisioningRunner
    base_configuration: BaseConfigurationRunner
    taskwarrior: TaskwarriorRunner
    telegram_onboarding: TelegramOnboardingVerifier
    telegram_configuration: TelegramConfigurationRunner
    systemd_service: SystemdServiceRunner
    health: HealthRunner
    acceptance: AcceptanceRunner


def create_release_candidate_orchestration_dependencies(
    *,
    taskwarrior_acceptance: TaskwarriorAcceptanceTester | None = None,
    telegram_validation: TelegramAcceptanceValidator | None = None,
    notifier: AcceptanceNotifier | None = None,
) -> ReleaseCandidateOrchestrationDependencies:
    """Create production dependencies from the established installer boundaries."""

    def install_base(
        request: ReleaseCandidateInstallRequest,
        lea_version: str,
    ) -> BaseConfigurationResult:
        return install_base_configuration(
            create_base_configuration_plan(request),
            create_installation_record(
                request=request,
                lea_version=lea_version,
            ),
            apply_ownership=apply_posix_ownership,
        )

    def install_taskwarrior(
        request: ReleaseCandidateInstallRequest,
        inputs: ReleaseCandidateTaskwarriorInputs,
    ) -> ReleaseCandidateTaskwarriorResult:
        return install_release_candidate_taskwarrior(
            create_taskwarrior_installation_plan(
                request,
                inputs,
            )
        )

    def verify_onboarding(
        token: str,
        confirmation: TelegramOnboardingConfirmation,
    ) -> tuple[InstallerIssue, ...]:
        try:
            validate_bot_token_shape(token)
        except (TypeError, ValueError):
            return (
                _issue(
                    InstallerStepId.TELEGRAM_ONBOARDING,
                    "The Telegram bot token has an invalid shape.",
                    field="telegram_token",
                ),
            )

        if not confirmation.confirmed or confirmation.role is None:
            return (
                _issue(
                    InstallerStepId.TELEGRAM_ONBOARDING,
                    "Telegram onboarding has not been confirmed.",
                    field="telegram_confirmation",
                ),
            )

        return ()

    def persist_telegram(
        request: ReleaseCandidateInstallRequest,
        confirmation: TelegramOnboardingConfirmation,
        token: str,
        replacement_approved: bool,
    ) -> TelegramConfigurationResult:
        return persist_telegram_configuration(
            create_telegram_configuration_plan(
                request,
                confirmation,
            ),
            token=token,
            approve_replacement=replacement_approved,
            apply_ownership=apply_posix_ownership,
        )

    def deploy_systemd(
        request: ReleaseCandidateInstallRequest,
        replacement_approved: bool,
    ) -> TelegramSystemdServiceResult:
        return deploy_telegram_systemd_service(
            create_telegram_systemd_service_plan(request),
            approve_replacement=replacement_approved,
        )

    def run_health(
        request: ReleaseCandidateInstallRequest,
    ) -> PostInstallHealthResult:
        return run_post_install_health(create_post_install_health_plan(request))

    def run_acceptance(
        request: ReleaseCandidateInstallRequest,
        health: PostInstallHealthResult,
    ) -> ReleaseCandidateAcceptanceResult:
        return run_release_candidate_acceptance(
            create_post_install_health_plan(request),
            health,
            taskwarrior_acceptance=taskwarrior_acceptance,
            telegram_validation=telegram_validation,
            notifier=notifier,
        )

    return ReleaseCandidateOrchestrationDependencies(
        preflight=run_host_preflight,
        provisioning=lambda request: provision_system_layout(
            create_system_provisioning_plan(request)
        ),
        base_configuration=install_base,
        taskwarrior=install_taskwarrior,
        telegram_onboarding=verify_onboarding,
        telegram_configuration=persist_telegram,
        systemd_service=deploy_systemd,
        health=run_health,
        acceptance=run_acceptance,
    )


def run_release_candidate_orchestration(
    request: ReleaseCandidateOrchestrationRequest,
    *,
    telegram_token: str | None = None,
    telegram_confirmation: TelegramOnboardingConfirmation | None = None,
    dependencies: ReleaseCandidateOrchestrationDependencies | None = None,
    cancelled: CancellationSignal = lambda: False,
) -> ReleaseCandidateOrchestrationResult:
    """Run one deterministic installation attempt through injected boundaries."""
    if not isinstance(request, ReleaseCandidateOrchestrationRequest):
        raise TypeError("request must be a ReleaseCandidateOrchestrationRequest value.")

    selected = request.installation.enable_telegram
    completed: list[InstallerStepResult] = []
    runners = dependencies or create_release_candidate_orchestration_dependencies()

    if not request.plan_approved:
        return _interaction_required(
            request,
            step_results=completed,
            current_step=None,
            interaction=InstallerInteraction(
                kind=InstallerInteractionKind.PLAN_APPROVAL,
                prompt="Approve the release-candidate installation plan.",
                choices=("approve", "cancel"),
            ),
        )

    cancelled_result = _check_cancellation(request, completed, cancelled)
    if cancelled_result is not None:
        return cancelled_result

    preflight, failure = _call_boundary(
        InstallerStepId.PREFLIGHT,
        lambda: runners.preflight(request.installation),
    )
    if failure is not None:
        return _failed_orchestration(request, completed, failure)

    assert isinstance(preflight, HostPreflightResult)
    if not preflight.supported:
        return _failed_orchestration(
            request,
            completed,
            _failed_step(
                InstallerStepId.PREFLIGHT,
                "Host preflight failed.",
                preflight.issues,
            ),
        )

    completed.append(
        _completed_step(
            InstallerStepId.PREFLIGHT,
            "Host preflight completed.",
        )
    )

    if (
        request.installation.mode is not ReleaseCandidateInstallMode.FRESH_INSTALL
        and not request.replacement_approved
    ):
        if request.installation.non_interactive:
            return _failed_orchestration(
                request,
                completed,
                _failed_step(
                    InstallerStepId.SYSTEM_ACCOUNT,
                    "Replacement approval is required before mutation.",
                    (
                        _issue(
                            InstallerStepId.SYSTEM_ACCOUNT,
                            "Non-interactive repair or upgrade requires "
                            "prior replacement approval.",
                            field="replacement_approved",
                        ),
                    ),
                ),
            )

        return _interaction_required(
            request,
            step_results=completed,
            current_step=InstallerStepId.SYSTEM_ACCOUNT,
            interaction=InstallerInteraction(
                kind=InstallerInteractionKind.REPLACEMENT_APPROVAL,
                prompt=(
                    "Approve replacement and repair of existing managed "
                    "installation resources."
                ),
                step=InstallerStepId.SYSTEM_ACCOUNT,
                choices=("approve", "cancel"),
            ),
        )

    cancelled_result = _check_cancellation(request, completed, cancelled)
    if cancelled_result is not None:
        return cancelled_result

    provisioning, failure = _call_boundary(
        InstallerStepId.FILESYSTEM,
        lambda: runners.provisioning(request.installation),
    )
    if failure is not None:
        return _failed_orchestration(request, completed, failure)

    assert isinstance(provisioning, SystemProvisioningResult)
    if not provisioning.success:
        return _failed_orchestration(
            request,
            completed,
            _failed_step(
                InstallerStepId.FILESYSTEM,
                "System provisioning failed.",
                provisioning.issues,
            ),
        )

    account_message = (
        "The LEA service account was created."
        if provisioning.user_created or provisioning.group_created
        else "The LEA service account already existed."
    )
    completed.extend(
        (
            _completed_step(
                InstallerStepId.SYSTEM_ACCOUNT,
                account_message,
            ),
            _completed_step(
                InstallerStepId.FILESYSTEM,
                (
                    "The managed filesystem layout was created or repaired."
                    if provisioning.directories_changed
                    else "The managed filesystem layout was already correct."
                ),
            ),
        )
    )

    cancelled_result = _check_cancellation(request, completed, cancelled)
    if cancelled_result is not None:
        return cancelled_result

    base_configuration, failure = _call_boundary(
        InstallerStepId.BASE_CONFIGURATION,
        lambda: runners.base_configuration(
            request.installation,
            request.lea_version,
        ),
    )
    if failure is not None:
        return _failed_orchestration(request, completed, failure)

    assert isinstance(base_configuration, BaseConfigurationResult)
    if not base_configuration.success:
        return _failed_orchestration(
            request,
            completed,
            _failed_step(
                InstallerStepId.BASE_CONFIGURATION,
                "Base configuration installation failed.",
                base_configuration.issues,
            ),
        )

    completed.append(
        _completed_step(
            InstallerStepId.BASE_CONFIGURATION,
            (
                "Base configuration was installed or updated."
                if (
                    base_configuration.configuration_changed
                    or base_configuration.record_changed
                )
                else "Base configuration was already current."
            ),
        )
    )

    cancelled_result = _check_cancellation(request, completed, cancelled)
    if cancelled_result is not None:
        return cancelled_result

    taskwarrior, failure = _call_boundary(
        InstallerStepId.TASKWARRIOR,
        lambda: runners.taskwarrior(
            request.installation,
            request.taskwarrior,
        ),
    )
    if failure is not None:
        return _failed_orchestration(request, completed, failure)

    assert isinstance(taskwarrior, ReleaseCandidateTaskwarriorResult)
    if not taskwarrior.success:
        return _failed_orchestration(
            request,
            completed,
            _failed_step(
                InstallerStepId.TASKWARRIOR,
                "Taskwarrior installation failed.",
                taskwarrior.issues,
            ),
        )

    completed.append(
        _completed_step(
            InstallerStepId.TASKWARRIOR,
            (
                "The managed Taskwarrior installation was already current."
                if taskwarrior.already_installed
                else "The managed Taskwarrior installation completed."
            ),
        )
    )

    if selected:
        interaction_result = _resolve_telegram_inputs(
            request,
            completed,
            telegram_token=telegram_token,
            telegram_confirmation=telegram_confirmation,
        )
        if interaction_result is not None:
            return interaction_result

        assert telegram_token is not None
        assert telegram_confirmation is not None

        if not telegram_confirmation.confirmed:
            return _cancelled_orchestration(request, completed)

        cancelled_result = _check_cancellation(request, completed, cancelled)
        if cancelled_result is not None:
            return cancelled_result

        onboarding_issues, failure = _call_boundary(
            InstallerStepId.TELEGRAM_ONBOARDING,
            lambda: runners.telegram_onboarding(
                telegram_token,
                telegram_confirmation,
            ),
        )
        if failure is not None:
            return _failed_orchestration(request, completed, failure)

        assert isinstance(onboarding_issues, tuple)
        if onboarding_issues:
            return _failed_orchestration(
                request,
                completed,
                _failed_step(
                    InstallerStepId.TELEGRAM_ONBOARDING,
                    "Telegram onboarding validation failed.",
                    onboarding_issues,
                ),
            )

        completed.append(
            _completed_step(
                InstallerStepId.TELEGRAM_ONBOARDING,
                "Telegram onboarding was confirmed.",
            )
        )

        cancelled_result = _check_cancellation(request, completed, cancelled)
        if cancelled_result is not None:
            return cancelled_result

        telegram_configuration, failure = _call_boundary(
            InstallerStepId.TELEGRAM_CONFIGURATION,
            lambda: runners.telegram_configuration(
                request.installation,
                telegram_confirmation,
                telegram_token,
                request.replacement_approved,
            ),
        )
        if failure is not None:
            return _failed_orchestration(request, completed, failure)

        assert isinstance(
            telegram_configuration,
            TelegramConfigurationResult,
        )
        if not telegram_configuration.success:
            return _failed_orchestration(
                request,
                completed,
                _failed_step(
                    InstallerStepId.TELEGRAM_CONFIGURATION,
                    "Telegram configuration persistence failed.",
                    telegram_configuration.issues,
                ),
            )

        completed.append(
            _completed_step(
                InstallerStepId.TELEGRAM_CONFIGURATION,
                (
                    "Telegram configuration was installed or updated."
                    if telegram_configuration.changed_files
                    else "Telegram configuration was already current."
                ),
            )
        )

        cancelled_result = _check_cancellation(request, completed, cancelled)
        if cancelled_result is not None:
            return cancelled_result

        service, failure = _call_boundary(
            InstallerStepId.SYSTEMD_SERVICE,
            lambda: runners.systemd_service(
                request.installation,
                request.replacement_approved,
            ),
        )
        if failure is not None:
            return _failed_orchestration(request, completed, failure)

        assert isinstance(service, TelegramSystemdServiceResult)
        if not service.success:
            return _failed_orchestration(
                request,
                completed,
                _failed_step(
                    InstallerStepId.SYSTEMD_SERVICE,
                    "Telegram systemd service deployment failed.",
                    service.issues,
                ),
            )

        completed.append(
            _completed_step(
                InstallerStepId.SYSTEMD_SERVICE,
                (
                    "The Telegram systemd service was installed or updated."
                    if service.unit_changed
                    else "The Telegram systemd service was already current."
                ),
            )
        )

    cancelled_result = _check_cancellation(request, completed, cancelled)
    if cancelled_result is not None:
        return cancelled_result

    health, failure = _call_boundary(
        InstallerStepId.HEALTH,
        lambda: runners.health(request.installation),
    )
    if failure is not None:
        return _failed_orchestration(request, completed, failure)

    assert isinstance(health, PostInstallHealthResult)
    if not health.healthy:
        return _failed_orchestration(
            request,
            completed,
            _failed_step(
                InstallerStepId.HEALTH,
                "Post-install health verification failed.",
                health.issues,
            ),
        )

    completed.append(
        _completed_step(
            InstallerStepId.HEALTH,
            "Post-install health verification passed.",
        )
    )

    cancelled_result = _check_cancellation(request, completed, cancelled)
    if cancelled_result is not None:
        return cancelled_result

    acceptance, failure = _call_boundary(
        InstallerStepId.ACCEPTANCE,
        lambda: runners.acceptance(
            request.installation,
            health,
        ),
    )
    if failure is not None:
        return _failed_orchestration(request, completed, failure)

    assert isinstance(acceptance, ReleaseCandidateAcceptanceResult)
    if not acceptance.accepted:
        return _failed_orchestration(
            request,
            completed,
            _failed_step(
                InstallerStepId.ACCEPTANCE,
                (
                    acceptance.summary.strip()
                    or "Release-candidate functional acceptance failed."
                ),
                acceptance.issues,
            ),
        )

    completed.append(
        _completed_step(
            InstallerStepId.ACCEPTANCE,
            (
                acceptance.summary.strip()
                or "Release-candidate functional acceptance passed."
            ),
        )
    )

    return ReleaseCandidateOrchestrationResult(
        state=ReleaseCandidateOrchestrationState.SUCCEEDED,
        request=request,
        current_step=None,
        step_results=tuple(completed),
        telegram_selected=selected,
        pending_interaction=None,
        issues=(),
    )


def _resolve_telegram_inputs(
    request: ReleaseCandidateOrchestrationRequest,
    completed: list[InstallerStepResult],
    *,
    telegram_token: str | None,
    telegram_confirmation: TelegramOnboardingConfirmation | None,
) -> ReleaseCandidateOrchestrationResult | None:
    if telegram_token is None:
        return _missing_interaction(
            request,
            completed,
            InstallerInteraction(
                kind=InstallerInteractionKind.TELEGRAM_TOKEN,
                prompt="Enter the Telegram bot token.",
                step=InstallerStepId.TELEGRAM_ONBOARDING,
                secret=True,
            ),
        )

    if telegram_confirmation is None:
        return _missing_interaction(
            request,
            completed,
            InstallerInteraction(
                kind=InstallerInteractionKind.TELEGRAM_IDENTITY_CONFIRMATION,
                prompt=(
                    "Discover and confirm the private Telegram identity "
                    "before continuing."
                ),
                step=InstallerStepId.TELEGRAM_ONBOARDING,
                choices=("confirm", "cancel"),
            ),
        )

    return None


def _missing_interaction(
    request: ReleaseCandidateOrchestrationRequest,
    completed: list[InstallerStepResult],
    interaction: InstallerInteraction,
) -> ReleaseCandidateOrchestrationResult:
    if not request.installation.non_interactive:
        return _interaction_required(
            request,
            step_results=completed,
            current_step=interaction.step,
            interaction=interaction,
        )

    step = interaction.step or InstallerStepId.PREFLIGHT
    return _failed_orchestration(
        request,
        completed,
        _failed_step(
            step,
            "Required non-interactive installer input was missing.",
            (
                InstallerIssue(
                    code=InstallerIssueCode.INCOMPLETE,
                    message=(
                        "Non-interactive installation cannot request "
                        f"{interaction.kind.value}."
                    ),
                    step=step,
                    field=interaction.kind.value,
                ),
            ),
        ),
    )


def _call_boundary(
    step: InstallerStepId,
    operation: Callable[[], object],
) -> tuple[object | None, InstallerStepResult | None]:
    try:
        return operation(), None
    except Exception:
        return None, _failed_step(
            step,
            f"{step.value} raised an unexpected boundary exception.",
            (
                _issue(
                    step,
                    "The installer boundary failed unexpectedly.",
                ),
            ),
        )


def _check_cancellation(
    request: ReleaseCandidateOrchestrationRequest,
    completed: list[InstallerStepResult],
    cancelled: CancellationSignal,
) -> ReleaseCandidateOrchestrationResult | None:
    try:
        is_cancelled = cancelled()
    except Exception:
        return _failed_orchestration(
            request,
            completed,
            _failed_step(
                InstallerStepId.PREFLIGHT,
                "The cancellation boundary failed.",
                (
                    _issue(
                        InstallerStepId.PREFLIGHT,
                        "The cancellation boundary failed unexpectedly.",
                    ),
                ),
            ),
        )

    if is_cancelled:
        return _cancelled_orchestration(request, completed)

    return None


def _completed_step(
    step: InstallerStepId,
    message: str,
) -> InstallerStepResult:
    return InstallerStepResult(
        step=step,
        state=InstallerStepState.COMPLETED,
        message=message,
    )


def _failed_step(
    step: InstallerStepId,
    message: str,
    issues: tuple[InstallerIssue, ...],
) -> InstallerStepResult:
    effective_issues = issues or (
        _issue(
            step,
            f"{step.value} failed without a structured issue.",
        ),
    )
    return InstallerStepResult(
        step=step,
        state=InstallerStepState.FAILED,
        message=message,
        issues=effective_issues,
    )


def _issue(
    step: InstallerStepId,
    message: str,
    *,
    field: str | None = None,
    path: Path | None = None,
) -> InstallerIssue:
    return InstallerIssue(
        code=InstallerIssueCode.STEP_FAILED,
        message=message,
        step=step,
        field=field,
        path=path,
    )


def _interaction_required(
    request: ReleaseCandidateOrchestrationRequest,
    *,
    step_results: list[InstallerStepResult],
    current_step: InstallerStepId | None,
    interaction: InstallerInteraction,
) -> ReleaseCandidateOrchestrationResult:
    return ReleaseCandidateOrchestrationResult(
        state=ReleaseCandidateOrchestrationState.WAITING_FOR_INTERACTION,
        request=request,
        current_step=current_step,
        step_results=tuple(step_results),
        telegram_selected=request.installation.enable_telegram,
        pending_interaction=interaction,
        issues=(),
    )


def _cancelled_orchestration(
    request: ReleaseCandidateOrchestrationRequest,
    completed: list[InstallerStepResult],
) -> ReleaseCandidateOrchestrationResult:
    return ReleaseCandidateOrchestrationResult(
        state=ReleaseCandidateOrchestrationState.CANCELLED,
        request=request,
        current_step=None,
        step_results=tuple(completed),
        telegram_selected=request.installation.enable_telegram,
        pending_interaction=None,
        issues=(),
    )


def _failed_orchestration(
    request: ReleaseCandidateOrchestrationRequest,
    completed: list[InstallerStepResult],
    failed: InstallerStepResult,
) -> ReleaseCandidateOrchestrationResult:
    return ReleaseCandidateOrchestrationResult(
        state=ReleaseCandidateOrchestrationState.FAILED,
        request=request,
        current_step=None,
        step_results=(*completed, failed),
        telegram_selected=request.installation.enable_telegram,
        pending_interaction=None,
        issues=failed.issues,
    )
