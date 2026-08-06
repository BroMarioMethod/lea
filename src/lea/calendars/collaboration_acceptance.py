"""Credential-free evidence for Milestone 4.1 collaboration acceptance."""

import json
import os
import tempfile
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CalendarCollaborationAcceptanceRecord:
    """Non-secret evidence that every live collaboration check passed."""

    schema_version: int
    component: str
    server_to_android_verified: bool
    android_to_server_verified: bool
    recurrence_verified: bool
    attendee_response_verified: bool
    reboot_verified: bool
    user_isolation_verified: bool
    backup_verified: bool
    accepted_at: str

    def __post_init__(self) -> None:
        if (
            self.schema_version != 1
            or self.component != "calendar-collaboration-acceptance"
        ):
            raise ValueError("Unsupported calendar collaboration acceptance identity.")
        if not all(
            (
                self.server_to_android_verified,
                self.android_to_server_verified,
                self.recurrence_verified,
                self.attendee_response_verified,
                self.reboot_verified,
                self.user_isolation_verified,
                self.backup_verified,
            )
        ):
            raise ValueError("Every calendar collaboration acceptance check must pass.")
        parsed = datetime.fromisoformat(self.accepted_at)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("accepted_at must be timezone-aware.")


def create_calendar_collaboration_acceptance_record(
    *,
    accepted_at: datetime,
    server_to_android_verified: bool,
    android_to_server_verified: bool,
    recurrence_verified: bool,
    attendee_response_verified: bool,
    reboot_verified: bool,
    user_isolation_verified: bool,
    backup_verified: bool,
) -> CalendarCollaborationAcceptanceRecord:
    """Create evidence only when all independently observed checks pass."""
    if accepted_at.tzinfo is None or accepted_at.utcoffset() is None:
        raise ValueError("accepted_at must be timezone-aware.")
    return CalendarCollaborationAcceptanceRecord(
        1,
        "calendar-collaboration-acceptance",
        server_to_android_verified,
        android_to_server_verified,
        recurrence_verified,
        attendee_response_verified,
        reboot_verified,
        user_isolation_verified,
        backup_verified,
        accepted_at.astimezone(UTC).isoformat(),
    )


def write_calendar_collaboration_acceptance_record(
    path: Path,
    record: CalendarCollaborationAcceptanceRecord,
) -> bool:
    """Atomically create restrictive evidence without replacing existing data."""
    if not path.is_absolute():
        raise ValueError("path must be absolute.")
    document = (
        json.dumps(asdict(record), sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    if path.parent.is_symlink() or not path.parent.is_dir():
        return False
    if path.exists() or path.is_symlink():
        return (
            path.is_file()
            and not path.is_symlink()
            and path.read_bytes() == document
            and path.stat().st_mode & 0o777 == 0o640
        )
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(name)
        os.fchmod(descriptor, 0o640)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(document)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        return True
    except OSError:
        return False
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
