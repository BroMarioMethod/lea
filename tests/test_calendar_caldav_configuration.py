"""Tests for vdirsyncer CalDAV pair and secret configuration."""

import os
from pathlib import Path

import pytest

from lea.installers.calendar import (
    CalendarCaldavPassword,
    CalendarCaldavSyncConfig,
    CalendarToolchainRuntimeLayout,
    activate_calendar_caldav_configuration,
    provision_calendar_caldav_password,
    render_calendar_caldav_vdirsyncer_configuration,
)


def _layout(tmp_path: Path) -> CalendarToolchainRuntimeLayout:
    return CalendarToolchainRuntimeLayout(
        configuration_directory=tmp_path / "config",
        khal_configuration=tmp_path / "config" / "khal.conf",
        vdirsyncer_configuration=tmp_path / "config" / "vdirsyncer.conf",
        state_root=tmp_path / "state",
        vdirs=tmp_path / "state" / "vdirs",
        khal_state=tmp_path / "state" / "khal",
        vdirsyncer_status=tmp_path / "state" / "vdirsyncer-status",
    )


def test_renderer_builds_two_way_pair_without_plaintext_secret(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    secret = tmp_path / "secrets" / "caldav-password"
    config = CalendarCaldavSyncConfig(
        layout,
        "https://calendar.internal.example/alice/",
        "alice",
        secret,
    )

    rendered = render_calendar_caldav_vdirsyncer_configuration(config)

    assert "[pair lea_calendars]" in rendered
    assert 'collections = ["from a", "from b"]' in rendered
    assert "conflict_resolution = null" in rendered
    assert "[storage lea_local]" in rendered
    assert 'type = "filesystem"' in rendered
    assert f'path = "{layout.vdirs}"' in rendered
    assert "[storage lea_radicale]" in rendered
    assert 'type = "caldav"' in rendered
    assert 'username = "alice"' in rendered
    assert f'password.fetch = ["command", "/usr/bin/cat", "{secret}"]' in rendered
    assert "correct horse battery staple" not in rendered
    assert '["shell"' not in rendered


def test_password_file_is_restrictive_idempotent_and_redaction_safe(
    tmp_path: Path,
) -> None:
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    path = secrets / "caldav-password"
    password = CalendarCaldavPassword("correct horse battery staple")

    created = provision_calendar_caldav_password(path, password)
    repeated = provision_calendar_caldav_password(path, password)

    assert created.success is True
    assert created.changed is True
    assert repeated.success is True
    assert repeated.changed is False
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.read_text(encoding="utf-8") == "correct horse battery staple\n"
    assert "correct horse battery staple" not in repr(created)


def test_password_mismatch_is_preserved_without_secret_diagnostic(
    tmp_path: Path,
) -> None:
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    path = secrets / "caldav-password"
    path.write_text("old-secret-value\n", encoding="utf-8")
    path.chmod(0o600)

    result = provision_calendar_caldav_password(
        path, CalendarCaldavPassword("replacement")
    )

    assert result.success is False
    assert result.issues[0].code == "calendar_caldav_secret_mismatch"
    assert "old-secret-value" not in result.issues[0].message
    assert "replacement" not in result.issues[0].message
    assert path.read_text(encoding="utf-8") == "old-secret-value\n"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://calendar.example/alice/",
        "https://alice:secret@calendar.example/",
        "https://calendar.example/alice/?token=secret",
        "https://calendar.example/alice/#fragment",
        "https://calendar.example/alice",
    ],
)
def test_config_rejects_unsafe_or_ambiguous_urls(tmp_path: Path, url: str) -> None:
    with pytest.raises(ValueError):
        CalendarCaldavSyncConfig(
            _layout(tmp_path), url, "alice", tmp_path / "secrets" / "password"
        )


def _activatable_config(tmp_path: Path) -> CalendarCaldavSyncConfig:
    layout = _layout(tmp_path)
    layout.configuration_directory.mkdir()
    layout.vdirsyncer_configuration.write_text(
        '[general]\nstatus_path = "' + str(layout.vdirsyncer_status) + '"\n',
        encoding="utf-8",
    )
    layout.vdirsyncer_configuration.chmod(0o640)
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    password_file = secrets / "password"
    assert provision_calendar_caldav_password(
        password_file, CalendarCaldavPassword("secret-value")
    ).success
    reader = tmp_path / "read-secret"
    reader.write_text("#!/bin/sh\n", encoding="utf-8")
    os.chmod(reader, 0o750)
    return CalendarCaldavSyncConfig(
        layout,
        "https://calendar.internal.example/alice/",
        "alice",
        password_file,
        reader,
    )


def test_activation_requires_approval_then_backs_up_and_is_idempotent(
    tmp_path: Path,
) -> None:
    config = _activatable_config(tmp_path)

    denied = activate_calendar_caldav_configuration(config, approve_replacement=False)
    activated = activate_calendar_caldav_configuration(config, approve_replacement=True)
    repeated = activate_calendar_caldav_configuration(config, approve_replacement=True)

    assert denied.success is False
    assert denied.issues[0].code == "calendar_caldav_replacement_approval_required"
    assert activated.success is True
    assert activated.changed is True
    assert activated.backup_file is not None
    assert activated.backup_file.read_text(encoding="utf-8").startswith("[general]")
    assert repeated.success is True
    assert repeated.changed is False
    assert config.layout.vdirsyncer_configuration.read_text() == (
        render_calendar_caldav_vdirsyncer_configuration(config)
    )


def test_activation_preserves_unrecognized_configuration_drift(tmp_path: Path) -> None:
    config = _activatable_config(tmp_path)
    config.layout.vdirsyncer_configuration.write_text("custom\n", encoding="utf-8")

    result = activate_calendar_caldav_configuration(config, approve_replacement=True)

    assert result.success is False
    assert result.issues[0].code == "calendar_caldav_configuration_drift"
    assert config.layout.vdirsyncer_configuration.read_text() == "custom\n"
    assert not config.layout.vdirsyncer_configuration.with_name(
        "vdirsyncer.conf.local-only.backup"
    ).exists()
