"""Tests for release-candidate acceptance-harness execution."""

import json
from datetime import UTC, datetime
from pathlib import Path

from lea.installers.release_candidate import (
    AcceptanceRecordWriteResult,
    InstallerIssue,
    InstallerIssueCode,
    InstallerStepId,
    PostInstallCheck,
    PostInstallCheckState,
    PostInstallHealthPlan,
    PostInstallHealthResult,
    ReleaseCandidateAcceptanceResult,
)
from lea.installers.release_candidate.acceptance_harness import (
    ReleaseCandidateAcceptanceHarnessDependencies,
    create_release_candidate_acceptance_harness_plan,
    run_release_candidate_acceptance_harness,
)


def _health_plan(tmp_path: Path) -> PostInstallHealthPlan:
    return PostInstallHealthPlan(
        runtime_config_file=tmp_path / "etc" / "lea" / "lea.toml",
        telegram_config_file=(tmp_path / "etc" / "lea" / "telegram" / "telegram.toml"),
        installation_record_file=(
            tmp_path / "var" / "lib" / "lea" / "install" / "release-candidate.json"
        ),
        taskwarrior_record_file=(
            tmp_path / "var" / "lib" / "lea" / "install" / "taskwarrior.json"
        ),
        acceptance_work_directory=(
            tmp_path / "var" / "lib" / "lea" / "acceptance" / "taskwarrior"
        ),
        systemctl=tmp_path / "usr" / "bin" / "systemctl",
        telegram_service_name="lea-telegram.service",
        telegram_enabled=False,
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


def _passed_acceptance() -> ReleaseCandidateAcceptanceResult:
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


def _failed_health() -> PostInstallHealthResult:
    return PostInstallHealthResult(
        healthy=False,
        checks=(
            PostInstallCheck(
                code="runtime_health",
                message="The runtime health check failed.",
                state=PostInstallCheckState.FAILED,
            ),
        ),
        issues=(
            InstallerIssue(
                code=InstallerIssueCode.STEP_FAILED,
                message="One or more health checks failed.",
                step=InstallerStepId.HEALTH,
            ),
        ),
    )


def test_plan_uses_canonical_acceptance_record_path(
    tmp_path: Path,
) -> None:
    health = _health_plan(tmp_path)

    plan = create_release_candidate_acceptance_harness_plan(health)

    assert plan.record_file == (
        tmp_path / "var" / "lib" / "lea" / "acceptance" / "release-candidate.json"
    )
    assert plan.record_mode == 0o640


def test_harness_composes_checks_and_persists_record(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def run_health(
        _plan: PostInstallHealthPlan,
    ) -> PostInstallHealthResult:
        calls.append("health")
        return _passed_health()

    def run_acceptance(
        _plan: PostInstallHealthPlan,
        health: PostInstallHealthResult,
    ) -> ReleaseCandidateAcceptanceResult:
        calls.append("acceptance")
        assert health.healthy is True
        return _passed_acceptance()

    plan = create_release_candidate_acceptance_harness_plan(_health_plan(tmp_path))

    result = run_release_candidate_acceptance_harness(
        plan,
        dependencies=ReleaseCandidateAcceptanceHarnessDependencies(
            run_health=run_health,
            run_acceptance=run_acceptance,
        ),
        clock=lambda: datetime(2026, 7, 25, 8, 0, tzinfo=UTC),
    )

    assert result.success is True
    assert result.accepted is True
    assert result.record is not None
    assert result.record_write is not None
    assert result.record_write.success is True
    assert result.record_write.changed is True
    assert calls == ["health", "acceptance"]

    payload = json.loads(plan.record_file.read_text(encoding="utf-8"))
    assert payload["accepted"] is True
    assert payload["health"]["healthy"] is True
    assert payload["acceptance"]["accepted"] is True


def test_failed_health_is_recorded_as_rejected_acceptance(
    tmp_path: Path,
) -> None:
    plan = create_release_candidate_acceptance_harness_plan(_health_plan(tmp_path))

    result = run_release_candidate_acceptance_harness(
        plan,
        dependencies=ReleaseCandidateAcceptanceHarnessDependencies(
            run_health=lambda _plan: _failed_health(),
        ),
        clock=lambda: datetime(2026, 7, 25, 8, 0, tzinfo=UTC),
    )

    assert result.success is True
    assert result.accepted is False
    assert result.acceptance is not None
    assert result.acceptance.accepted is False
    assert result.record_write is not None
    assert result.record_write.success is True

    payload = json.loads(plan.record_file.read_text(encoding="utf-8"))
    assert payload["accepted"] is False
    assert payload["health"]["healthy"] is False
    assert payload["acceptance"]["accepted"] is False


def test_record_write_failure_preserves_acceptance_outcome(
    tmp_path: Path,
) -> None:
    plan = create_release_candidate_acceptance_harness_plan(_health_plan(tmp_path))

    def fail_write(
        _record: object,
        destination: Path,
        *,
        mode: int,
    ) -> AcceptanceRecordWriteResult:
        assert mode == 0o640
        return AcceptanceRecordWriteResult(
            success=False,
            changed=False,
            path=destination,
            issues=(
                InstallerIssue(
                    code=InstallerIssueCode.STEP_FAILED,
                    message="Acceptance record could not be written.",
                    step=InstallerStepId.ACCEPTANCE,
                    path=destination,
                ),
            ),
        )

    result = run_release_candidate_acceptance_harness(
        plan,
        dependencies=ReleaseCandidateAcceptanceHarnessDependencies(
            run_health=lambda _plan: _passed_health(),
            run_acceptance=lambda _plan, _health: _passed_acceptance(),
            write_record=fail_write,
        ),
        clock=lambda: datetime(2026, 7, 25, 8, 0, tzinfo=UTC),
    )

    assert result.success is False
    assert result.accepted is True
    assert result.record is not None
    assert result.record.accepted is True
    assert result.record_write is not None
    assert result.record_write.success is False
    assert result.issues == result.record_write.issues


def test_boundary_exception_is_sanitised(
    tmp_path: Path,
) -> None:
    plan = create_release_candidate_acceptance_harness_plan(_health_plan(tmp_path))

    def fail_health(
        _plan: PostInstallHealthPlan,
    ) -> PostInstallHealthResult:
        raise RuntimeError("sensitive internal health detail")

    result = run_release_candidate_acceptance_harness(
        plan,
        dependencies=ReleaseCandidateAcceptanceHarnessDependencies(
            run_health=fail_health,
        ),
    )

    assert result.success is False
    assert result.accepted is False
    assert result.health is None
    assert result.acceptance is None
    assert result.record is None
    assert result.record_write is None
    assert result.issues[0].message == ("Release-candidate health execution failed.")
    assert "sensitive" not in result.issues[0].message
    assert not plan.record_file.exists()
