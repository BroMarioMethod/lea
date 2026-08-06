"""Atomic provisioning for Radicale's bcrypt htpasswd secret store."""

import os
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

_USERNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_BCRYPT = re.compile(r"^\$2[aby]\$([0-3][0-9])\$[./A-Za-z0-9]{53}$")
_MAX_USERS_FILE_BYTES = 1_048_576


@dataclass(frozen=True, slots=True)
class RadicaleCredential:
    """One username and already-derived bcrypt verifier."""

    username: str
    bcrypt_hash: str

    def __post_init__(self) -> None:
        """Reject ambiguous usernames and non-bcrypt secret material."""
        if (
            not isinstance(self.username, str)
            or _USERNAME.fullmatch(self.username) is None
        ):
            raise ValueError("username must use 1-64 safe account characters.")
        match = _BCRYPT.fullmatch(self.bcrypt_hash)
        if match is None:
            raise ValueError("bcrypt_hash must be one canonical bcrypt verifier.")
        cost = int(match.group(1))
        if not 12 <= cost <= 31:
            raise ValueError("bcrypt_hash cost must be at least 12.")


@dataclass(frozen=True, slots=True)
class RadicaleCredentialIssue:
    """One non-secret credential provisioning problem."""

    code: str
    message: str
    path: Path


@dataclass(frozen=True, slots=True)
class RadicaleCredentialProvisionResult:
    """Result of exact htpasswd secret-store provisioning."""

    success: bool
    path: Path
    user_count: int
    changed: bool
    issues: tuple[RadicaleCredentialIssue, ...]


def render_radicale_users_file(
    credentials: tuple[RadicaleCredential, ...],
) -> bytes:
    """Render deterministic htpasswd bytes without exposing them in diagnostics."""
    if not credentials:
        raise ValueError("At least one Radicale credential is required.")
    usernames = [credential.username for credential in credentials]
    if len(set(usernames)) != len(usernames):
        raise ValueError("Radicale usernames must be unique.")
    ordered = sorted(credentials, key=lambda credential: credential.username)
    return "".join(
        f"{credential.username}:{credential.bcrypt_hash}\n" for credential in ordered
    ).encode("utf-8")


def provision_radicale_users_file(
    path: Path,
    credentials: tuple[RadicaleCredential, ...],
) -> RadicaleCredentialProvisionResult:
    """Create an exact mode-0600 users file without replacing mismatched state."""
    if not path.is_absolute():
        raise ValueError("path must be absolute.")
    contents = render_radicale_users_file(credentials)
    if len(contents) > _MAX_USERS_FILE_BYTES:
        raise ValueError("Radicale users file exceeds the supported size limit.")
    parent_issue = _validate_parent(path)
    if parent_issue is not None:
        return _failure(path, len(credentials), parent_issue)
    if path.exists() or path.is_symlink():
        return _inspect_existing(path, contents, len(credentials))

    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary_path, path)
        _fsync_directory(path.parent)
    except FileExistsError:
        return _inspect_existing(path, contents, len(credentials))
    except OSError:
        return _failure(
            path,
            len(credentials),
            RadicaleCredentialIssue(
                "radicale_users_write_failed",
                "The Radicale users file could not be created.",
                path,
            ),
        )
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
    return RadicaleCredentialProvisionResult(True, path, len(credentials), True, ())


def _validate_parent(path: Path) -> RadicaleCredentialIssue | None:
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir():
        return RadicaleCredentialIssue(
            "radicale_secrets_directory_invalid",
            (
                "The Radicale secrets directory must be an existing "
                "non-symbolic directory."
            ),
            parent,
        )
    try:
        mode = parent.stat().st_mode
    except OSError:
        mode = 0o777
    if mode & 0o077:
        return RadicaleCredentialIssue(
            "radicale_secrets_permissions_invalid",
            "The Radicale secrets directory permissions are too broad.",
            parent,
        )
    return None


def _inspect_existing(
    path: Path, expected: bytes, user_count: int
) -> RadicaleCredentialProvisionResult:
    if path.is_symlink() or not path.is_file():
        return _failure(
            path,
            user_count,
            RadicaleCredentialIssue(
                "radicale_users_file_invalid",
                "The Radicale users path must be a regular non-symbolic file.",
                path,
            ),
        )
    try:
        stat = path.stat()
        actual = path.read_bytes()
    except OSError:
        return _failure(
            path,
            user_count,
            RadicaleCredentialIssue(
                "radicale_users_read_failed",
                "The existing Radicale users file could not be inspected.",
                path,
            ),
        )
    if stat.st_size > _MAX_USERS_FILE_BYTES or actual != expected:
        return _failure(
            path,
            user_count,
            RadicaleCredentialIssue(
                "radicale_users_mismatch",
                "The existing Radicale users file does not match requested accounts.",
                path,
            ),
        )
    if stat.st_mode & 0o077:
        return _failure(
            path,
            user_count,
            RadicaleCredentialIssue(
                "radicale_users_permissions_invalid",
                "The existing Radicale users file permissions are too broad.",
                path,
            ),
        )
    return RadicaleCredentialProvisionResult(True, path, user_count, False, ())


def _failure(
    path: Path, user_count: int, issue: RadicaleCredentialIssue
) -> RadicaleCredentialProvisionResult:
    return RadicaleCredentialProvisionResult(False, path, user_count, False, (issue,))


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
