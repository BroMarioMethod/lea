"""Immutable guided installer orchestration contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from lea.installers.release_candidate.calendar import (
    ReleaseCandidateCalendarInputs,
)
from lea.installers.release_candidate.contracts import (
    InstallerIssue,
    InstallerStepId,
    InstallerStepResult,
    InstallerStepState,
    ReleaseCandidateInstallRequest,
)
from lea.installers.release_candidate.taskwarrior import (
    ReleaseCandidateTaskwarriorInputs,
)


class InstallerInteractionKind(StrEnum):
    """Interactive decisions supported by the guided installer."""

    PLAN_APPROVAL = "plan-approval"
    REPLACEMENT_APPROVAL = "replacement-approval"
    TELEGRAM_TOKEN = "telegram-token"
    TELEGRAM_IDENTITY_CONFIRMATION = "telegram-identity-confirmation"
    TELEGRAM_ROLE_SELECTION = "telegram-role-selection"


class ReleaseCandidateOrchestrationState(StrEnum):
    """Possible states for one guided installation attempt."""

    RUNNING = "running"
    WAITING_FOR_INTERACTION = "waiting-for-interaction"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class InstallerInteraction:
    """One explicit interaction required before orchestration may continue."""

    kind: InstallerInteractionKind
    prompt: str
    step: InstallerStepId | None = None
    secret: bool = False
    choices: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate one interaction request."""
        if not self.prompt.strip():
            raise ValueError("prompt must be non-empty.")

        if any(not choice.strip() for choice in self.choices):
            raise ValueError("choices must contain only non-empty values.")

        if len(set(self.choices)) != len(self.choices):
            raise ValueError("choices must not contain duplicates.")

        if self.kind is InstallerInteractionKind.TELEGRAM_TOKEN:
            if not self.secret:
                raise ValueError("Telegram token interaction must be secret.")
            if self.choices:
                raise ValueError("Telegram token interaction must not contain choices.")
        elif self.secret:
            raise ValueError("Only Telegram token interaction may be marked secret.")


@dataclass(frozen=True, slots=True)
class ReleaseCandidateOrchestrationRequest:
    """Complete non-secret input for one guided installation attempt."""

    installation: ReleaseCandidateInstallRequest
    taskwarrior: ReleaseCandidateTaskwarriorInputs
    lea_version: str
    plan_approved: bool
    replacement_approved: bool = False
    calendar: ReleaseCandidateCalendarInputs | None = None

    def __post_init__(self) -> None:
        """Validate orchestration inputs."""
        if not isinstance(self.installation, ReleaseCandidateInstallRequest):
            raise TypeError(
                "installation must be a ReleaseCandidateInstallRequest value."
            )

        if not isinstance(
            self.taskwarrior,
            ReleaseCandidateTaskwarriorInputs,
        ):
            raise TypeError(
                "taskwarrior must be a ReleaseCandidateTaskwarriorInputs value."
            )

        if self.calendar is not None and not isinstance(
            self.calendar,
            ReleaseCandidateCalendarInputs,
        ):
            raise TypeError(
                "calendar must be a ReleaseCandidateCalendarInputs value when supplied."
            )

        if not self.lea_version.strip():
            raise ValueError("lea_version must be non-empty.")

        if self.installation.non_interactive and not self.plan_approved:
            raise ValueError(
                "Non-interactive orchestration requires prior plan approval."
            )


@dataclass(frozen=True, slots=True)
class ReleaseCandidateOrchestrationResult:
    """Complete resumable state of one guided installation attempt."""

    state: ReleaseCandidateOrchestrationState
    request: ReleaseCandidateOrchestrationRequest
    current_step: InstallerStepId | None
    step_results: tuple[InstallerStepResult, ...]
    telegram_selected: bool
    pending_interaction: InstallerInteraction | None
    issues: tuple[InstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate orchestration-state consistency."""
        if self.telegram_selected != self.request.installation.enable_telegram:
            raise ValueError("telegram_selected must match the installation request.")

        step_ids = tuple(result.step for result in self.step_results)
        if len(set(step_ids)) != len(step_ids):
            raise ValueError(
                "step_results must not contain duplicate step identifiers."
            )

        if any(
            result.state is InstallerStepState.PLANNED for result in self.step_results
        ):
            raise ValueError("step_results must contain only attempted step outcomes.")

        telegram_steps = {
            InstallerStepId.TELEGRAM_ONBOARDING,
            InstallerStepId.TELEGRAM_CONFIGURATION,
            InstallerStepId.SYSTEMD_SERVICE,
        }
        if not self.telegram_selected:
            supplied_steps = set(step_ids)
            if self.current_step is not None:
                supplied_steps.add(self.current_step)
            if self.pending_interaction is not None:
                interaction_step = self.pending_interaction.step
                if interaction_step is not None:
                    supplied_steps.add(interaction_step)

            if telegram_steps & supplied_steps:
                raise ValueError(
                    "Telegram-disabled orchestration must not contain Telegram steps."
                )

        failed_steps = tuple(
            result
            for result in self.step_results
            if result.state is InstallerStepState.FAILED
        )

        if self.state is ReleaseCandidateOrchestrationState.RUNNING:
            if self.current_step is None:
                raise ValueError("A running orchestration must contain a current step.")
            if self.pending_interaction is not None:
                raise ValueError(
                    "A running orchestration must not contain a pending interaction."
                )
            if failed_steps or self.issues:
                raise ValueError("A running orchestration must not contain failures.")
            return

        if self.state is ReleaseCandidateOrchestrationState.WAITING_FOR_INTERACTION:
            if self.pending_interaction is None:
                raise ValueError("A waiting orchestration must contain an interaction.")
            if self.current_step != self.pending_interaction.step:
                raise ValueError(
                    "current_step must match the pending interaction step."
                )
            if failed_steps or self.issues:
                raise ValueError("A waiting orchestration must not contain failures.")
            return

        if self.current_step is not None:
            raise ValueError(
                "A terminal orchestration must not contain a current step."
            )

        if self.pending_interaction is not None:
            raise ValueError(
                "A terminal orchestration must not contain a pending interaction."
            )

        if self.state is ReleaseCandidateOrchestrationState.SUCCEEDED:
            if failed_steps or self.issues:
                raise ValueError(
                    "A successful orchestration must not contain failures."
                )
            return

        if self.state is ReleaseCandidateOrchestrationState.FAILED:
            if not failed_steps and not self.issues:
                raise ValueError(
                    "A failed orchestration must contain a failed step or issue."
                )
            return

        if failed_steps or self.issues:
            raise ValueError(
                "A cancelled orchestration must remain separate from failure."
            )
