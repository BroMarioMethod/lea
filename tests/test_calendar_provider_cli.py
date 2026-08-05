"""Tests for protected calendar-provider administrative inputs."""

import urllib.request
from pathlib import Path
from typing import Any

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


def test_bootstrap_creates_and_verifies_declared_remote_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[Any] = []

    class Response:
        def __init__(self, status: int) -> None:
            self.status = status

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    responses = iter((Response(201), Response(207)))

    def urlopen(request: Any, **_kwargs: Any) -> Response:
        requests.append(request)
        return next(responses)

    monkeypatch.setattr(calendar_provider_cli, "_protected_line", lambda _path: "pw")
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        urlopen,
    )
    calendar_provider_cli._bootstrap_remote_collection(
        "http://192.168.1.2:5232/",
        "account",
        Path("/root/password"),
        "lea-calendar",
    )
    assert [request.method for request in requests] == ["MKCALENDAR", "PROPFIND"]
    assert all("pw" not in request.full_url for request in requests)
