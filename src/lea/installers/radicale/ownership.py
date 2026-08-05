"""Ownership helpers for privileged Radicale provisioning."""

import grp
import os
import pwd
from pathlib import Path


def apply_radicale_ownership(path: Path, owner: str, group: str) -> bool:
    """Apply exact non-symlink ownership and report whether it changed."""
    if path.is_symlink():
        raise OSError("Radicale ownership targets must not be symbolic links.")
    user = pwd.getpwnam(owner)
    group_record = grp.getgrnam(group)
    current = path.stat()
    if current.st_uid == user.pw_uid and current.st_gid == group_record.gr_gid:
        return False
    os.chown(path, user.pw_uid, group_record.gr_gid, follow_symlinks=False)
    return True
