"""Ownership helpers for calendar installer filesystem mutations."""

import grp
import os
import pwd
from collections.abc import Callable
from pathlib import Path

type CalendarOwnershipApplier = Callable[
    [Path, str, str],
    bool,
]


def apply_calendar_ownership(
    path: Path,
    owner: str,
    group: str,
) -> bool:
    """Apply exact ownership and report whether a mutation occurred."""
    user_record = pwd.getpwnam(owner)
    group_record = grp.getgrnam(group)
    current = path.stat()

    if current.st_uid == user_record.pw_uid and current.st_gid == group_record.gr_gid:
        return False

    os.chown(
        path,
        user_record.pw_uid,
        group_record.gr_gid,
    )
    return True


def ignore_calendar_ownership(
    _path: Path,
    _owner: str,
    _group: str,
) -> bool:
    """Skip ownership mutation for isolated non-privileged tests."""
    return False
