"""Tests for the release-candidate acceptance CLI."""

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from lea.installers.release_candidate import (
    AcceptanceRecordWriteResult,
    InstallerIssue,
    InstallerIssueCode,
    InstallerStepId,
    PostInstallCheck,
    PostInstallCheckState,
    PostInstallHealthResult,
    ReleaseCandidateAcceptanceHarnessPlan,
    ReleaseCandidateAcceptanceHarnessResult,
    ReleaseCandidateAcceptanceResult,
    create_release_candidate_acceptance_record,
)
from lea.release_candidate_acceptance_cli import (
    EXIT_ACCEPTANCE_FAILED,
    EXIT_INTERNAL_ERROR,
    EXIT_SUCCESS,
    EXIT_USAGE_ERROR,
    ReleaseCandidateAcceptanceCliDependencies,
    execute_release_candidate_acceptance_cli,
)


def _passed_health() -> PostInstallHealthResult:
    return PostInstallHealthResult(
        healthy=True,
        checks=(
            PostInstallCheck(
                code="runtime_health",
                message="The runtime health check passed.",
                state=PostInstallCheckState.PASSED,
            ),
        ),
        issues=(),
    )


def _acceptance(
    *,
    accepted: bool,
) -> ReleaseCandidateAcceptanceResult:
    if accepted:
        return ReleaseCandidateAcceptanceResult(
            accepted=True,
            checks=(
                PostInstallCheck(
                    code="taskwarrior_lifecycle",
                    message="The disposable Taskwarrior lifecycle passed.",
                    state=PostInstallCheckState.PASSED,
                ),
            ),
            summary="LEA release-candidate acceptance: PASSED\n",
            issues=(),
        )

    return ReleaseCandidateAcceptanceResult(
        accepted=False,
        checks=(
            PostInstallCheck(
                code="taskwarrior_lifecycle",
                message="The disposable Taskwarrior lifecycle failed.",
                state=PostInstallCheckState.FAILED,
            ),
        ),
        summary="LEA release-candidate acceptance: FAILED\n",
        issues=(
            InstallerIssue(
                code=InstallerIssueCode.STEP_FAILED,
                message="Functional acceptance failed.",
                step=InstallerStepId.ACCEPTANCE,
            ),
        ),
    )


def _completed_result(
    plan: ReleaseCandidateAcceptanceHarnessPlan,
    *,
    accepted: bool,
) -> ReleaseCandidateAcceptanceHarnessResult:
    health = _passed_health()
    acceptance = _acceptance(accepted=accepted)
    record = create_release_candidate_acceptance_record(
        plan.health,
        health,
        acceptance,
        clock=lambda: datetime(2026, 7, 25, 8, 0, tzinfo=UTC),
    )
    write = AcceptanceRecordWriteResult(
        success=True,
        changed=True,
        path=plan.record_file,
        issues=(),
    )
    return ReleaseCandidateAcceptanceHarnessResult(
        success=True,
        accepted=accepted,
        health=health,
        acceptance=acceptance,
        record=record,
        record_write=write,
        issues=(),
    )


def test_success_uses_canonical_installed_paths() -> None:
    captured: list[ReleaseCandidateAcceptanceHarnessPlan] = []

    def run(
        plan: ReleaseCandidateAcceptanceHarnessPlan,
    ) -> ReleaseCandidateAcceptanceHarnessResult:
        captured.append(plan)
        return _completed_result(plan, accepted=True)

    stdout = StringIO()
    stderr = StringIO()

    exit_code = execute_release_candidate_acceptance_cli(
        ["--no-telegram"],
        stdout=stdout,
        stderr=stderr,
        dependencies=ReleaseCandidateAcceptanceCliDependencies(
            harness_runner=run,
        ),
    )

    assert exit_code == EXIT_SUCCESS
    assert stderr.getvalue() == ""
    assert "Outcome: PASSED" in stdout.getvalue()

    plan = captured[0]
    assert plan.health.runtime_config_file == Path("/etc/lea/lea.toml")
    assert plan.health.taskwarrior_record_file == Path(
        "/var/lib/lea/install/taskwarrior.json"
    )
    assert plan.record_file == Path("/var/lib/lea/acceptance/release-candidate.json")
    assert plan.health.telegram_enabled is False


def test_rejected_acceptance_returns_status_one(
    tmp_path: Path,
) -> None:
    def run(
        plan: ReleaseCandidateAcceptanceHarnessPlan,
    ) -> ReleaseCandidateAcceptanceHarnessResult:
        return _completed_result(plan, accepted=False)

    stdout = StringIO()
    stderr = StringIO()

    exit_code = execute_release_candidate_acceptance_cli(
        [
            "--no-telegram",
            "--configuration-root",
            str(tmp_path / "etc" / "lea"),
            "--state-root",
            str(tmp_path / "var" / "lib" / "lea"),
            "--systemctl",
            str(tmp_path / "usr" / "bin" / "systemctl"),
        ],
        stdout=stdout,
        stderr=stderr,
        dependencies=ReleaseCandidateAcceptanceCliDependencies(
            harness_runner=run,
        ),
    )

    assert exit_code == EXIT_ACCEPTANCE_FAILED
    assert stderr.getvalue() == ""
    assert "Outcome: FAILED" in stdout.getvalue()
    assert "taskwarrior_lifecycle" in stdout.getvalue()


def test_harness_failure_returns_internal_error(
    tmp_path: Path,
) -> None:
    def run(
        plan: ReleaseCandidateAcceptanceHarnessPlan,
    ) -> ReleaseCandidateAcceptanceHarnessResult:
        return ReleaseCandidateAcceptanceHarnessResult(
            success=False,
            accepted=False,
            health=None,
            acceptance=None,
            record=None,
            record_write=None,
            issues=(
                InstallerIssue(
                    code=InstallerIssueCode.STEP_FAILED,
                    message="Acceptance harness execution failed.",
                    step=InstallerStepId.ACCEPTANCE,
                    path=plan.record_file,
                ),
            ),
        )

    stdout = StringIO()
    stderr = StringIO()

    exit_code = execute_release_candidate_acceptance_cli(
        [
            "--no-telegram",
            "--configuration-root",
            str(tmp_path / "etc" / "lea"),
            "--state-root",
            str(tmp_path / "var" / "lib" / "lea"),
            "--systemctl",
            str(tmp_path / "usr" / "bin" / "systemctl"),
        ],
        stdout=stdout,
        stderr=stderr,
        dependencies=ReleaseCandidateAcceptanceCliDependencies(
            harness_runner=run,
        ),
    )

    assert exit_code == EXIT_INTERNAL_ERROR
    assert stdout.getvalue() == ""
    assert "Outcome: ERROR" in stderr.getvalue()
    assert "Acceptance harness execution failed." in stderr.getvalue()


def test_relative_paths_are_rejected() -> None:
    called = False

    def run(
        plan: ReleaseCandidateAcceptanceHarnessPlan,
    ) -> ReleaseCandidateAcceptanceHarnessResult:
        nonlocal called
        called = True
        return _completed_result(plan, accepted=True)

    stdout = StringIO()
    stderr = StringIO()

    exit_code = execute_release_candidate_acceptance_cli(
        [
            "--no-telegram",
            "--state-root",
            "relative/state",
        ],
        stdout=stdout,
        stderr=stderr,
        dependencies=ReleaseCandidateAcceptanceCliDependencies(
            harness_runner=run,
        ),
    )

    assert exit_code == EXIT_USAGE_ERROR
    assert called is False
    assert stdout.getvalue() == ""
    assert "state_root must be absolute" in stderr.getvalue()


def test_telegram_and_path_overrides_reach_harness(
    tmp_path: Path,
) -> None:
    captured: list[ReleaseCandidateAcceptanceHarnessPlan] = []
    record_file = tmp_path / "reports" / "acceptance.json"

    def run(
        plan: ReleaseCandidateAcceptanceHarnessPlan,
    ) -> ReleaseCandidateAcceptanceHarnessResult:
        captured.append(plan)
        return _completed_result(plan, accepted=True)

    exit_code = execute_release_candidate_acceptance_cli(
        [
            "--telegram",
            "--configuration-root",
            str(tmp_path / "configuration"),
            "--state-root",
            str(tmp_path / "state"),
            "--systemctl",
            str(tmp_path / "bin" / "systemctl"),
            "--record-file",
            str(record_file),
        ],
        stdout=StringIO(),
        stderr=StringIO(),
        dependencies=ReleaseCandidateAcceptanceCliDependencies(
            harness_runner=run,
        ),
    )

    assert exit_code == EXIT_SUCCESS
    plan = captured[0]
    assert plan.health.telegram_enabled is True
    assert plan.health.telegram_config_file == (
        tmp_path / "configuration" / "telegram" / "telegram.toml"
    )
    assert plan.record_file == record_file


def test_telegram_selection_is_required() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = execute_release_candidate_acceptance_cli(
        [],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == EXIT_USAGE_ERROR
    assert stdout.getvalue() == ""
    assert "--telegram --no-telegram" in stderr.getvalue()
