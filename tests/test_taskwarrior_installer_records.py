"""Tests for Taskwarrior installation-record reading and matching."""

import json
from datetime import UTC, datetime
from pathlib import Path

from lea.installers.taskwarrior import (
    TaskwarriorInstallationRecord,
    TaskwarriorInstallFailureCode,
    installation_record_matches,
    read_taskwarrior_installation_record,
    render_taskwarrior_installation_record,
)

INSTALLED_AT = datetime(2026, 7, 21, 18, 30, tzinfo=UTC)


def make_record(tmp_path: Path) -> TaskwarriorInstallationRecord:
    """Return one deterministic installation record."""
    return TaskwarriorInstallationRecord(
        schema_version=1,
        component="taskwarrior",
        version="3.4.2",
        mode="bundled-binary",
        platform="linux-aarch64",
        executable=tmp_path / "tools" / "3.4.2" / "bin" / "task",
        sha256="a" * 64,
        taskrc=tmp_path / "config" / "taskrc",
        home=tmp_path / "state" / "home",
        data=tmp_path / "state" / "data",
        smoke_test="passed",
        installed_at=INSTALLED_AT,
    )


def test_record_round_trip(tmp_path: Path) -> None:
    """Rendered records should read back without information loss."""
    record = make_record(tmp_path)
    path = tmp_path / "taskwarrior.json"
    path.write_text(
        render_taskwarrior_installation_record(record),
        encoding="utf-8",
    )

    parsed, issues = read_taskwarrior_installation_record(path)

    assert issues == ()
    assert parsed == record


def test_missing_record_returns_structured_issue(
    tmp_path: Path,
) -> None:
    """Missing records should fail closed."""
    path = tmp_path / "missing.json"

    record, issues = read_taskwarrior_installation_record(path)

    assert record is None
    assert issues[0].code is TaskwarriorInstallFailureCode.RECORD_FAILED


def test_unknown_record_key_is_rejected(tmp_path: Path) -> None:
    """Unexpected JSON fields should fail strict validation."""
    record = make_record(tmp_path)
    payload = json.loads(render_taskwarrior_installation_record(record))
    payload["unexpected"] = True
    path = tmp_path / "taskwarrior.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    parsed, issues = read_taskwarrior_installation_record(path)

    assert parsed is None
    assert issues[0].code is TaskwarriorInstallFailureCode.RECORD_FAILED


def test_non_utc_z_timestamp_is_rejected(tmp_path: Path) -> None:
    """Stored timestamps should use the canonical UTC Z representation."""
    record = make_record(tmp_path)
    payload = json.loads(render_taskwarrior_installation_record(record))
    payload["installed_at"] = "2026-07-21T20:30:00+02:00"
    path = tmp_path / "taskwarrior.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    parsed, issues = read_taskwarrior_installation_record(path)

    assert parsed is None
    assert issues


def test_installation_record_matching(tmp_path: Path) -> None:
    """Matching should cover immutable installation identity."""
    record = make_record(tmp_path)

    assert installation_record_matches(
        record,
        version="3.4.2",
        platform="linux-aarch64",
        executable=record.executable,
        sha256="a" * 64,
    )
    assert not installation_record_matches(
        record,
        version="3.4.3",
        platform="linux-aarch64",
        executable=record.executable,
        sha256="a" * 64,
    )
