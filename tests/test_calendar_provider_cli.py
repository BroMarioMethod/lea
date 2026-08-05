"""Tests for protected calendar-provider administrative inputs."""

from pathlib import Path

import pytest

from lea import calendar_provider_cli


def test_credentials_file_loads_canonical_accounts_without_exposing_hashes() -> None:
    credentials = calendar_provider_cli._parse_credentials_document(
        "alpha:$2b$12$.....................................................\n"
        "beta:$2b$12$/////////////////////////////////////////////////////\n"
    )
    assert tuple(value.username for value in credentials) == ("alpha", "beta")


def test_credentials_file_rejects_noncanonical_document() -> None:
    with pytest.raises(ValueError, match="canonical htpasswd"):
        calendar_provider_cli._parse_credentials_document("missing-separator\n")


def test_provider_parent_policy_is_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[tuple[Path, int, str, str]] = []
    monkeypatch.setattr(Path, "exists", lambda _path: True)
    monkeypatch.setattr(Path, "is_dir", lambda _path: True)
    monkeypatch.setattr(Path, "is_symlink", lambda _path: False)
    monkeypatch.setattr(Path, "mkdir", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        calendar_provider_cli,
        "_apply_and_verify",
        lambda path, mode, owner, group, **_kwargs: observed.append(
            (path, mode, owner, group)
        ),
    )
    calendar_provider_cli._prepare_provider_parents()
    assert observed == [
        (Path("/opt/lea-tools/radicale"), 0o750, "root", "lea"),
        (Path("/var/lib/lea/secrets"), 0o750, "root", "lea"),
        (Path("/var/lib/lea/secrets/calendar"), 0o700, "lea", "lea"),
    ]


def test_caldav_configuration_policy_is_service_readable() -> None:
    layout = calendar_provider_cli._calendar_layout()
    assert layout.vdirsyncer_configuration == Path("/etc/lea/calendar/vdirsyncer.conf")
