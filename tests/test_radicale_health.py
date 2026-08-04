"""Tests for Radicale DAV health and reciprocal user isolation."""

import base64
from collections.abc import Mapping

from lea.installers.radicale import (
    RadicaleAcceptanceAccount,
    RadicaleProbeResponse,
    inspect_radicale_health,
    verify_radicale_user_isolation,
)


def test_health_requires_authentication_without_sending_credentials() -> None:
    recorded: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def transport(
        method: str, url: str, headers: Mapping[str, str], body: bytes | None
    ) -> RadicaleProbeResponse:
        mapped = dict(headers)
        recorded.append((method, url, mapped, body))
        return RadicaleProbeResponse(401)

    result = inspect_radicale_health("http://192.168.1.20:5232", transport=transport)

    assert result.healthy is True
    assert result.authentication_required is True
    assert recorded[0][0:2] == ("PROPFIND", "http://192.168.1.20:5232/")
    assert "Authorization" not in recorded[0][2]


def test_health_rejects_anonymous_dav_access() -> None:
    result = inspect_radicale_health(
        "http://127.0.0.1:5232",
        transport=lambda *_arguments: RadicaleProbeResponse(207),
    )

    assert result.healthy is False
    assert result.issues[0].code == "radicale_authentication_not_required"


def test_two_accounts_have_own_access_and_reciprocal_cross_denial() -> None:
    passwords = {"alice": "alice-secret", "bob": "bob-secret"}

    def transport(
        method: str,
        url: str,
        headers: Mapping[str, str],
        _body: bytes | None,
    ) -> RadicaleProbeResponse:
        assert method == "PROPFIND"
        authorization = dict(headers)["Authorization"]
        encoded = authorization.removeprefix("Basic ")
        username, password = base64.b64decode(encoded).decode().split(":", 1)
        assert password == passwords[username]
        principal = url.rstrip("/").rsplit("/", 1)[-1]
        return RadicaleProbeResponse(207 if principal == username else 404)

    result = verify_radicale_user_isolation(
        "http://127.0.0.1:5232",
        RadicaleAcceptanceAccount("alice", passwords["alice"]),
        RadicaleAcceptanceAccount("bob", passwords["bob"]),
        transport=transport,
    )

    assert result.success is True
    assert result.own_access_verified is True
    assert result.cross_access_denied is True
    assert result.checks_completed == 4
    assert "alice-secret" not in repr(result)
    assert "bob-secret" not in repr(result)


def test_isolation_fails_when_cross_owner_access_is_permitted() -> None:
    result = verify_radicale_user_isolation(
        "http://127.0.0.1:5232",
        RadicaleAcceptanceAccount("alice", "first-secret"),
        RadicaleAcceptanceAccount("bob", "second-secret"),
        transport=lambda *_arguments: RadicaleProbeResponse(207),
    )

    assert result.success is False
    assert result.own_access_verified is True
    assert result.cross_access_denied is False
    assert result.issues[0].code == "radicale_user_isolation_failed"
    assert "secret" not in result.issues[0].message.lower()
