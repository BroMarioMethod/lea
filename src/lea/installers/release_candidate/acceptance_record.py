"""Persistent release-candidate acceptance records."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from lea.installers.release_candidate.contracts import (
    InstallerIssue,
    InstallerIssueCode,
    InstallerStepId,
)
from lea.installers.release_candidate.post_install import (
    PostInstallCheck,
    PostInstallHealthPlan,
    PostInstallHealthResult,
    ReleaseCandidateAcceptanceResult,
)

Clock = Callable[[], datetime]

_ACCEPTANCE_COMPONENT = "lea-release-candidate-acceptance"


@dataclass(frozen=True, slots=True)
class ReleaseCandidateAcceptanceRecord:
    """Machine-readable record of one release-candidate acceptance run."""

    schema_version: int
    component: str
    accepted: bool
    recorded_at_utc: str
    runtime_config_file: Path
    taskwarrior_record_file: Path
    telegram_enabled: bool
    health_healthy: bool
    health_checks: tuple[PostInstallCheck, ...]
    acceptance_accepted: bool
    acceptance_checks: tuple[PostInstallCheck, ...]

    def __post_init__(self) -> None:
        """Validate the acceptance-record contract."""
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != 1
        ):
            raise ValueError("Unsupported acceptance record schema version.")

        if self.component != _ACCEPTANCE_COMPONENT:
            raise ValueError("Unsupported acceptance record component.")

        for field_name, value in (
            ("accepted", self.accepted),
            ("telegram_enabled", self.telegram_enabled),
            ("health_healthy", self.health_healthy),
            ("acceptance_accepted", self.acceptance_accepted),
        ):
            if not isinstance(value, bool):
                raise TypeError(f"{field_name} must be a boolean.")

        if not isinstance(self.recorded_at_utc, str):
            raise TypeError("recorded_at_utc must be a string.")

        try:
            timestamp = datetime.fromisoformat(self.recorded_at_utc)
        except ValueError as error:
            raise ValueError(
                "recorded_at_utc must be a valid ISO-8601 timestamp."
            ) from error

        if timestamp.tzinfo is None or timestamp.utcoffset() != UTC.utcoffset(
            timestamp
        ):
            raise ValueError("recorded_at_utc must use UTC.")

        _validate_absolute_path(
            self.runtime_config_file,
            field_name="runtime_config_file",
        )
        _validate_absolute_path(
            self.taskwarrior_record_file,
            field_name="taskwarrior_record_file",
        )

        for field_name, checks in (
            ("health_checks", self.health_checks),
            ("acceptance_checks", self.acceptance_checks),
        ):
            if not isinstance(checks, tuple):
                raise TypeError(f"{field_name} must be a tuple.")
            if not all(isinstance(check, PostInstallCheck) for check in checks):
                raise TypeError(
                    f"{field_name} must contain only PostInstallCheck values."
                )


@dataclass(frozen=True, slots=True)
class AcceptanceRecordWriteResult:
    """Result of persisting one acceptance record."""

    success: bool
    changed: bool
    path: Path
    issues: tuple[InstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate write-result consistency."""
        _validate_absolute_path(self.path, field_name="path")

        if self.success:
            if self.issues:
                raise ValueError(
                    "A successful acceptance-record write must not contain issues."
                )
            return

        if self.changed:
            raise ValueError(
                "A failed acceptance-record write must not report a change."
            )

        if not self.issues:
            raise ValueError("A failed acceptance-record write must contain an issue.")


def create_release_candidate_acceptance_record(
    plan: PostInstallHealthPlan,
    health: PostInstallHealthResult,
    acceptance: ReleaseCandidateAcceptanceResult,
    *,
    clock: Clock = lambda: datetime.now(UTC),
) -> ReleaseCandidateAcceptanceRecord:
    """Create one deterministic acceptance record."""
    if not isinstance(plan, PostInstallHealthPlan):
        raise TypeError("plan must be a PostInstallHealthPlan value.")
    if not isinstance(health, PostInstallHealthResult):
        raise TypeError("health must be a PostInstallHealthResult value.")
    if not isinstance(acceptance, ReleaseCandidateAcceptanceResult):
        raise TypeError("acceptance must be a ReleaseCandidateAcceptanceResult value.")

    timestamp = clock()

    if not isinstance(timestamp, datetime):
        raise TypeError("clock must return a datetime value.")
    if timestamp.tzinfo is None:
        raise ValueError("clock must return a timezone-aware datetime.")

    return ReleaseCandidateAcceptanceRecord(
        schema_version=1,
        component=_ACCEPTANCE_COMPONENT,
        accepted=health.healthy and acceptance.accepted,
        recorded_at_utc=timestamp.astimezone(UTC).isoformat(),
        runtime_config_file=plan.runtime_config_file,
        taskwarrior_record_file=plan.taskwarrior_record_file,
        telegram_enabled=plan.telegram_enabled,
        health_healthy=health.healthy,
        health_checks=health.checks,
        acceptance_accepted=acceptance.accepted,
        acceptance_checks=acceptance.checks,
    )


def render_release_candidate_acceptance_record(
    record: ReleaseCandidateAcceptanceRecord,
) -> str:
    """Render one acceptance record as deterministic JSON."""
    if not isinstance(record, ReleaseCandidateAcceptanceRecord):
        raise TypeError("record must be a ReleaseCandidateAcceptanceRecord value.")

    payload = {
        "acceptance": {
            "accepted": record.acceptance_accepted,
            "checks": [_render_check(check) for check in record.acceptance_checks],
        },
        "accepted": record.accepted,
        "component": record.component,
        "health": {
            "checks": [_render_check(check) for check in record.health_checks],
            "healthy": record.health_healthy,
        },
        "recorded_at_utc": record.recorded_at_utc,
        "runtime_config_file": str(record.runtime_config_file),
        "schema_version": record.schema_version,
        "taskwarrior_record_file": str(record.taskwarrior_record_file),
        "telegram_enabled": record.telegram_enabled,
    }

    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def write_release_candidate_acceptance_record(
    record: ReleaseCandidateAcceptanceRecord,
    destination: Path,
    *,
    mode: int = 0o640,
) -> AcceptanceRecordWriteResult:
    """Write one deterministic acceptance record atomically."""
    if not isinstance(record, ReleaseCandidateAcceptanceRecord):
        raise TypeError("record must be a ReleaseCandidateAcceptanceRecord value.")

    _validate_absolute_path(destination, field_name="destination")

    if isinstance(mode, bool) or not isinstance(mode, int) or mode < 0 or mode > 0o7777:
        raise ValueError("mode must be a valid Unix permission mode.")

    document = render_release_candidate_acceptance_record(record)

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)

        if destination.exists():
            if destination.is_symlink() or not destination.is_file():
                raise OSError("Unsafe acceptance-record destination.")

            existing = destination.read_text(encoding="utf-8")

            if existing == document:
                os.chmod(destination, mode)
                return AcceptanceRecordWriteResult(
                    success=True,
                    changed=False,
                    path=destination,
                    issues=(),
                )

        _atomic_replace(
            destination,
            contents=document,
            mode=mode,
        )
    except (OSError, UnicodeError) as error:
        return AcceptanceRecordWriteResult(
            success=False,
            changed=False,
            path=destination,
            issues=(
                InstallerIssue(
                    code=InstallerIssueCode.STEP_FAILED,
                    message=(
                        "Release-candidate acceptance record writing failed: "
                        f"{type(error).__name__}."
                    ),
                    step=InstallerStepId.ACCEPTANCE,
                    path=destination,
                ),
            ),
        )

    return AcceptanceRecordWriteResult(
        success=True,
        changed=True,
        path=destination,
        issues=(),
    )


def _render_check(check: PostInstallCheck) -> dict[str, object]:
    """Render one safe acceptance check."""
    return {
        "code": check.code,
        "message": check.message,
        "path": str(check.path) if check.path is not None else None,
        "state": check.state.value,
    }


def _atomic_replace(
    destination: Path,
    *,
    contents: str,
    mode: int,
) -> None:
    """Atomically replace one UTF-8 acceptance-record file."""
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary = Path(temporary_name)

    try:
        with os.fdopen(
            file_descriptor,
            mode="w",
            encoding="utf-8",
            newline="\n",
        ) as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())

        os.chmod(temporary, mode)
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _validate_absolute_path(
    path: Path,
    *,
    field_name: str,
) -> None:
    """Validate one absolute filesystem path."""
    if not isinstance(path, Path):
        raise TypeError(f"{field_name} must be a pathlib.Path value.")
    if not path.is_absolute():
        raise ValueError(f"{field_name} must be absolute.")
    if "\x00" in str(path):
        raise ValueError(f"{field_name} must not contain a null byte.")
