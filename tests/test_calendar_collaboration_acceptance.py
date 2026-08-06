"""Tests for Milestone 4.1 credential-free acceptance evidence."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from lea.calendars import (
    CalendarCollaborationAcceptanceRecord,
    create_calendar_collaboration_acceptance_record,
    write_calendar_collaboration_acceptance_record,
)


def _record() -> CalendarCollaborationAcceptanceRecord:
    return create_calendar_collaboration_acceptance_record(
        accepted_at=datetime(2026, 8, 6, tzinfo=UTC),
        server_to_android_verified=True,
        android_to_server_verified=True,
        recurrence_verified=True,
        attendee_response_verified=True,
        reboot_verified=True,
        user_isolation_verified=True,
        backup_verified=True,
    )


def test_record_requires_new_collaboration_checks() -> None:
    with pytest.raises(ValueError, match="Every"):
        create_calendar_collaboration_acceptance_record(
            accepted_at=datetime(2026, 8, 6, tzinfo=UTC),
            server_to_android_verified=True,
            android_to_server_verified=True,
            recurrence_verified=False,
            attendee_response_verified=True,
            reboot_verified=True,
            user_isolation_verified=True,
            backup_verified=True,
        )


def test_record_is_restrictive_atomic_and_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "acceptance" / "calendar-collaboration.json"
    path.parent.mkdir()

    assert write_calendar_collaboration_acceptance_record(path, _record()) is True
    assert write_calendar_collaboration_acceptance_record(path, _record()) is True
    assert path.stat().st_mode & 0o777 == 0o640
    document = path.read_text(encoding="utf-8")
    assert "password" not in document.lower()
    assert "attendee@example" not in document


def test_different_existing_record_is_not_replaced(tmp_path: Path) -> None:
    path = tmp_path / "acceptance.json"
    path.write_text("existing\n", encoding="utf-8")

    assert write_calendar_collaboration_acceptance_record(path, _record()) is False
    assert path.read_text(encoding="utf-8") == "existing\n"
