"""Credential-free records for human-observed Android two-way acceptance."""

import json
import os
import tempfile
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AndroidCalendarAcceptanceRecord:
    """Non-secret evidence that all required live acceptance checks passed."""

    schema_version: int
    component: str
    server_to_android_verified: bool
    android_to_server_verified: bool
    user_isolation_verified: bool
    backup_verified: bool
    accepted_at: str

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.component != "calendar-android-acceptance":
            raise ValueError("Unsupported Android calendar acceptance record identity.")
        if not all(
            (
                self.server_to_android_verified,
                self.android_to_server_verified,
                self.user_isolation_verified,
                self.backup_verified,
            )
        ):
            raise ValueError("Every Android calendar acceptance check must pass.")
        parsed = datetime.fromisoformat(self.accepted_at)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("accepted_at must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class AndroidCalendarAcceptanceIssue:
    """One record persistence or verification problem."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class AndroidCalendarAcceptanceResult:
    """Result of persisting exact live acceptance evidence."""

    success: bool
    changed: bool
    path: Path
    record: AndroidCalendarAcceptanceRecord | None
    issues: tuple[AndroidCalendarAcceptanceIssue, ...]


def create_android_calendar_acceptance_record(
    *,
    accepted_at: datetime,
    server_to_android_verified: bool,
    android_to_server_verified: bool,
    user_isolation_verified: bool,
    backup_verified: bool,
) -> AndroidCalendarAcceptanceRecord:
    """Create evidence only when every independently observed check passed."""
    if accepted_at.tzinfo is None or accepted_at.utcoffset() is None:
        raise ValueError("accepted_at must be timezone-aware.")
    return AndroidCalendarAcceptanceRecord(
        1,
        "calendar-android-acceptance",
        server_to_android_verified,
        android_to_server_verified,
        user_isolation_verified,
        backup_verified,
        accepted_at.astimezone(UTC).isoformat(),
    )


def write_android_calendar_acceptance_record(
    path: Path,
    record: AndroidCalendarAcceptanceRecord,
) -> AndroidCalendarAcceptanceResult:
    """Atomically create a non-secret acceptance record without replacement."""
    if not path.is_absolute():
        raise ValueError("path must be absolute.")
    document = (
        json.dumps(asdict(record), sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    if path.parent.is_symlink() or not path.parent.is_dir():
        return _failure(
            path,
            "android_acceptance_parent_invalid",
            "The Android acceptance record directory is unavailable.",
        )
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            return _failure(
                path,
                "android_acceptance_record_invalid",
                "The Android acceptance record path is invalid.",
            )
        try:
            if path.read_bytes() == document and path.stat().st_mode & 0o777 == 0o640:
                return AndroidCalendarAcceptanceResult(True, False, path, record, ())
        except OSError:
            pass
        return _failure(
            path,
            "android_acceptance_record_mismatch",
            "Existing Android acceptance evidence does not match.",
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
    except OSError:
        return _failure(
            path,
            "android_acceptance_record_write_failed",
            "The Android acceptance record could not be created.",
        )
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
    return AndroidCalendarAcceptanceResult(True, True, path, record, ())


def _failure(path: Path, code: str, message: str) -> AndroidCalendarAcceptanceResult:
    return AndroidCalendarAcceptanceResult(
        False,
        False,
        path,
        None,
        (AndroidCalendarAcceptanceIssue(code, message),),
    )
