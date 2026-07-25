"""Tests for persistent release-candidate acceptance records."""

import json
import stat
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from lea.installers.release_candidate import (
    PostInstallCheck,
    PostInstallCheckState,
    PostInstallHealthPlan,
    PostInstallHealthResult,
    ReleaseCandidateAcceptanceResult,
)
from lea.installers.release_candidate.acceptance_record import (
    create_release_candidate_acceptance_record,
    render_release_candidate_acceptance_record,
    write_release_candidate_acceptance_record,
)


def _plan(tmp_path: Path) -> PostInstallHealthPlan:
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


def _health() -> PostInstallHealthResult:
    return PostInstallHealthResult(
        healthy=True,
        checks=(
            PostInstallCheck(
                code="runtime_health",
                message="The runtime health check passed.",
                state=PostInstallCheckState.PASSED,
                path=Path("/etc/lea/lea.toml"),
            ),
        ),
        issues=(),
    )


def _acceptance(
    *,
    summary: str = "LEA release-candidate acceptance: PASSED\n",
) -> ReleaseCandidateAcceptanceResult:
    return ReleaseCandidateAcceptanceResult(
        accepted=True,
        checks=(
            PostInstallCheck(
                code="taskwarrior_lifecycle",
                message="The disposable Taskwarrior lifecycle passed.",
                state=PostInstallCheckState.PASSED,
                path=Path("/opt/lea/tools/taskwarrior/bin/task"),
            ),
        ),
        summary=summary,
        issues=(),
    )


def test_create_acceptance_record_normalises_timestamp_to_utc(
    tmp_path: Path,
) -> None:
    record = create_release_candidate_acceptance_record(
        _plan(tmp_path),
        _health(),
        _acceptance(),
        clock=lambda: datetime(
            2026,
            7,
            25,
            10,
            0,
            tzinfo=timezone(timedelta(hours=2)),
        ),
    )

    assert record.schema_version == 1
    assert record.component == "lea-release-candidate-acceptance"
    assert record.accepted is True
    assert record.recorded_at_utc == "2026-07-25T08:00:00+00:00"
    assert record.health_healthy is True
    assert record.acceptance_accepted is True


def test_render_acceptance_record_is_deterministic_and_secret_free(
    tmp_path: Path,
) -> None:
    secret = "123456789:telegram-secret-value"
    record = create_release_candidate_acceptance_record(
        _plan(tmp_path),
        _health(),
        _acceptance(summary=f"Sensitive summary: {secret}\n"),
        clock=lambda: datetime(2026, 7, 25, 8, 0, tzinfo=UTC),
    )

    first = render_release_candidate_acceptance_record(record)
    second = render_release_candidate_acceptance_record(record)
    payload = json.loads(first)

    assert first == second
    assert first.endswith("\n")
    assert secret not in first
    assert payload["accepted"] is True
    assert payload["health"]["healthy"] is True
    assert payload["acceptance"]["accepted"] is True
    assert payload["health"]["checks"][0]["state"] == "passed"
    assert payload["acceptance"]["checks"][0]["state"] == "passed"


def test_write_acceptance_record_is_atomic_and_idempotent(
    tmp_path: Path,
) -> None:
    record = create_release_candidate_acceptance_record(
        _plan(tmp_path),
        _health(),
        _acceptance(),
        clock=lambda: datetime(2026, 7, 25, 8, 0, tzinfo=UTC),
    )
    destination = (
        tmp_path / "var" / "lib" / "lea" / "acceptance" / "release-candidate.json"
    )

    first = write_release_candidate_acceptance_record(
        record,
        destination,
    )
    second = write_release_candidate_acceptance_record(
        record,
        destination,
    )

    assert first.success is True
    assert first.changed is True
    assert second.success is True
    assert second.changed is False
    assert destination.read_text(encoding="utf-8") == (
        render_release_candidate_acceptance_record(record)
    )
    assert stat.S_IMODE(destination.stat().st_mode) == 0o640
    assert not tuple(destination.parent.glob(f".{destination.name}.*.tmp"))


def test_write_acceptance_record_rejects_symlink_destination(
    tmp_path: Path,
) -> None:
    record = create_release_candidate_acceptance_record(
        _plan(tmp_path),
        _health(),
        _acceptance(),
        clock=lambda: datetime(2026, 7, 25, 8, 0, tzinfo=UTC),
    )
    target = tmp_path / "target.json"
    target.write_text("do not replace\n", encoding="utf-8")
    destination = tmp_path / "acceptance.json"
    destination.symlink_to(target)

    result = write_release_candidate_acceptance_record(
        record,
        destination,
    )

    assert result.success is False
    assert result.changed is False
    assert result.issues[0].path == destination
    assert "OSError" in result.issues[0].message
    assert target.read_text(encoding="utf-8") == "do not replace\n"
