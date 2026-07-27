"""Tests for safe release-candidate purge execution."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from lea.installers.release_candidate.uninstall_contracts import (
    ReleaseCandidateUninstallIssueCode,
    ReleaseCandidateUninstallRequest,
    ReleaseCandidateUninstallStepId,
    ReleaseCandidateUninstallStepState,
)
from lea.installers.release_candidate.uninstall_executor import (
    execute_release_candidate_uninstall,
)
from lea.installers.release_candidate.uninstall_planning import (
    create_release_candidate_uninstall_plan,
)


def _request(tmp_path: Path) -> ReleaseCandidateUninstallRequest:
    """Create one isolated purge request."""
    return ReleaseCandidateUninstallRequest(
        purge=True,
        confirmed=True,
        installation_root=tmp_path / "source",
        configuration_root=tmp_path / "etc" / "lea",
        state_root=tmp_path / "var" / "lib" / "lea",
        log_root=tmp_path / "var" / "log" / "lea",
        taskwarrior_root=tmp_path / "tools" / "taskwarrior",
        systemd_unit=(tmp_path / "systemd" / "lea-telegram.service"),
        tmpfiles_configuration=(tmp_path / "tmpfiles" / "lea.conf"),
        runtime_directory=(tmp_path / "run" / "lea"),
        systemctl=Path("/usr/bin/systemctl"),
    )


def _populate(request: ReleaseCandidateUninstallRequest) -> None:
    """Create every managed path and the service unit."""
    for root in (
        request.configuration_root,
        request.state_root,
        request.log_root,
        request.taskwarrior_root,
    ):
        root.mkdir(parents=True)
        (root / "managed.txt").write_text(
            "managed\n",
            encoding="utf-8",
        )

    request.systemd_unit.parent.mkdir(parents=True)
    request.systemd_unit.write_text(
        "[Unit]\nDescription=LEA Telegram\n",
        encoding="utf-8",
    )

    request.tmpfiles_configuration.parent.mkdir(parents=True)
    request.tmpfiles_configuration.write_text(
        "d /run/lea 0750 lea lea -\n",
        encoding="utf-8",
    )

    request.runtime_directory.mkdir(parents=True)
    (request.runtime_directory / "runtime.txt").write_text(
        "runtime\n",
        encoding="utf-8",
    )


class RecordingRunner:
    """Record exact commands and optionally fail one invocation."""

    def __init__(
        self,
        *,
        fail_command: tuple[str, ...] | None = None,
    ) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.fail_command = fail_command

    def __call__(
        self,
        command: Sequence[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        """Record one command and return a successful process."""
        resolved = tuple(command)
        self.commands.append(resolved)

        if resolved == self.fail_command:
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=resolved,
                stderr="synthetic failure",
            )

        return subprocess.CompletedProcess(
            args=resolved,
            returncode=0,
            stdout="",
            stderr="",
        )


def test_purge_removes_all_managed_resources_in_safe_order(
    tmp_path: Path,
) -> None:
    """A complete purge should remove exact managed resources."""
    request = _request(tmp_path)
    _populate(request)
    runner = RecordingRunner()

    result = execute_release_candidate_uninstall(
        create_release_candidate_uninstall_plan(request),
        command_runner=runner,
        user_exists=lambda name: name == "lea",
        group_exists=lambda name: name == "lea",
    )

    assert result.success is True
    assert result.issues == ()
    assert tuple(step.state for step in result.steps) == (
        ReleaseCandidateUninstallStepState.COMPLETED,
        ReleaseCandidateUninstallStepState.COMPLETED,
        ReleaseCandidateUninstallStepState.COMPLETED,
        ReleaseCandidateUninstallStepState.COMPLETED,
        ReleaseCandidateUninstallStepState.COMPLETED,
        ReleaseCandidateUninstallStepState.COMPLETED,
        ReleaseCandidateUninstallStepState.COMPLETED,
    )

    assert runner.commands == [
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
    ]

    assert not request.systemd_unit.exists()
    assert not request.tmpfiles_configuration.exists()
    assert not request.runtime_directory.exists()
    assert not request.configuration_root.exists()
    assert not request.state_root.exists()
    assert not request.log_root.exists()
    assert not request.taskwarrior_root.exists()

    assert not request.installation_root.exists()


def test_purge_is_idempotent_when_resources_are_absent(
    tmp_path: Path,
) -> None:
    """Already absent managed resources should be skipped successfully."""
    request = _request(tmp_path)
    runner = RecordingRunner()

    result = execute_release_candidate_uninstall(
        create_release_candidate_uninstall_plan(request),
        command_runner=runner,
        user_exists=lambda _name: False,
        group_exists=lambda _name: False,
    )

    assert result.success is True
    assert result.issues == ()
    assert all(
        step.state is ReleaseCandidateUninstallStepState.SKIPPED
        for step in result.steps
    )
    assert runner.commands == [
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
    ]


def test_symlinked_managed_root_is_rejected_without_following(
    tmp_path: Path,
) -> None:
    """A managed-root symlink must not remove its external target."""
    request = _request(tmp_path)
    external = tmp_path / "external-state"
    external.mkdir()
    marker = external / "keep.txt"
    marker.write_text("keep\n", encoding="utf-8")

    request.state_root.parent.mkdir(parents=True)
    request.state_root.symlink_to(
        external,
        target_is_directory=True,
    )

    runner = RecordingRunner()
    result = execute_release_candidate_uninstall(
        create_release_candidate_uninstall_plan(request),
        command_runner=runner,
        user_exists=lambda _name: True,
        group_exists=lambda _name: True,
    )

    assert result.success is False
    assert marker.read_text(encoding="utf-8") == "keep\n"
    assert request.state_root.is_symlink()

    state_result = next(
        step
        for step in result.steps
        if step.step is ReleaseCandidateUninstallStepId.STATE
    )
    assert state_result.state is ReleaseCandidateUninstallStepState.FAILED
    assert state_result.issues[0].code is (
        ReleaseCandidateUninstallIssueCode.UNSAFE_PATH
    )

    account_result = result.steps[-1]
    assert account_result.step is (ReleaseCandidateUninstallStepId.SYSTEM_ACCOUNT)
    assert account_result.state is (ReleaseCandidateUninstallStepState.SKIPPED)
    assert runner.commands == [
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
    ]


def test_service_failure_halts_all_destructive_removal(
    tmp_path: Path,
) -> None:
    """Failure to stop the service should preserve files and accounts."""
    request = _request(tmp_path)
    _populate(request)

    failing = (
        "/usr/bin/systemctl",
        "stop",
        "lea-telegram.service",
    )
    runner = RecordingRunner(fail_command=failing)

    result = execute_release_candidate_uninstall(
        create_release_candidate_uninstall_plan(request),
        command_runner=runner,
        user_exists=lambda _name: True,
        group_exists=lambda _name: True,
    )

    assert result.success is False
    assert result.steps[0].state is (ReleaseCandidateUninstallStepState.FAILED)
    assert all(
        step.state is ReleaseCandidateUninstallStepState.SKIPPED
        for step in result.steps[1:]
    )

    assert request.systemd_unit.is_file()
    assert request.configuration_root.is_dir()
    assert request.state_root.is_dir()
    assert request.log_root.is_dir()
    assert request.taskwarrior_root.is_dir()
    assert runner.commands == [failing]


def test_absent_unit_still_stops_disables_and_reloads(
    tmp_path: Path,
) -> None:
    """An absent unit file should not skip systemd cleanup commands."""
    request = _request(tmp_path)
    runner = RecordingRunner()

    result = execute_release_candidate_uninstall(
        create_release_candidate_uninstall_plan(request),
        command_runner=runner,
        user_exists=lambda _name: False,
        group_exists=lambda _name: False,
    )

    assert result.success is True
    assert result.steps[0].state is (ReleaseCandidateUninstallStepState.SKIPPED)
    assert runner.commands == [
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
    ]


def test_absent_systemd_unit_errors_are_tolerated(
    tmp_path: Path,
) -> None:
    """Missing-unit stop and disable errors should remain idempotent."""
    request = _request(tmp_path)

    class MissingUnitRunner(RecordingRunner):
        def __call__(
            self,
            command: Sequence[str],
            **_kwargs: Any,
        ) -> subprocess.CompletedProcess[str]:
            resolved = tuple(command)
            self.commands.append(resolved)

            if resolved[1] in {"stop", "disable"}:
                raise subprocess.CalledProcessError(
                    returncode=5,
                    cmd=resolved,
                    stderr=("Unit lea-telegram.service not loaded."),
                )

            return subprocess.CompletedProcess(
                args=resolved,
                returncode=0,
                stdout="",
                stderr="",
            )

    runner = MissingUnitRunner()

    result = execute_release_candidate_uninstall(
        create_release_candidate_uninstall_plan(request),
        command_runner=runner,
        user_exists=lambda _name: False,
        group_exists=lambda _name: False,
    )

    assert result.success is True
    assert runner.commands[-1] == (
        "/usr/bin/systemctl",
        "daemon-reload",
    )


def test_group_removal_failure_reports_removed_user(
    tmp_path: Path,
) -> None:
    """A partial account failure should report the completed mutation."""
    request = _request(tmp_path)
    runner = RecordingRunner(
        fail_command=(
            "/usr/sbin/groupdel",
            "lea",
        )
    )

    result = execute_release_candidate_uninstall(
        create_release_candidate_uninstall_plan(request),
        command_runner=runner,
        user_exists=lambda name: name == "lea",
        group_exists=lambda name: name == "lea",
    )

    assert result.success is False

    account_result = result.steps[-1]
    assert account_result.step is (ReleaseCandidateUninstallStepId.SYSTEM_ACCOUNT)
    assert account_result.state is (ReleaseCandidateUninstallStepState.FAILED)
    assert len(account_result.issues) == 1
    assert "CalledProcessError" in account_result.message
    assert "Successfully removed user lea" in account_result.message
    assert (
        "group lea"
        not in account_result.message.split(
            "Successfully removed",
            maxsplit=1,
        )[1]
    )

    assert runner.commands[-2:] == [
        (
            "/usr/sbin/userdel",
            "lea",
        ),
        (
            "/usr/sbin/groupdel",
            "lea",
        ),
    ]


def test_retry_removes_remaining_group_only(
    tmp_path: Path,
) -> None:
    """A retry after partial removal should omit the absent user."""
    request = _request(tmp_path)
    runner = RecordingRunner()

    result = execute_release_candidate_uninstall(
        create_release_candidate_uninstall_plan(request),
        command_runner=runner,
        user_exists=lambda _name: False,
        group_exists=lambda name: name == "lea",
    )

    assert result.success is True

    account_result = result.steps[-1]
    assert account_result.state is (ReleaseCandidateUninstallStepState.COMPLETED)
    assert account_result.message == "Removed managed group lea."

    assert (
        "/usr/sbin/userdel",
        "lea",
    ) not in runner.commands
    assert runner.commands[-1] == (
        "/usr/sbin/groupdel",
        "lea",
    )


def test_user_removal_may_also_remove_private_group(
    tmp_path: Path,
) -> None:
    """The group must be re-checked after deleting its matching user."""
    request = _request(tmp_path)
    runner = RecordingRunner()
    user_present = True
    group_present = True

    def user_exists(_name: str) -> bool:
        return user_present

    def group_exists(_name: str) -> bool:
        return group_present

    def run(
        command: tuple[str, ...],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal user_present, group_present
        runner.commands.append(command)

        if command == ("/usr/sbin/userdel", "lea"):
            user_present = False
            group_present = False

        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="",
            stderr="",
        )

    result = execute_release_candidate_uninstall(
        create_release_candidate_uninstall_plan(request),
        command_runner=run,
        user_exists=user_exists,
        group_exists=group_exists,
    )

    assert result.success is True
    assert runner.commands[-1] == (
        "/usr/sbin/userdel",
        "lea",
    )
    assert (
        "/usr/sbin/groupdel",
        "lea",
    ) not in runner.commands

    account_result = result.steps[-1]
    assert account_result.state is ReleaseCandidateUninstallStepState.COMPLETED
    assert account_result.message == "Removed managed user lea."


def test_symlinked_tmpfiles_configuration_is_rejected(
    tmp_path: Path,
) -> None:
    """Purge must not follow a tmpfiles-configuration symlink."""
    request = _request(tmp_path)
    external = tmp_path / "external.conf"
    external.write_text("keep\n", encoding="utf-8")

    request.tmpfiles_configuration.parent.mkdir(parents=True)
    request.tmpfiles_configuration.symlink_to(external)

    runner = RecordingRunner()
    result = execute_release_candidate_uninstall(
        create_release_candidate_uninstall_plan(request),
        command_runner=runner,
        user_exists=lambda _name: True,
        group_exists=lambda _name: True,
    )

    assert result.success is False
    assert external.read_text(encoding="utf-8") == "keep\n"
    assert request.tmpfiles_configuration.is_symlink()

    runtime_result = next(
        step
        for step in result.steps
        if step.step is ReleaseCandidateUninstallStepId.RUNTIME_RESOURCES
    )
    assert runtime_result.state is ReleaseCandidateUninstallStepState.FAILED
    assert runtime_result.issues[0].code is (
        ReleaseCandidateUninstallIssueCode.UNSAFE_PATH
    )


def test_runtime_resources_are_idempotent_when_absent(
    tmp_path: Path,
) -> None:
    """Absent tmpfiles and runtime paths should be skipped safely."""
    request = _request(tmp_path)
    runner = RecordingRunner()

    result = execute_release_candidate_uninstall(
        create_release_candidate_uninstall_plan(request),
        command_runner=runner,
        user_exists=lambda _name: False,
        group_exists=lambda _name: False,
    )

    runtime_result = next(
        step
        for step in result.steps
        if step.step is ReleaseCandidateUninstallStepId.RUNTIME_RESOURCES
    )
    assert runtime_result.state is ReleaseCandidateUninstallStepState.SKIPPED
