"""Reading and verification of Taskwarrior installation records."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lea.installers.taskwarrior.contracts import (
    TaskwarriorInstallerIssue,
    TaskwarriorInstallFailureCode,
)


@dataclass(frozen=True, slots=True)
class TaskwarriorInstallationRecord:
    """Immutable record of one activated Taskwarrior installation."""

    schema_version: int
    component: str
    version: str
    mode: str
    platform: str
    executable: Path
    sha256: str
    taskrc: Path
    home: Path
    data: Path
    smoke_test: str
    installed_at: datetime

    def __post_init__(self) -> None:
        """Validate installation-record fields."""
        if self.schema_version != 1:
            raise ValueError("schema_version must be 1.")

        if self.component != "taskwarrior":
            raise ValueError("component must be taskwarrior.")

        for field_name, value in (
            ("version", self.version),
            ("mode", self.mode),
            ("platform", self.platform),
            ("smoke_test", self.smoke_test),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty.")

        for field_name, path in (
            ("executable", self.executable),
            ("taskrc", self.taskrc),
            ("home", self.home),
            ("data", self.data),
        ):
            if not path.is_absolute():
                raise ValueError(f"{field_name} must be absolute.")

        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise ValueError("sha256 must be lower-case hexadecimal SHA-256 text.")

        if self.smoke_test != "passed":
            raise ValueError("smoke_test must be passed.")

        if self.installed_at.tzinfo is None or self.installed_at.utcoffset() is None:
            raise ValueError("installed_at must be timezone-aware.")

        if self.installed_at.utcoffset() != UTC.utcoffset(self.installed_at):
            raise ValueError("installed_at must be canonical UTC.")


def read_taskwarrior_installation_record(
    path: Path,
) -> tuple[
    TaskwarriorInstallationRecord | None,
    tuple[TaskwarriorInstallerIssue, ...],
]:
    """Read and strictly validate one installation record."""
    if not isinstance(path, Path):
        raise TypeError("path must be a pathlib.Path value.")

    if not path.is_absolute():
        raise ValueError("path must be absolute.")

    if not path.exists():
        return (
            None,
            (
                TaskwarriorInstallerIssue(
                    code=TaskwarriorInstallFailureCode.RECORD_FAILED,
                    message=("The Taskwarrior installation record does not exist."),
                    field="installation_record",
                    path=path,
                ),
            ),
        )

    if not path.is_file():
        return (
            None,
            (
                TaskwarriorInstallerIssue(
                    code=TaskwarriorInstallFailureCode.RECORD_FAILED,
                    message=(
                        "The Taskwarrior installation record is not a regular file."
                    ),
                    field="installation_record",
                    path=path,
                ),
            ),
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _record_failure(
            path,
            "The Taskwarrior installation record could not be decoded.",
        )

    if not isinstance(payload, dict):
        return _record_failure(
            path,
            "The Taskwarrior installation record must contain one JSON object.",
        )

    try:
        record = _parse_record(payload)
    except (KeyError, TypeError, ValueError):
        return _record_failure(
            path,
            "The Taskwarrior installation record failed strict validation.",
        )

    return record, ()


def installation_record_matches(
    record: TaskwarriorInstallationRecord,
    *,
    version: str,
    platform: str,
    executable: Path,
    sha256: str,
) -> bool:
    """Return whether one record identifies the expected installation."""
    return (
        record.version == version
        and record.platform == platform
        and record.executable == executable
        and record.sha256 == sha256
        and record.smoke_test == "passed"
    )


def _parse_record(
    payload: dict[str, Any],
) -> TaskwarriorInstallationRecord:
    """Parse one strictly shaped installation-record payload."""
    expected_keys = {
        "schema_version",
        "component",
        "version",
        "mode",
        "platform",
        "executable",
        "sha256",
        "taskrc",
        "home",
        "data",
        "smoke_test",
        "installed_at",
    }

    if set(payload) != expected_keys:
        raise ValueError("Installation-record keys did not match.")

    installed_at_raw = _require_string(
        payload["installed_at"],
        field_name="installed_at",
    )

    if not installed_at_raw.endswith("Z"):
        raise ValueError("installed_at must use canonical UTC Z form.")

    installed_at = datetime.fromisoformat(
        installed_at_raw.removesuffix("Z") + "+00:00"
    ).astimezone(UTC)

    schema_version = payload["schema_version"]

    if not isinstance(schema_version, int) or isinstance(
        schema_version,
        bool,
    ):
        raise TypeError("schema_version must be an integer.")

    return TaskwarriorInstallationRecord(
        schema_version=schema_version,
        component=_require_string(
            payload["component"],
            field_name="component",
        ),
        version=_require_string(
            payload["version"],
            field_name="version",
        ),
        mode=_require_string(
            payload["mode"],
            field_name="mode",
        ),
        platform=_require_string(
            payload["platform"],
            field_name="platform",
        ),
        executable=Path(
            _require_string(
                payload["executable"],
                field_name="executable",
            )
        ),
        sha256=_require_string(
            payload["sha256"],
            field_name="sha256",
        ),
        taskrc=Path(
            _require_string(
                payload["taskrc"],
                field_name="taskrc",
            )
        ),
        home=Path(
            _require_string(
                payload["home"],
                field_name="home",
            )
        ),
        data=Path(
            _require_string(
                payload["data"],
                field_name="data",
            )
        ),
        smoke_test=_require_string(
            payload["smoke_test"],
            field_name="smoke_test",
        ),
        installed_at=installed_at,
    )


def _require_string(
    value: object,
    *,
    field_name: str,
) -> str:
    """Require one non-empty JSON string."""
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be a non-empty string.")

    return value


def _record_failure(
    path: Path,
    message: str,
) -> tuple[
    None,
    tuple[TaskwarriorInstallerIssue, ...],
]:
    """Create one structured installation-record read failure."""
    return (
        None,
        (
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.RECORD_FAILED,
                message=message,
                field="installation_record",
                path=path,
            ),
        ),
    )
