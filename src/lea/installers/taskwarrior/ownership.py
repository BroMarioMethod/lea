"""POSIX ownership boundaries for managed Taskwarrior paths."""

import grp
import os
import pwd
from collections.abc import Callable
from pathlib import Path

OwnershipApplier = Callable[[Path, str, str], None]


def apply_posix_ownership(
    path: Path,
    owner: str,
    group: str,
) -> None:
    """Apply explicit POSIX ownership using local account databases."""
    user_record = pwd.getpwnam(owner)
    group_record = grp.getgrnam(group)
    os.chown(path, user_record.pw_uid, group_record.gr_gid)


def ignore_ownership(
    _path: Path,
    _owner: str,
    _group: str,
) -> None:
    """Provide an unprivileged ownership boundary for focused unit tests."""
