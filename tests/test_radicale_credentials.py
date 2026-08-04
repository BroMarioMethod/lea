"""Tests for atomic Radicale credential provisioning."""

import os
from pathlib import Path

import pytest

from lea.installers.radicale import (
    RadicaleCredential,
    provision_radicale_users_file,
    render_radicale_users_file,
)

HASH_A = "$2b$12$" + "A" * 53
HASH_B = "$2b$12$" + "B" * 53


def test_users_file_is_deterministic_and_contains_only_bcrypt_verifiers() -> None:
    rendered = render_radicale_users_file(
        (RadicaleCredential("zoe", HASH_B), RadicaleCredential("alice", HASH_A))
    )

    assert rendered == f"alice:{HASH_A}\nzoe:{HASH_B}\n".encode()


def test_provision_is_atomic_restrictive_and_idempotent(tmp_path: Path) -> None:
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    path = secrets / "users"
    credentials = (RadicaleCredential("alice", HASH_A),)

    created = provision_radicale_users_file(path, credentials)
    repeated = provision_radicale_users_file(path, credentials)

    assert created.success is True
    assert created.changed is True
    assert repeated.success is True
    assert repeated.changed is False
    assert path.stat().st_mode & 0o777 == 0o600


def test_provision_fails_closed_on_mismatch_without_exposing_hash(
    tmp_path: Path,
) -> None:
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    path = secrets / "users"
    path.write_text(f"alice:{HASH_A}\n", encoding="utf-8")
    os.chmod(path, 0o600)

    result = provision_radicale_users_file(path, (RadicaleCredential("alice", HASH_B),))

    assert result.success is False
    assert result.issues[0].code == "radicale_users_mismatch"
    assert HASH_A not in result.issues[0].message
    assert HASH_B not in result.issues[0].message
    assert path.read_text(encoding="utf-8") == f"alice:{HASH_A}\n"


def test_provision_rejects_symlink(tmp_path: Path) -> None:
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    target = tmp_path / "target"
    target.write_text("unchanged", encoding="utf-8")
    path = secrets / "users"
    path.symlink_to(target)

    result = provision_radicale_users_file(path, (RadicaleCredential("alice", HASH_A),))

    assert result.success is False
    assert result.issues[0].code == "radicale_users_file_invalid"
    assert target.read_text(encoding="utf-8") == "unchanged"


@pytest.mark.parametrize(
    ("username", "bcrypt_hash"),
    [("alice:admin", HASH_A), ("../alice", HASH_A), ("alice", "password")],
)
def test_credentials_reject_ambiguous_users_and_plaintext(
    username: str, bcrypt_hash: str
) -> None:
    with pytest.raises(ValueError):
        RadicaleCredential(username, bcrypt_hash)


def test_provision_rejects_world_readable_secrets_directory(tmp_path: Path) -> None:
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o755)

    result = provision_radicale_users_file(
        secrets / "users", (RadicaleCredential("alice", HASH_A),)
    )

    assert result.success is False
    assert result.issues[0].code == "radicale_secrets_permissions_invalid"
