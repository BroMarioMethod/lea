"""Deterministic release-candidate uninstall planning."""

from lea.installers.release_candidate.uninstall_contracts import (
    ReleaseCandidateUninstallMutation,
    ReleaseCandidateUninstallMutationKind,
    ReleaseCandidateUninstallPlan,
    ReleaseCandidateUninstallRequest,
    ReleaseCandidateUninstallStepId,
    ReleaseCandidateUninstallStepPlan,
)


def create_release_candidate_uninstall_plan(
    request: ReleaseCandidateUninstallRequest,
) -> ReleaseCandidateUninstallPlan:
    """Create one non-mutating release-candidate purge plan."""
    if not isinstance(request, ReleaseCandidateUninstallRequest):
        raise TypeError("request must be a ReleaseCandidateUninstallRequest value.")

    service_name = request.systemd_unit.name

    return ReleaseCandidateUninstallPlan(
        request=request,
        steps=(
            ReleaseCandidateUninstallStepPlan(
                step=ReleaseCandidateUninstallStepId.SYSTEMD_SERVICE,
                summary=(
                    "Stop, disable and remove the managed Telegram systemd service."
                ),
                mutations=(
                    ReleaseCandidateUninstallMutation(
                        kind=(ReleaseCandidateUninstallMutationKind.STOP_SERVICE),
                        summary=(f"Stop the managed service {service_name}."),
                        command=(
                            str(request.systemctl),
                            "stop",
                            service_name,
                        ),
                    ),
                    ReleaseCandidateUninstallMutation(
                        kind=(ReleaseCandidateUninstallMutationKind.DISABLE_SERVICE),
                        summary=(f"Disable the managed service {service_name}."),
                        command=(
                            str(request.systemctl),
                            "disable",
                            service_name,
                        ),
                    ),
                    ReleaseCandidateUninstallMutation(
                        kind=(ReleaseCandidateUninstallMutationKind.REMOVE_FILE),
                        summary="Remove the managed systemd unit file.",
                        target=request.systemd_unit,
                    ),
                    ReleaseCandidateUninstallMutation(
                        kind=(
                            ReleaseCandidateUninstallMutationKind.RELOAD_SERVICE_MANAGER
                        ),
                        summary="Reload the systemd service manager.",
                        command=(
                            str(request.systemctl),
                            "daemon-reload",
                        ),
                    ),
                ),
            ),
            ReleaseCandidateUninstallStepPlan(
                step=ReleaseCandidateUninstallStepId.RUNTIME_RESOURCES,
                summary=(
                    "Remove the persistent runtime-directory rule and "
                    "the current volatile runtime directory."
                ),
                mutations=(
                    ReleaseCandidateUninstallMutation(
                        kind=(ReleaseCandidateUninstallMutationKind.REMOVE_FILE),
                        summary=("Remove the managed systemd tmpfiles configuration."),
                        target=request.tmpfiles_configuration,
                    ),
                    ReleaseCandidateUninstallMutation(
                        kind=(ReleaseCandidateUninstallMutationKind.REMOVE_DIRECTORY),
                        summary=("Remove the current volatile LEA runtime directory."),
                        target=request.runtime_directory,
                    ),
                ),
            ),
            ReleaseCandidateUninstallStepPlan(
                step=ReleaseCandidateUninstallStepId.TASKWARRIOR,
                summary="Remove the managed Taskwarrior installation.",
                mutations=(
                    ReleaseCandidateUninstallMutation(
                        kind=(ReleaseCandidateUninstallMutationKind.REMOVE_DIRECTORY),
                        summary=("Remove LEA's managed Taskwarrior root."),
                        target=request.taskwarrior_root,
                    ),
                ),
            ),
            ReleaseCandidateUninstallStepPlan(
                step=ReleaseCandidateUninstallStepId.CALENDAR_TOOLCHAIN,
                summary="Remove the managed calendar client toolchain.",
                mutations=(
                    ReleaseCandidateUninstallMutation(
                        kind=(ReleaseCandidateUninstallMutationKind.REMOVE_DIRECTORY),
                        summary="Remove LEA's managed calendar toolchain root.",
                        target=request.calendar_toolchain_root,
                    ),
                ),
            ),
            ReleaseCandidateUninstallStepPlan(
                step=ReleaseCandidateUninstallStepId.CONFIGURATION,
                summary="Remove managed LEA configuration and secrets.",
                mutations=(
                    ReleaseCandidateUninstallMutation(
                        kind=(ReleaseCandidateUninstallMutationKind.REMOVE_DIRECTORY),
                        summary="Remove LEA's managed configuration root.",
                        target=request.configuration_root,
                    ),
                ),
            ),
            ReleaseCandidateUninstallStepPlan(
                step=ReleaseCandidateUninstallStepId.STATE,
                summary=(
                    "Remove managed LEA state, records, backups and "
                    "failure diagnostics."
                ),
                mutations=(
                    ReleaseCandidateUninstallMutation(
                        kind=(ReleaseCandidateUninstallMutationKind.REMOVE_DIRECTORY),
                        summary="Remove LEA's managed state root.",
                        target=request.state_root,
                    ),
                ),
            ),
            ReleaseCandidateUninstallStepPlan(
                step=ReleaseCandidateUninstallStepId.LOGS,
                summary="Remove managed LEA logs.",
                mutations=(
                    ReleaseCandidateUninstallMutation(
                        kind=(ReleaseCandidateUninstallMutationKind.REMOVE_DIRECTORY),
                        summary="Remove LEA's managed log root.",
                        target=request.log_root,
                    ),
                ),
            ),
            ReleaseCandidateUninstallStepPlan(
                step=ReleaseCandidateUninstallStepId.SYSTEM_ACCOUNT,
                summary="Remove the managed LEA service user and group.",
                mutations=(
                    ReleaseCandidateUninstallMutation(
                        kind=(ReleaseCandidateUninstallMutationKind.REMOVE_USER),
                        summary=(f"Remove service user {request.service_user}."),
                        command=(
                            "/usr/sbin/userdel",
                            request.service_user,
                        ),
                    ),
                    ReleaseCandidateUninstallMutation(
                        kind=(ReleaseCandidateUninstallMutationKind.REMOVE_GROUP),
                        summary=(f"Remove service group {request.service_group}."),
                        command=(
                            "/usr/sbin/groupdel",
                            request.service_group,
                        ),
                    ),
                ),
            ),
        ),
    )
