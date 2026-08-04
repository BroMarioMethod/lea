"""CLI for recording completed Android two-way calendar acceptance."""

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from lea.calendars import (
    create_android_calendar_acceptance_record,
    write_android_calendar_acceptance_record,
)


def execute_calendar_acceptance_cli(
    arguments: Sequence[str],
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Validate explicit confirmations and persist non-secret evidence."""
    parser = argparse.ArgumentParser(prog="lea accept-calendar-android")
    parser.add_argument(
        "--record-file",
        type=Path,
        default=Path("/var/lib/lea/acceptance/calendar-android.json"),
    )
    parser.add_argument("--server-to-android-verified", action="store_true")
    parser.add_argument("--android-to-server-verified", action="store_true")
    parser.add_argument("--user-isolation-verified", action="store_true")
    parser.add_argument("--backup-verified", action="store_true")
    try:
        namespace = parser.parse_args(list(arguments))
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else 2
    try:
        if not namespace.record_file.is_absolute():
            raise ValueError("--record-file must be absolute.")
        record = create_android_calendar_acceptance_record(
            accepted_at=datetime.now(UTC),
            server_to_android_verified=namespace.server_to_android_verified,
            android_to_server_verified=namespace.android_to_server_verified,
            user_isolation_verified=namespace.user_isolation_verified,
            backup_verified=namespace.backup_verified,
        )
        result = write_android_calendar_acceptance_record(namespace.record_file, record)
    except ValueError as error:
        stderr.write(f"Android calendar acceptance rejected: {error}\n")
        return 2
    if not result.success:
        stderr.write(f"{result.issues[0].code}: {result.issues[0].message}\n")
        return 1
    state = "recorded" if result.changed else "already recorded"
    stdout.write(f"Android calendar acceptance {state}: {result.path}\n")
    return 0
