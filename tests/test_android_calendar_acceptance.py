"""Tests for credential-free Android calendar acceptance evidence."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from lea.calendars import (
    create_android_calendar_acceptance_record,
    write_android_calendar_acceptance_record,
)


def test_acceptance_record_requires_every_live_check() -> None:
    with pytest.raises(ValueError, match="Every"):
        create_android_calendar_acceptance_record(
            accepted_at=datetime(2026, 8, 4, tzinfo=UTC),
            server_to_android_verified=True,
            android_to_server_verified=False,
            user_isolation_verified=True,
            backup_verified=True,
        )


def test_acceptance_record_is_atomic_restrictive_and_idempotent(
    tmp_path: Path,
) -> None:
    record = create_android_calendar_acceptance_record(
        accepted_at=datetime(2026, 8, 4, 12, tzinfo=UTC),
        server_to_android_verified=True,
        android_to_server_verified=True,
        user_isolation_verified=True,
        backup_verified=True,
    )
    path = tmp_path / "acceptance" / "calendar-android.json"
    path.parent.mkdir()

    created = write_android_calendar_acceptance_record(path, record)
    repeated = write_android_calendar_acceptance_record(path, record)

    assert created.success is True
    assert created.changed is True
    assert repeated.success is True
    assert repeated.changed is False
    assert path.stat().st_mode & 0o777 == 0o640
    document = path.read_text(encoding="utf-8")
    assert "password" not in document.lower()
    assert "device" not in document.lower()
    assert "event" not in document.lower()


def test_existing_different_acceptance_is_not_replaced(tmp_path: Path) -> None:
    path = tmp_path / "acceptance.json"
    path.write_text("existing\n", encoding="utf-8")
    path.chmod(0o640)
    record = create_android_calendar_acceptance_record(
        accepted_at=datetime(2026, 8, 4, tzinfo=UTC),
        server_to_android_verified=True,
        android_to_server_verified=True,
        user_isolation_verified=True,
        backup_verified=True,
    )

    result = write_android_calendar_acceptance_record(path, record)

    assert result.success is False
    assert result.issues[0].code == "android_acceptance_record_mismatch"
    assert path.read_text(encoding="utf-8") == "existing\n"
