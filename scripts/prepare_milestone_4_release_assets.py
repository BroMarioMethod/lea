#!/usr/bin/env python3
"""Materialize independently reviewed Milestone 4 release assets."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

TASK_DIGEST = "d302761fcd1268e4a5a545613a2b68c61abd50c0bcaade3b3e68d728dd02e716"
CALENDAR_DIGEST = "f5f7a0749b993e49bbd50b8807242611fff1dbc2477a59a4a292c0aa42420ba5"
RADICALE_DIGEST = "bc339317cbda1deec4cd7cff15bed10539297341471e67fbb05c3b906db70669"


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _verified_source(path: Path, expected: str) -> None:
    if not path.is_absolute():
        raise ValueError(f"Asset source must be absolute: {path}")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Asset source must be a regular non-symbolic file: {path}")
    if _digest(path) != expected:
        raise ValueError(f"Asset digest mismatch: {path.name}")


def _install(source: Path, destination: Path, expected: str) -> None:
    _verified_source(source, expected)
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise ValueError(f"Asset destination is unsafe: {destination}")
    if destination.exists():
        stat = destination.stat()
        if (
            _digest(destination) != expected
            or stat.st_mode & 0o777 != 0o644
            or (os.geteuid() == 0 and (stat.st_uid != 0 or stat.st_gid != 0))
        ):
            raise ValueError(f"Existing release asset differs: {destination.name}")
        return
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "wb") as target, source.open("rb") as origin:
            shutil.copyfileobj(origin, target)
            target.flush()
            os.fsync(target.fileno())
        if _digest(temporary) != expected:
            raise ValueError(f"Copied release asset differs: {destination.name}")
        os.link(temporary, destination)
        os.chown(destination, 0, 0, follow_symlinks=False)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--taskwarrior-archive", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument(
        "--destination", type=Path, default=Path("/opt/lea-release-assets")
    )
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("release assets must be prepared as root")
    repository = args.repository.resolve()
    destination = args.destination
    if not destination.is_absolute() or destination.is_symlink():
        parser.error("--destination must be an absolute non-symbolic path")
    destination.mkdir(mode=0o755, parents=False, exist_ok=True)
    assets = (
        (args.taskwarrior_archive, destination / "task-3.4.2.tar.gz", TASK_DIGEST),
        (
            repository / "third_party/calendar/requirements-linux-aarch64-py313.txt",
            destination / "calendar-requirements.lock",
            CALENDAR_DIGEST,
        ),
        (
            repository / "third_party/radicale/requirements-linux-aarch64-py313.txt",
            destination / "radicale-requirements.lock",
            RADICALE_DIGEST,
        ),
    )
    for source, target, digest in assets:
        _install(source, target, digest)
    print("Milestone 4 release assets: READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
