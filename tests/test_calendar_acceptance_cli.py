"""Tests for the Android calendar acceptance CLI."""

from io import StringIO
from pathlib import Path

from lea.calendar_acceptance_cli import execute_calendar_acceptance_cli


def test_cli_requires_every_explicit_live_confirmation(tmp_path: Path) -> None:
    stderr = StringIO()

    exit_code = execute_calendar_acceptance_cli(
        ["--record-file", str(tmp_path / "record.json")],
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert "Every Android calendar acceptance check must pass" in stderr.getvalue()


def test_cli_rejects_relative_record_path() -> None:
    stderr = StringIO()

    exit_code = execute_calendar_acceptance_cli(
        [
            "--record-file",
            "calendar-android.json",
            "--server-to-android-verified",
            "--android-to-server-verified",
            "--user-isolation-verified",
            "--backup-verified",
        ],
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert "--record-file must be absolute" in stderr.getvalue()


def test_cli_writes_non_secret_acceptance_evidence(tmp_path: Path) -> None:
    path = tmp_path / "acceptance" / "calendar-android.json"
    path.parent.mkdir()
    stdout = StringIO()

    exit_code = execute_calendar_acceptance_cli(
        [
            "--record-file",
            str(path),
            "--server-to-android-verified",
            "--android-to-server-verified",
            "--user-isolation-verified",
            "--backup-verified",
        ],
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert path.is_file()
    assert "recorded" in stdout.getvalue()
    assert "password" not in path.read_text(encoding="utf-8").lower()
