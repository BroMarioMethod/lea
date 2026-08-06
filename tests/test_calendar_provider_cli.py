"""Tests for protected calendar-provider administrative inputs."""

import os
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from lea import calendar_provider_cli
from lea.installers.radicale import RadicaleRemovalResult


def test_credentials_file_loads_canonical_accounts_without_exposing_hashes() -> None:
    credentials = calendar_provider_cli._parse_credentials_document(
        "alpha:$2b$12$.....................................................\n"
        "beta:$2b$12$/////////////////////////////////////////////////////\n"
    )
    assert tuple(value.username for value in credentials) == ("alpha", "beta")


def test_credentials_file_rejects_noncanonical_document() -> None:
    with pytest.raises(ValueError, match="canonical htpasswd"):
        calendar_provider_cli._parse_credentials_document("missing-separator\n")


def test_acceptance_account_reads_password_from_protected_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        calendar_provider_cli, "_protected_line", lambda _path: "password"
    )
    account = calendar_provider_cli._acceptance_account(
        "account=/root/account.password"
    )
    assert account.username == "account"


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

    responses = iter((Response(207),))

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
    assert [request.method for request in requests] == ["PROPFIND"]
    assert all("pw" not in request.full_url for request in requests)


def test_bootstrap_runtime_paths_are_canonical() -> None:
    layout = calendar_provider_cli._calendar_layout()
    assert layout.vdirs / "lea-calendar" == Path(
        "/var/lib/lea/calendar/vdirs/lea-calendar"
    )
    assert layout.vdirsyncer_status / "lea_calendars.collections" == Path(
        "/var/lib/lea/calendar/vdirsyncer-status/lea_calendars.collections"
    )


def test_setgid_mode_is_not_reduced_to_basic_permission_bits() -> None:
    assert 0o42750 & 0o7777 == 0o2750


def test_public_remove_command_uses_exact_confirmed_purge_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[Any] = []
    monkeypatch.setattr(os, "geteuid", lambda: 0)

    def remove(request: Any) -> RadicaleRemovalResult:
        observed.append(request)
        return RadicaleRemovalResult(True, True, True, (), ())

    monkeypatch.setattr(calendar_provider_cli, "remove_radicale", remove)
    result = calendar_provider_cli.execute_calendar_provider_cli(
        ("remove", "--purge", "--yes")
    )

    assert result == 0
    assert len(observed) == 1
    assert observed[0].purge is True
    assert observed[0].confirmed is True
    assert observed[0].installation_record == Path("/var/lib/lea/install/radicale.json")
    assert observed[0].distribution_root == Path("/opt/lea-tools/radicale/3.5.4")


def test_public_remove_command_requires_explicit_confirmation() -> None:
    with pytest.raises(SystemExit):
        calendar_provider_cli.create_parser().parse_args(("remove", "--purge"))


def test_bootstrap_creates_collection_only_after_not_found(
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

    outcomes: Any = iter((404, Response(201), Response(207)))

    def urlopen(request: Any, **_kwargs: Any) -> Response:
        requests.append(request)
        outcome = next(outcomes)
        if outcome == 404:
            raise urllib.error.HTTPError(
                request.full_url, 404, "not found", Message(), None
            )
        assert isinstance(outcome, Response)
        return outcome

    monkeypatch.setattr(calendar_provider_cli, "_protected_line", lambda _path: "pw")
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    calendar_provider_cli._bootstrap_remote_collection(
        "http://192.168.1.2:5232/", "account", Path("/root/password"), "calendar"
    )
    assert [request.method for request in requests] == [
        "PROPFIND",
        "MKCALENDAR",
        "PROPFIND",
    ]
