"""Bounded HTTP health and authenticated owner-isolation acceptance for Radicale."""

import base64
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import quote

_USERNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_PROPFIND_BODY = (
    b'<?xml version="1.0"?><propfind xmlns="DAV:">'
    b"<prop><resourcetype/></prop></propfind>"
)


@dataclass(frozen=True, slots=True)
class RadicaleAcceptanceAccount:
    """One runtime-only account used for live isolation acceptance."""

    username: str
    password: str = field(repr=False)

    def __post_init__(self) -> None:
        if _USERNAME.fullmatch(self.username) is None:
            raise ValueError("username must use safe account characters.")
        if not self.password:
            raise ValueError("password must not be empty.")


@dataclass(frozen=True, slots=True)
class RadicaleProbeResponse:
    """Non-secret projection of one bounded HTTP response."""

    status: int


RadicaleTransport = Callable[
    [str, str, Mapping[str, str], bytes | None], RadicaleProbeResponse
]


@dataclass(frozen=True, slots=True)
class RadicaleHealthIssue:
    """One redaction-safe Radicale health or isolation problem."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class RadicaleHealthResult:
    """Credential-free DAV endpoint health result."""

    healthy: bool
    authentication_required: bool
    issues: tuple[RadicaleHealthIssue, ...]


@dataclass(frozen=True, slots=True)
class RadicaleIsolationResult:
    """Result proving two authenticated owners cannot cross principals."""

    success: bool
    own_access_verified: bool
    cross_access_denied: bool
    checks_completed: int
    issues: tuple[RadicaleHealthIssue, ...]


def inspect_radicale_health(
    base_url: str,
    *,
    transport: RadicaleTransport | None = None,
) -> RadicaleHealthResult:
    """Verify that the DAV endpoint is reachable and requires authentication."""
    url = _base_url(base_url)
    try:
        response = (transport or _transport)(
            "PROPFIND", url, {"Depth": "0"}, _PROPFIND_BODY
        )
    except (OSError, TimeoutError, urllib.error.URLError):
        return _health_failure(
            "radicale_health_unavailable", "The Radicale DAV endpoint is unavailable."
        )
    if response.status not in {401, 403}:
        return _health_failure(
            "radicale_authentication_not_required",
            "The Radicale DAV endpoint did not require authentication.",
        )
    return RadicaleHealthResult(True, True, ())


def verify_radicale_user_isolation(
    base_url: str,
    first: RadicaleAcceptanceAccount,
    second: RadicaleAcceptanceAccount,
    *,
    transport: RadicaleTransport | None = None,
) -> RadicaleIsolationResult:
    """Prove own-principal access and reciprocal cross-principal denial."""
    url = _base_url(base_url)
    if first.username == second.username:
        raise ValueError("Isolation acceptance requires two distinct usernames.")
    execute = transport or _transport
    checks = (
        (first, first.username, True),
        (second, second.username, True),
        (first, second.username, False),
        (second, first.username, False),
    )
    completed = 0
    own_verified = True
    cross_denied = True
    for account, principal, expect_access in checks:
        headers = {
            "Authorization": _basic_authorization(account),
            "Depth": "0",
        }
        try:
            response = execute(
                "PROPFIND",
                f"{url}{quote(principal, safe='')}/",
                headers,
                _PROPFIND_BODY,
            )
        except (OSError, TimeoutError, urllib.error.URLError):
            return RadicaleIsolationResult(
                False,
                False,
                False,
                completed,
                (
                    RadicaleHealthIssue(
                        "radicale_isolation_unavailable",
                        "Radicale user-isolation acceptance could not complete.",
                    ),
                ),
            )
        completed += 1
        if expect_access:
            own_verified = own_verified and response.status in {200, 207}
        else:
            cross_denied = cross_denied and response.status in {403, 404}
    if not own_verified or not cross_denied:
        return RadicaleIsolationResult(
            False,
            own_verified,
            cross_denied,
            completed,
            (
                RadicaleHealthIssue(
                    "radicale_user_isolation_failed",
                    "Radicale did not enforce reciprocal owner isolation.",
                ),
            ),
        )
    return RadicaleIsolationResult(True, True, True, completed, ())


def _base_url(value: str) -> str:
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        raise ValueError("base_url must be an explicit HTTP or HTTPS URL.")
    if any(character.isspace() for character in value):
        raise ValueError("base_url must not contain whitespace.")
    return value.rstrip("/") + "/"


def _basic_authorization(account: RadicaleAcceptanceAccount) -> str:
    token = base64.b64encode(f"{account.username}:{account.password}".encode()).decode(
        "ascii"
    )
    return f"Basic {token}"


def _transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes | None,
) -> RadicaleProbeResponse:
    request = urllib.request.Request(
        url,
        data=body,
        headers=dict(headers),
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read(65_537)
            return RadicaleProbeResponse(response.status)
    except urllib.error.HTTPError as error:
        error.read(65_537)
        return RadicaleProbeResponse(error.code)


def _health_failure(code: str, message: str) -> RadicaleHealthResult:
    return RadicaleHealthResult(False, False, (RadicaleHealthIssue(code, message),))
