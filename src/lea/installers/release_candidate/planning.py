"""Deterministic release-candidate installation planning and rendering."""

from __future__ import annotations

from lea.installers.release_candidate.calendar import (
    ReleaseCandidateCalendarInputs,
    create_calendar_toolchain_installation_plan,
)
from lea.installers.release_candidate.configuration import (
    create_base_configuration_plan,
)
from lea.installers.release_candidate.contracts import (
    InstallerMutation,
    InstallerMutationKind,
    InstallerStepId,
    InstallerStepPlan,
    ReleaseCandidateInstallPlan,
    ReleaseCandidateInstallRequest,
)
from lea.installers.release_candidate.provisioning import (
    create_system_provisioning_plan,
)
from lea.installers.release_candidate.systemd_service import (
    create_telegram_systemd_service_plan,
)
from lea.installers.release_candidate.taskwarrior import (
    ReleaseCandidateTaskwarriorInputs,
    create_taskwarrior_installation_plan,
)


def create_release_candidate_install_plan(
    request: ReleaseCandidateInstallRequest,
    taskwarrior_inputs: ReleaseCandidateTaskwarriorInputs,
    calendar_inputs: ReleaseCandidateCalendarInputs | None = None,
) -> ReleaseCandidateInstallPlan:
    """Create the complete non-mutating plan shown before approval."""
    if not isinstance(request, ReleaseCandidateInstallRequest):
        raise TypeError("request must be a ReleaseCandidateInstallRequest value.")

    if not isinstance(
        taskwarrior_inputs,
        ReleaseCandidateTaskwarriorInputs,
    ):
        raise TypeError(
            "taskwarrior_inputs must be a ReleaseCandidateTaskwarriorInputs value."
        )

    if calendar_inputs is not None and not isinstance(
        calendar_inputs,
        ReleaseCandidateCalendarInputs,
    ):
        raise TypeError(
            "calendar_inputs must be a ReleaseCandidateCalendarInputs "
            "value when supplied."
        )

    provisioning = create_system_provisioning_plan(request)
    base = create_base_configuration_plan(request)
    taskwarrior = create_taskwarrior_installation_plan(
        request,
        taskwarrior_inputs,
    )

    steps: list[InstallerStepPlan] = [
        InstallerStepPlan(
            step=InstallerStepId.PREFLIGHT,
            summary="Inspect host compatibility without mutation.",
            mutations=(),
        ),
        InstallerStepPlan(
            step=InstallerStepId.SYSTEM_ACCOUNT,
            summary="Create or verify the dedicated LEA service identity.",
            mutations=(
                InstallerMutation(
                    kind=InstallerMutationKind.CREATE_GROUP,
                    summary=(
                        "Create the system group "
                        f"'{provisioning.service_group}' when missing."
                    ),
                ),
                InstallerMutation(
                    kind=InstallerMutationKind.CREATE_USER,
                    summary=(
                        "Create the system user "
                        f"'{provisioning.service_user}' when missing."
                    ),
                ),
            ),
        ),
        InstallerStepPlan(
            step=InstallerStepId.FILESYSTEM,
            summary="Create or repair the managed filesystem layout.",
            mutations=(
                *(
                    InstallerMutation(
                        kind=InstallerMutationKind.CREATE_DIRECTORY,
                        summary=(
                            "Ensure directory ownership "
                            f"{directory.owner}:{directory.group} "
                            f"and mode {directory.mode:#06o}."
                        ),
                        target=directory.path,
                    )
                    for directory in provisioning.directories
                ),
                InstallerMutation(
                    kind=InstallerMutationKind.WRITE_FILE,
                    summary=(
                        "Install the systemd tmpfiles rule that recreates "
                        "the volatile LEA runtime directory after boot."
                    ),
                    target=provisioning.tmpfiles_configuration.path,
                ),
            ),
        ),
        InstallerStepPlan(
            step=InstallerStepId.BASE_CONFIGURATION,
            summary="Install the base runtime configuration and release record.",
            mutations=(
                InstallerMutation(
                    kind=InstallerMutationKind.CREATE_DIRECTORY,
                    summary="Create the base-configuration backup directory.",
                    target=base.backup_directory,
                ),
                InstallerMutation(
                    kind=InstallerMutationKind.WRITE_FILE,
                    summary="Write the canonical LEA runtime configuration.",
                    target=base.configuration_file,
                ),
                InstallerMutation(
                    kind=InstallerMutationKind.WRITE_FILE,
                    summary="Write the release-candidate installation record.",
                    target=base.installation_record,
                ),
            ),
        ),
        InstallerStepPlan(
            step=InstallerStepId.TASKWARRIOR,
            summary=(
                "Install the pinned Taskwarrior "
                f"{taskwarrior_inputs.version} source build."
            ),
            mutations=(
                InstallerMutation(
                    kind=InstallerMutationKind.INSTALL_COMPONENT,
                    summary=(
                        "Build and activate Taskwarrior for "
                        f"{taskwarrior_inputs.platform} from "
                        f"{taskwarrior_inputs.source_archive}."
                    ),
                    target=taskwarrior.expected_executable,
                ),
                InstallerMutation(
                    kind=InstallerMutationKind.WRITE_FILE,
                    summary="Write the managed Taskwarrior runtime configuration.",
                    target=taskwarrior.config.configuration_dir / "taskrc",
                ),
                InstallerMutation(
                    kind=InstallerMutationKind.WRITE_FILE,
                    summary="Write the Taskwarrior installation record.",
                    target=taskwarrior.config.installation_record,
                ),
            ),
        ),
    ]

    if calendar_inputs is not None:
        calendar = create_calendar_toolchain_installation_plan(
            request,
            calendar_inputs,
        )
        steps.append(
            InstallerStepPlan(
                step=InstallerStepId.CALENDAR_TOOLCHAIN,
                summary=(
                    "Install the pinned khal "
                    f"{calendar_inputs.khal_version} and vdirsyncer "
                    f"{calendar_inputs.vdirsyncer_version} toolchain."
                ),
                mutations=(
                    InstallerMutation(
                        kind=InstallerMutationKind.INSTALL_COMPONENT,
                        summary=(
                            "Create and activate the verified calendar "
                            "environment from the pinned requirements lock."
                        ),
                        target=calendar.expected_khal_executable,
                    ),
                    InstallerMutation(
                        kind=InstallerMutationKind.WRITE_FILE,
                        summary="Write the managed khal configuration.",
                        target=calendar.config.configuration_dir / "khal.conf",
                    ),
                    InstallerMutation(
                        kind=InstallerMutationKind.WRITE_FILE,
                        summary="Write the managed vdirsyncer configuration.",
                        target=(calendar.config.configuration_dir / "vdirsyncer.conf"),
                    ),
                    InstallerMutation(
                        kind=InstallerMutationKind.WRITE_FILE,
                        summary="Write the calendar installation record.",
                        target=calendar.config.installation_record,
                    ),
                ),
            )
        )

    if request.enable_telegram:
        telegram_root = request.configuration_root / "telegram"
        telegram_backup = request.state_root / "backups" / "telegram"
        systemd = create_telegram_systemd_service_plan(request)

        steps.extend(
            (
                InstallerStepPlan(
                    step=InstallerStepId.TELEGRAM_ONBOARDING,
                    summary=(
                        "Validate the Telegram bot and confirm one private "
                        "authorised identity."
                    ),
                    mutations=(),
                ),
                InstallerStepPlan(
                    step=InstallerStepId.TELEGRAM_CONFIGURATION,
                    summary=(
                        "Persist Telegram runtime, identity and secret-file "
                        "configuration."
                    ),
                    mutations=(
                        InstallerMutation(
                            kind=InstallerMutationKind.CREATE_DIRECTORY,
                            summary=(
                                "Create the Telegram configuration backup directory."
                            ),
                            target=telegram_backup,
                        ),
                        InstallerMutation(
                            kind=InstallerMutationKind.WRITE_FILE,
                            summary=(
                                "Update the base runtime configuration with "
                                "the Telegram token-file reference."
                            ),
                            target=request.configuration_root / "lea.toml",
                        ),
                        InstallerMutation(
                            kind=InstallerMutationKind.WRITE_FILE,
                            summary="Write the Telegram worker configuration.",
                            target=telegram_root / "telegram.toml",
                        ),
                        InstallerMutation(
                            kind=InstallerMutationKind.WRITE_FILE,
                            summary="Write the authorised Telegram identity.",
                            target=telegram_root / "authorised-users.toml",
                        ),
                        InstallerMutation(
                            kind=InstallerMutationKind.WRITE_FILE,
                            summary="Write the Telegram worker environment.",
                            target=telegram_root / "worker.env",
                        ),
                        InstallerMutation(
                            kind=InstallerMutationKind.WRITE_FILE,
                            summary=(
                                "Write the Telegram bot token to a restricted "
                                "secret file."
                            ),
                            target=(
                                request.configuration_root
                                / "secrets"
                                / "telegram-bot-token"
                            ),
                        ),
                    ),
                ),
                InstallerStepPlan(
                    step=InstallerStepId.SYSTEMD_SERVICE,
                    summary="Install, enable and start the Telegram service.",
                    mutations=(
                        InstallerMutation(
                            kind=InstallerMutationKind.INSTALL_SERVICE,
                            summary="Install the Telegram systemd unit.",
                            target=systemd.destination_file,
                        ),
                        InstallerMutation(
                            kind=InstallerMutationKind.ENABLE_SERVICE,
                            summary="Enable the Telegram systemd service.",
                            target=systemd.destination_file,
                        ),
                        InstallerMutation(
                            kind=InstallerMutationKind.START_SERVICE,
                            summary="Start or restart the Telegram systemd service.",
                            target=systemd.destination_file,
                        ),
                    ),
                ),
            )
        )

    steps.extend(
        (
            InstallerStepPlan(
                step=InstallerStepId.HEALTH,
                summary="Run read-only post-install health verification.",
                mutations=(),
            ),
            InstallerStepPlan(
                step=InstallerStepId.ACCEPTANCE,
                summary="Run disposable functional acceptance checks.",
                mutations=(),
            ),
        )
    )

    return ReleaseCandidateInstallPlan(
        request=request,
        steps=tuple(steps),
    )


def render_release_candidate_install_plan(
    plan: ReleaseCandidateInstallPlan,
) -> str:
    """Render one stable human-readable installation plan."""
    if not isinstance(plan, ReleaseCandidateInstallPlan):
        raise TypeError("plan must be a ReleaseCandidateInstallPlan value.")

    lines = [
        "LEA release-candidate installation plan",
        "",
        f"Mode: {plan.request.mode.value}",
        f"Display timezone: {plan.request.display_timezone}",
        ("Telegram: enabled" if plan.request.enable_telegram else "Telegram: disabled"),
        "",
        "Planned steps:",
    ]

    for index, step in enumerate(plan.steps, start=1):
        optional = " (optional)" if step.optional else ""
        lines.append(f"{index}. {step.step.value}{optional}: {step.summary}")

        if not step.mutations:
            lines.append("   - No mutation.")
            continue

        for mutation in step.mutations:
            privilege = "root" if mutation.requires_root else "user"
            target = f" -> {mutation.target}" if mutation.target is not None else ""
            lines.append(
                f"   - [{privilege}] {mutation.kind.value}: {mutation.summary}{target}"
            )

    return "\n".join(lines) + "\n"
