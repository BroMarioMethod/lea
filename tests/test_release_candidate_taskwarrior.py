"""Tests for release-candidate Taskwarrior integration."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lea.installers.release_candidate import (
    ReleaseCandidateInstallMode,
    ReleaseCandidateInstallRequest,
    ReleaseCandidateTaskwarriorInputs,
    create_taskwarrior_installation_plan,
    install_release_candidate_taskwarrior,
)
from lea.installers.taskwarrior import (
    TaskwarriorInstallationRecord,
    TaskwarriorInstallerIssue,
    TaskwarriorInstallFailureCode,
    TaskwarriorInstallMode,
    TaskwarriorInstallResult,
)


def _request(tmp_path: Path) -> ReleaseCandidateInstallRequest:
    """Return one isolated release-candidate request."""
    return ReleaseCandidateInstallRequest(
        mode=ReleaseCandidateInstallMode.FRESH_INSTALL,
        display_timezone="Africa/Gaborone",
        enable_telegram=False,
        configuration_root=tmp_path / "etc" / "lea",
        state_root=tmp_path / "var" / "lib" / "lea",
        log_root=tmp_path / "var" / "log" / "lea",
    )


def _inputs(tmp_path: Path) -> ReleaseCandidateTaskwarriorInputs:
    """Return valid pinned source-build inputs."""
    archive = tmp_path / "task-3.4.2.tar.gz"
    archive.write_bytes(b"source")

    return ReleaseCandidateTaskwarriorInputs(
        version="3.4.2",
        platform="arm64",
        source_archive=archive,
        expected_sha256="a" * 64,
        build_directory=tmp_path / "build",
        build_concurrency=1,
    )


def _record(plan: Any) -> TaskwarriorInstallationRecord:
    """Return a deterministic successful component record."""
    return TaskwarriorInstallationRecord(
        schema_version=1,
        component="taskwarrior",
        version=plan.config.version,
        mode=TaskwarriorInstallMode.SOURCE_BUILD.value,
        platform="linux-aarch64",
        executable=plan.expected_executable,
        sha256="b" * 64,
        taskrc=plan.config.configuration_dir / "taskrc",
        home=plan.config.state_root / "home",
        data=plan.config.state_root / "data",
        smoke_test="passed",
        installed_at=datetime(2026, 7, 24, tzinfo=UTC),
    )


def test_plan_reuses_existing_taskwarrior_installer_contract(
    tmp_path: Path,
) -> None:
    """The release-candidate plan should build the existing config contract."""
    request = _request(tmp_path)
    inputs = _inputs(tmp_path)

    plan = create_taskwarrior_installation_plan(request, inputs)

    assert plan.config.mode is TaskwarriorInstallMode.SOURCE_BUILD
    assert plan.config.version == "3.4.2"
    assert plan.config.tools_root == Path("/opt/lea-tools/taskwarrior")
    assert plan.config.configuration_dir == (request.configuration_root / "taskwarrior")
    assert plan.config.state_root == request.state_root / "taskwarrior"
    assert plan.config.installation_record == (
        request.state_root / "install" / "taskwarrior.json"
    )
    assert plan.expected_executable == Path("/opt/lea-tools/taskwarrior/3.4.2/bin/task")


def test_installation_delegates_to_existing_dispatcher(
    tmp_path: Path,
) -> None:
    """The release-candidate boundary should not duplicate build logic."""
    plan = create_taskwarrior_installation_plan(
        _request(tmp_path),
        _inputs(tmp_path),
    )
    record = _record(plan)
    calls: list[tuple[Any, bool]] = []

    def installer(config: Any, *, fsync: bool) -> TaskwarriorInstallResult:
        calls.append((config, fsync))
        return TaskwarriorInstallResult(
            success=True,
            already_installed=False,
            record=record,
            issues=(),
        )

    result = install_release_candidate_taskwarrior(
        plan,
        installer=installer,
    )

    assert result.success is True
    assert result.executable == plan.expected_executable
    assert result.record == record
    assert calls == [(plan.config, True)]


def test_already_installed_state_is_preserved(
    tmp_path: Path,
) -> None:
    """Idempotent component results should remain visible."""
    plan = create_taskwarrior_installation_plan(
        _request(tmp_path),
        _inputs(tmp_path),
    )
    record = _record(plan)

    def installer(config: Any, *, fsync: bool) -> TaskwarriorInstallResult:
        return TaskwarriorInstallResult(
            success=True,
            already_installed=True,
            record=record,
            issues=(),
        )

    result = install_release_candidate_taskwarrior(
        plan,
        installer=installer,
    )

    assert result.success is True
    assert result.already_installed is True


def test_component_issues_are_translated(
    tmp_path: Path,
) -> None:
    """Taskwarrior failures should become release-candidate step issues."""
    plan = create_taskwarrior_installation_plan(
        _request(tmp_path),
        _inputs(tmp_path),
    )
    component_issue = TaskwarriorInstallerIssue(
        code=TaskwarriorInstallFailureCode.BUILD_FAILED,
        message="Build failed.",
        field="build_directory",
        path=plan.config.build_directory,
    )

    def installer(config: Any, *, fsync: bool) -> TaskwarriorInstallResult:
        return TaskwarriorInstallResult(
            success=False,
            already_installed=False,
            record=None,
            issues=(component_issue,),
        )

    result = install_release_candidate_taskwarrior(
        plan,
        installer=installer,
    )

    assert result.success is False
    assert result.issues[0].message == "Build failed."
    assert result.issues[0].field == "build_directory"
    assert result.issues[0].path == plan.config.build_directory


def test_unexpected_executable_path_is_rejected(
    tmp_path: Path,
) -> None:
    """Successful component records must identify the managed executable."""
    plan = create_taskwarrior_installation_plan(
        _request(tmp_path),
        _inputs(tmp_path),
    )
    record = TaskwarriorInstallationRecord(
        schema_version=1,
        component="taskwarrior",
        version="3.4.2",
        mode=TaskwarriorInstallMode.SOURCE_BUILD.value,
        platform="linux-aarch64",
        executable=tmp_path / "unexpected" / "task",
        sha256="b" * 64,
        taskrc=plan.config.configuration_dir / "taskrc",
        home=plan.config.state_root / "home",
        data=plan.config.state_root / "data",
        smoke_test="passed",
        installed_at=datetime(2026, 7, 24, tzinfo=UTC),
    )

    def installer(config: Any, *, fsync: bool) -> TaskwarriorInstallResult:
        return TaskwarriorInstallResult(
            success=True,
            already_installed=False,
            record=record,
            issues=(),
        )

    result = install_release_candidate_taskwarrior(
        plan,
        installer=installer,
    )

    assert result.success is False
    assert result.record is None
