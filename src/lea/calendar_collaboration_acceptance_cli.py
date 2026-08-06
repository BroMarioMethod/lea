"""CLI for recording Milestone 4.1 collaboration acceptance."""

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from lea.calendars import (
    create_calendar_collaboration_acceptance_record,
    write_calendar_collaboration_acceptance_record,
)


def execute_calendar_collaboration_acceptance_cli(
    arguments: Sequence[str],
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Validate explicit confirmations and persist non-secret evidence."""
    parser = argparse.ArgumentParser(prog="lea accept-calendar-collaboration")
    parser.add_argument(
        "--record-file",
        type=Path,
        default=Path("/var/lib/lea/acceptance/calendar-collaboration.json"),
    )
    for name in (
        "server-to-android-verified",
        "android-to-server-verified",
        "recurrence-verified",
        "attendee-response-verified",
        "reboot-verified",
        "user-isolation-verified",
        "backup-verified",
    ):
        parser.add_argument(f"--{name}", action="store_true")
    try:
        namespace = parser.parse_args(list(arguments))
        if not namespace.record_file.is_absolute():
            raise ValueError("--record-file must be absolute.")
        record = create_calendar_collaboration_acceptance_record(
            accepted_at=datetime.now(UTC),
            server_to_android_verified=namespace.server_to_android_verified,
            android_to_server_verified=namespace.android_to_server_verified,
            recurrence_verified=namespace.recurrence_verified,
            attendee_response_verified=namespace.attendee_response_verified,
            reboot_verified=namespace.reboot_verified,
            user_isolation_verified=namespace.user_isolation_verified,
            backup_verified=namespace.backup_verified,
        )
        if not write_calendar_collaboration_acceptance_record(
            namespace.record_file,
            record,
        ):
            stderr.write("calendar_collaboration_acceptance_write_failed\n")
            return 1
    except (OSError, ValueError) as error:
        stderr.write(f"Calendar collaboration acceptance rejected: {error}\n")
        return 2
    stdout.write(
        f"Calendar collaboration acceptance recorded: {namespace.record_file}\n"
    )
    return 0
