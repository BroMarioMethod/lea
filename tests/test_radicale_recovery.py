"""Regression tests for root-only calendar-provider recovery archives."""

import os
from pathlib import Path
from typing import Any

from lea.installers.radicale.recovery import (
    create_calendar_provider_backup,
    restore_calendar_provider_backup_isolated,
)


def test_backup_is_0600_from_creation_and_restores_isolated(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(os, "fchown", lambda *_args: None)
    source = tmp_path / "secret"
    source.mkdir(mode=0o700)
    (source / "users").write_text("credential")
    archive = tmp_path / "backup.tar.gz"
    created = create_calendar_provider_backup(archive, sources=(("secrets", source),))
    assert created.success is True
    assert archive.stat().st_mode & 0o777 == 0o600
    destination = tmp_path / "restore"
    restored = restore_calendar_provider_backup_isolated(archive, destination)
    assert restored.success is True
    assert (destination / "secrets").stat().st_mode & 0o777 == 0o700
    assert (destination / "secrets/users").read_text() == "credential"


def test_backup_rejects_symbolic_content(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    source = tmp_path / "source"
    source.mkdir()
    (source / "link").symlink_to(tmp_path / "elsewhere")
    result = create_calendar_provider_backup(
        tmp_path / "backup.tar.gz", sources=(("source", source),)
    )
    assert result.success is False
    assert result.code == "backup_source_symlink"
