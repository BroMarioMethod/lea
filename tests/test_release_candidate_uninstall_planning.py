"""Tests for deterministic release-candidate uninstall planning."""

from pathlib import Path

import pytest

from lea.installers.release_candidate.uninstall_contracts import (
    ReleaseCandidateUninstallMutationKind,
    ReleaseCandidateUninstallRequest,
    ReleaseCandidateUninstallStepId,
)
from lea.installers.release_candidate.uninstall_planning import (
    create_release_candidate_uninstall_plan,
)


def _request() -> ReleaseCandidateUninstallRequest:
    """Return one safe test purge request."""
    return ReleaseCandidateUninstallRequest(
        purge=True,
        confirmed=True,
        installation_root=Path("/srv/lea-source"),
        configuration_root=Path("/srv/lea-config"),
        state_root=Path("/srv/lea-state"),
        log_root=Path("/srv/lea-log"),
        taskwarrior_root=Path("/srv/lea-tools/taskwarrior"),
        systemd_unit=Path("/srv/systemd/lea-telegram.service"),
        tmpfiles_configuration=Path("/srv/tmpfiles/lea.conf"),
        runtime_directory=Path("/srv/run/lea"),
        systemctl=Path("/usr/bin/systemctl"),
    )


def test_requires_explicit_purge_and_confirmation() -> None:
    """Uninstall requests should require both destructive approvals."""
    with pytest.raises(ValueError, match="purge must be true"):
        ReleaseCandidateUninstallRequest(
            purge=False,
            confirmed=True,
        )

    with pytest.raises(ValueError, match="confirmed must be true"):
        ReleaseCandidateUninstallRequest(
            purge=True,
            confirmed=False,
        )


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("configuration_root", Path("/")),
        ("state_root", Path("/var")),
        ("log_root", Path("/var/log")),
        ("taskwarrior_root", Path("/opt")),
    ],
)
def test_rejects_unsafe_destructive_roots(
    field_name: str,
    value: Path,
) -> None:
    """Purge must reject broad system roots."""
    with pytest.raises(ValueError, match="unsafe"):
        if field_name == "configuration_root":
            ReleaseCandidateUninstallRequest(
                purge=True,
                confirmed=True,
                configuration_root=value,
            )
        elif field_name == "state_root":
            ReleaseCandidateUninstallRequest(
                purge=True,
                confirmed=True,
                state_root=value,
            )
        elif field_name == "log_root":
            ReleaseCandidateUninstallRequest(
                purge=True,
                confirmed=True,
                log_root=value,
            )
        elif field_name == "taskwarrior_root":
            ReleaseCandidateUninstallRequest(
                purge=True,
                confirmed=True,
                taskwarrior_root=value,
            )
        else:
            raise AssertionError(f"Unexpected destructive-root field: {field_name}")


def test_plan_orders_service_before_files_and_account() -> None:
    """The service should stop before files and accounts are removed."""
    plan = create_release_candidate_uninstall_plan(_request())

    assert tuple(step.step for step in plan.steps) == (
        ReleaseCandidateUninstallStepId.SYSTEMD_SERVICE,
        ReleaseCandidateUninstallStepId.RUNTIME_RESOURCES,
        ReleaseCandidateUninstallStepId.TASKWARRIOR,
        ReleaseCandidateUninstallStepId.CONFIGURATION,
        ReleaseCandidateUninstallStepId.STATE,
        ReleaseCandidateUninstallStepId.LOGS,
        ReleaseCandidateUninstallStepId.SYSTEM_ACCOUNT,
    )


def test_plan_preserves_repository_and_release_assets() -> None:
    """The uninstall plan must not target source or release assets."""
    plan = create_release_candidate_uninstall_plan(_request())

    targets = {
        mutation.target
        for step in plan.steps
        for mutation in step.mutations
        if mutation.target is not None
    }

    assert Path("/srv/lea-source") not in targets
    assert Path("/opt/lea-release-assets") not in targets


def test_plan_uses_exact_non_shell_commands() -> None:
    """Service and account operations should be exact command tuples."""
    plan = create_release_candidate_uninstall_plan(_request())

    commands = tuple(
        mutation.command
        for step in plan.steps
        for mutation in step.mutations
        if mutation.command is not None
    )

    assert commands == (
        (
            "/usr/bin/systemctl",
            "stop",
            "lea-telegram.service",
        ),
        (
            "/usr/bin/systemctl",
            "disable",
            "lea-telegram.service",
        ),
        (
            "/usr/bin/systemctl",
            "daemon-reload",
        ),
        (
            "/usr/sbin/userdel",
            "lea",
        ),
        (
            "/usr/sbin/groupdel",
            "lea",
        ),
    )


def test_plan_contains_only_expected_destructive_targets() -> None:
    """The plan should enumerate the complete managed purge surface."""
    request = _request()
    plan = create_release_candidate_uninstall_plan(request)

    targets = tuple(
        mutation.target
        for step in plan.steps
        for mutation in step.mutations
        if mutation.target is not None
    )

    assert targets == (
        request.systemd_unit,
        request.tmpfiles_configuration,
        request.runtime_directory,
        request.taskwarrior_root,
        request.configuration_root,
        request.state_root,
        request.log_root,
    )

    kinds = {mutation.kind for step in plan.steps for mutation in step.mutations}
    assert ReleaseCandidateUninstallMutationKind.REMOVE_DIRECTORY in kinds
    assert ReleaseCandidateUninstallMutationKind.REMOVE_USER in kinds
    assert ReleaseCandidateUninstallMutationKind.REMOVE_GROUP in kinds
