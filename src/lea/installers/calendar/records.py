"""Strict calendar toolchain installation-record persistence."""

import json
import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lea.installers.calendar.contracts import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
)
from lea.installers.calendar.ownership import (
    CalendarOwnershipApplier,
    ignore_calendar_ownership,
)

_SCHEMA_VERSION = 2
_COMPONENT = "calendar-toolchain"
_SMOKE_TEST_PASSED = "passed"
_RECORD_MODE = 0o640
_RECORD_PARENT_MODE = 0o750


@dataclass(frozen=True, slots=True)
class CalendarToolchainInstallationRecord:
    """Immutable evidence identifying one verified calendar toolchain."""

    schema_version: int
    component: str
    toolchain_version: str
    installation_mode: CalendarToolchainInstallMode
    platform: str
    python_version: str | None
    khal_version: str
    vdirsyncer_version: str
    khal_executable: Path
    vdirsyncer_executable: Path
    lock_or_manifest_sha256: str | None
    khal_executable_sha256: str | None
    vdirsyncer_executable_sha256: str | None
    smoke_test: str
    installed_at: datetime

    def __post_init__(self) -> None:
        """Validate every persisted installation-record field."""
        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or self.schema_version != _SCHEMA_VERSION
        ):
            raise ValueError("schema_version must be 2.")

        if self.component != _COMPONENT:
            raise ValueError("component must be calendar-toolchain.")

        if not isinstance(
            self.installation_mode,
            CalendarToolchainInstallMode,
        ):
            raise TypeError(
                "installation_mode must be a CalendarToolchainInstallMode value."
            )

        for field_name, value in (
            ("toolchain_version", self.toolchain_version),
            ("platform", self.platform),
            ("khal_version", self.khal_version),
            ("vdirsyncer_version", self.vdirsyncer_version),
            ("smoke_test", self.smoke_test),
        ):
            _validate_non_empty_string(
                value,
                field_name=field_name,
            )

        for field_name, path in (
            ("khal_executable", self.khal_executable),
            ("vdirsyncer_executable", self.vdirsyncer_executable),
        ):
            _validate_absolute_path(path, field_name=field_name)

        if self.installation_mode is CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES:
            _validate_external_record_material(self)
        else:
            _validate_managed_record_material(self)

        if self.smoke_test != _SMOKE_TEST_PASSED:
            raise ValueError("smoke_test must be passed.")

        if self.installed_at.tzinfo is None or self.installed_at.utcoffset() is None:
            raise ValueError("installed_at must be timezone-aware.")

        if self.installed_at.utcoffset() != UTC.utcoffset(self.installed_at):
            raise ValueError("installed_at must be canonical UTC.")


def _validate_managed_record_material(
    record: CalendarToolchainInstallationRecord,
) -> None:
    """Require managed Python and lock evidence only."""
    if record.python_version is None:
        raise ValueError("Managed installation records require python_version.")

    _validate_non_empty_string(
        record.python_version,
        field_name="python_version",
    )

    if record.lock_or_manifest_sha256 is None:
        raise ValueError(
            "Managed installation records require lock_or_manifest_sha256."
        )

    _validate_sha256(
        record.lock_or_manifest_sha256,
        field_name="lock_or_manifest_sha256",
    )

    if record.khal_executable_sha256 is not None:
        raise ValueError(
            "Managed installation records must not contain khal_executable_sha256."
        )

    if record.vdirsyncer_executable_sha256 is not None:
        raise ValueError(
            "Managed installation records must not contain "
            "vdirsyncer_executable_sha256."
        )


def _validate_external_record_material(
    record: CalendarToolchainInstallationRecord,
) -> None:
    """Require exact external executable digests without managed evidence."""
    if record.python_version is not None:
        raise ValueError(
            "External installation records must not contain python_version."
        )

    if record.lock_or_manifest_sha256 is not None:
        raise ValueError(
            "External installation records must not contain lock_or_manifest_sha256."
        )

    if record.khal_executable_sha256 is None:
        raise ValueError(
            "External installation records require khal_executable_sha256."
        )

    if record.vdirsyncer_executable_sha256 is None:
        raise ValueError(
            "External installation records require vdirsyncer_executable_sha256."
        )

    _validate_sha256(
        record.khal_executable_sha256,
        field_name="khal_executable_sha256",
    )
    _validate_sha256(
        record.vdirsyncer_executable_sha256,
        field_name="vdirsyncer_executable_sha256",
    )


def create_calendar_toolchain_installation_record(
    config: CalendarToolchainInstallerConfig,
    *,
    python_version: str,
    khal_executable: Path,
    vdirsyncer_executable: Path,
    lock_or_manifest_sha256: str,
    installed_at: datetime,
) -> CalendarToolchainInstallationRecord:
    """Create one strict managed record from verified installer evidence."""
    if not isinstance(config, CalendarToolchainInstallerConfig):
        raise TypeError("config must be a CalendarToolchainInstallerConfig value.")

    if config.mode is CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES:
        raise ValueError(
            "Managed record creation does not accept external-executables mode."
        )

    return CalendarToolchainInstallationRecord(
        schema_version=_SCHEMA_VERSION,
        component=_COMPONENT,
        toolchain_version=config.toolchain_version,
        installation_mode=config.mode,
        platform=config.platform,
        python_version=python_version,
        khal_version=config.khal_version,
        vdirsyncer_version=config.vdirsyncer_version,
        khal_executable=khal_executable,
        vdirsyncer_executable=vdirsyncer_executable,
        lock_or_manifest_sha256=lock_or_manifest_sha256,
        khal_executable_sha256=None,
        vdirsyncer_executable_sha256=None,
        smoke_test=_SMOKE_TEST_PASSED,
        installed_at=installed_at,
    )


def create_external_calendar_toolchain_installation_record(
    config: CalendarToolchainInstallerConfig,
    *,
    khal_executable_sha256: str,
    vdirsyncer_executable_sha256: str,
    installed_at: datetime,
) -> CalendarToolchainInstallationRecord:
    """Create one strict record for exact external executables."""
    if not isinstance(config, CalendarToolchainInstallerConfig):
        raise TypeError("config must be a CalendarToolchainInstallerConfig value.")

    if config.mode is not CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES:
        raise ValueError("External record creation requires external-executables mode.")

    khal_executable = config.external_khal_executable
    vdirsyncer_executable = config.external_vdirsyncer_executable

    if khal_executable is None:
        raise ValueError("external_khal_executable is required.")

    if vdirsyncer_executable is None:
        raise ValueError("external_vdirsyncer_executable is required.")

    return CalendarToolchainInstallationRecord(
        schema_version=_SCHEMA_VERSION,
        component=_COMPONENT,
        toolchain_version=config.toolchain_version,
        installation_mode=config.mode,
        platform=config.platform,
        python_version=None,
        khal_version=config.khal_version,
        vdirsyncer_version=config.vdirsyncer_version,
        khal_executable=khal_executable,
        vdirsyncer_executable=vdirsyncer_executable,
        lock_or_manifest_sha256=None,
        khal_executable_sha256=khal_executable_sha256,
        vdirsyncer_executable_sha256=(vdirsyncer_executable_sha256),
        smoke_test=_SMOKE_TEST_PASSED,
        installed_at=installed_at,
    )


def render_calendar_toolchain_installation_record(
    record: CalendarToolchainInstallationRecord,
) -> str:
    """Render one deterministic, newline-terminated JSON record."""
    if not isinstance(record, CalendarToolchainInstallationRecord):
        raise TypeError("record must be a CalendarToolchainInstallationRecord value.")

    payload = {
        "schema_version": record.schema_version,
        "component": record.component,
        "toolchain_version": record.toolchain_version,
        "installation_mode": record.installation_mode.value,
        "platform": record.platform,
        "python_version": record.python_version,
        "khal_version": record.khal_version,
        "vdirsyncer_version": record.vdirsyncer_version,
        "khal_executable": str(record.khal_executable),
        "vdirsyncer_executable": str(record.vdirsyncer_executable),
        "lock_or_manifest_sha256": (record.lock_or_manifest_sha256),
        "khal_executable_sha256": (record.khal_executable_sha256),
        "vdirsyncer_executable_sha256": (record.vdirsyncer_executable_sha256),
        "smoke_test": record.smoke_test,
        "installed_at": _render_canonical_utc(record.installed_at),
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


def read_calendar_toolchain_installation_record(
    path: Path,
) -> tuple[
    CalendarToolchainInstallationRecord | None,
    tuple[CalendarToolchainInstallerIssue, ...],
]:
    """Read and strictly validate one managed installation record."""
    _validate_absolute_path(path, field_name="path")

    try:
        if path.is_symlink():
            return _record_read_failure(
                path,
                "The calendar toolchain installation record must not "
                "be a symbolic link.",
            )

        if not path.exists():
            return _record_read_failure(
                path,
                "The calendar toolchain installation record does not exist.",
            )

        if not path.is_file():
            return _record_read_failure(
                path,
                "The calendar toolchain installation record is not a regular file.",
            )

        document = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return _record_read_failure(
            path,
            "The calendar toolchain installation record could not be read.",
        )

    try:
        payload = json.loads(
            document,
            object_pairs_hook=_strict_json_object,
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return _record_read_failure(
            path,
            "The calendar toolchain installation record could not be decoded.",
        )

    if not isinstance(payload, dict):
        return _record_read_failure(
            path,
            "The calendar toolchain installation record must contain one JSON object.",
        )

    try:
        record = _parse_record(payload)
    except (KeyError, TypeError, ValueError):
        return _record_read_failure(
            path,
            "The calendar toolchain installation record failed strict validation.",
        )

    return record, ()


def calendar_toolchain_installation_record_matches(
    record: CalendarToolchainInstallationRecord,
    *,
    config: CalendarToolchainInstallerConfig,
    python_version: str,
    khal_executable: Path,
    vdirsyncer_executable: Path,
    lock_or_manifest_sha256: str,
) -> bool:
    """Return whether a managed record identifies the toolchain exactly."""
    if not isinstance(record, CalendarToolchainInstallationRecord):
        raise TypeError("record must be a CalendarToolchainInstallationRecord value.")

    if not isinstance(config, CalendarToolchainInstallerConfig):
        raise TypeError("config must be a CalendarToolchainInstallerConfig value.")

    if config.mode is CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES:
        raise ValueError(
            "Managed record matching does not accept external-executables mode."
        )

    _validate_non_empty_string(
        python_version,
        field_name="python_version",
    )
    _validate_absolute_path(
        khal_executable,
        field_name="khal_executable",
    )
    _validate_absolute_path(
        vdirsyncer_executable,
        field_name="vdirsyncer_executable",
    )
    _validate_sha256(
        lock_or_manifest_sha256,
        field_name="lock_or_manifest_sha256",
    )

    return (
        _record_common_identity_matches(
            record,
            config=config,
            khal_executable=khal_executable,
            vdirsyncer_executable=vdirsyncer_executable,
        )
        and record.python_version == python_version
        and record.lock_or_manifest_sha256 == lock_or_manifest_sha256
        and record.khal_executable_sha256 is None
        and record.vdirsyncer_executable_sha256 is None
    )


def external_calendar_toolchain_installation_record_matches(
    record: CalendarToolchainInstallationRecord,
    *,
    config: CalendarToolchainInstallerConfig,
    khal_executable_sha256: str,
    vdirsyncer_executable_sha256: str,
) -> bool:
    """Return whether a record identifies both external executables."""
    if not isinstance(record, CalendarToolchainInstallationRecord):
        raise TypeError("record must be a CalendarToolchainInstallationRecord value.")

    if not isinstance(config, CalendarToolchainInstallerConfig):
        raise TypeError("config must be a CalendarToolchainInstallerConfig value.")

    if config.mode is not CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES:
        raise ValueError("External record matching requires external-executables mode.")

    khal_executable = config.external_khal_executable
    vdirsyncer_executable = config.external_vdirsyncer_executable

    if khal_executable is None:
        raise ValueError("external_khal_executable is required.")

    if vdirsyncer_executable is None:
        raise ValueError("external_vdirsyncer_executable is required.")

    _validate_sha256(
        khal_executable_sha256,
        field_name="khal_executable_sha256",
    )
    _validate_sha256(
        vdirsyncer_executable_sha256,
        field_name="vdirsyncer_executable_sha256",
    )

    return (
        _record_common_identity_matches(
            record,
            config=config,
            khal_executable=khal_executable,
            vdirsyncer_executable=vdirsyncer_executable,
        )
        and record.python_version is None
        and record.lock_or_manifest_sha256 is None
        and record.khal_executable_sha256 == khal_executable_sha256
        and record.vdirsyncer_executable_sha256 == vdirsyncer_executable_sha256
    )


def _record_common_identity_matches(
    record: CalendarToolchainInstallationRecord,
    *,
    config: CalendarToolchainInstallerConfig,
    khal_executable: Path,
    vdirsyncer_executable: Path,
) -> bool:
    """Compare fields shared by managed and external records."""
    return (
        record.schema_version == _SCHEMA_VERSION
        and record.component == _COMPONENT
        and record.toolchain_version == config.toolchain_version
        and record.installation_mode is config.mode
        and record.platform == config.platform
        and record.khal_version == config.khal_version
        and record.vdirsyncer_version == config.vdirsyncer_version
        and record.khal_executable == khal_executable
        and record.vdirsyncer_executable == vdirsyncer_executable
        and record.smoke_test == _SMOKE_TEST_PASSED
    )


def write_calendar_toolchain_installation_record(
    record: CalendarToolchainInstallationRecord,
    *,
    destination: Path,
    owner: str = "root",
    group: str = "root",
    fsync: bool = False,
    apply_ownership: CalendarOwnershipApplier = (ignore_calendar_ownership),
) -> tuple[CalendarToolchainInstallerIssue, ...]:
    """Atomically create or validate one managed installation record."""
    if not isinstance(record, CalendarToolchainInstallationRecord):
        raise TypeError("record must be a CalendarToolchainInstallationRecord value.")

    _validate_absolute_path(destination, field_name="destination")
    _validate_non_empty_string(owner, field_name="owner")
    _validate_non_empty_string(group, field_name="group")

    document = render_calendar_toolchain_installation_record(record)
    parent_issue = _prepare_record_parent(destination.parent)

    if parent_issue is not None:
        return (parent_issue,)

    existing_issue, existing_matches = _inspect_existing_record(
        destination,
        expected_document=document,
    )

    if existing_issue is not None:
        return (existing_issue,)

    if existing_matches:
        try:
            destination.chmod(_RECORD_MODE)
            apply_ownership(destination, owner, group)

            if fsync:
                _fsync_directory(destination.parent)
        except (KeyError, OSError) as error:
            return (
                _record_issue(
                    message=(
                        "The existing calendar toolchain installation "
                        "record permissions could not be applied: "
                        f"{_error_detail(error)}."
                    ),
                    path=destination,
                ),
            )

        return ()

    temporary_path: Path | None = None
    destination_created = False

    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            text=True,
        )
        temporary_path = Path(temporary_name)

        with os.fdopen(
            descriptor,
            mode="w",
            encoding="utf-8",
            newline="\n",
        ) as stream:
            stream.write(document)
            stream.flush()

            if fsync:
                os.fsync(stream.fileno())

        temporary_path.chmod(_RECORD_MODE)
        os.link(temporary_path, destination)
        destination_created = True
        destination.chmod(_RECORD_MODE)
        apply_ownership(destination, owner, group)

        if fsync:
            _fsync_directory(destination.parent)
    except FileExistsError:
        return (
            _record_issue(
                message=(
                    "The calendar toolchain installation record appeared "
                    "during persistence and was not overwritten."
                ),
                path=destination,
            ),
        )
    except (KeyError, OSError) as error:
        issues = [
            _record_issue(
                message=(
                    "The calendar toolchain installation record could "
                    f"not be written: {_error_detail(error)}."
                ),
                path=destination,
            )
        ]

        if destination_created:
            try:
                destination.unlink()
            except OSError as rollback_error:
                issues.append(
                    _record_issue(
                        message=(
                            "The incomplete calendar toolchain installation "
                            "record could not be removed: "
                            f"{_error_detail(rollback_error)}."
                        ),
                        path=destination,
                    )
                )

        return tuple(issues)
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)

    return ()


def _parse_record(
    payload: dict[str, Any],
) -> CalendarToolchainInstallationRecord:
    """Parse one exact installation-record JSON shape."""
    expected_keys = {
        "schema_version",
        "component",
        "toolchain_version",
        "installation_mode",
        "platform",
        "python_version",
        "khal_version",
        "vdirsyncer_version",
        "khal_executable",
        "vdirsyncer_executable",
        "lock_or_manifest_sha256",
        "khal_executable_sha256",
        "vdirsyncer_executable_sha256",
        "smoke_test",
        "installed_at",
    }

    if set(payload) != expected_keys:
        raise ValueError("Installation-record keys did not match.")

    schema_version = payload["schema_version"]

    if not isinstance(schema_version, int) or isinstance(
        schema_version,
        bool,
    ):
        raise TypeError("schema_version must be an integer.")

    installed_at_raw = _require_string(
        payload["installed_at"],
        field_name="installed_at",
    )
    installed_at = _parse_canonical_utc(installed_at_raw)

    mode_raw = _require_string(
        payload["installation_mode"],
        field_name="installation_mode",
    )

    return CalendarToolchainInstallationRecord(
        schema_version=schema_version,
        component=_require_string(
            payload["component"],
            field_name="component",
        ),
        toolchain_version=_require_string(
            payload["toolchain_version"],
            field_name="toolchain_version",
        ),
        installation_mode=CalendarToolchainInstallMode(mode_raw),
        platform=_require_string(
            payload["platform"],
            field_name="platform",
        ),
        python_version=_require_optional_string(
            payload["python_version"],
            field_name="python_version",
        ),
        khal_version=_require_string(
            payload["khal_version"],
            field_name="khal_version",
        ),
        vdirsyncer_version=_require_string(
            payload["vdirsyncer_version"],
            field_name="vdirsyncer_version",
        ),
        khal_executable=Path(
            _require_string(
                payload["khal_executable"],
                field_name="khal_executable",
            )
        ),
        vdirsyncer_executable=Path(
            _require_string(
                payload["vdirsyncer_executable"],
                field_name="vdirsyncer_executable",
            )
        ),
        lock_or_manifest_sha256=_require_optional_string(
            payload["lock_or_manifest_sha256"],
            field_name="lock_or_manifest_sha256",
        ),
        khal_executable_sha256=_require_optional_string(
            payload["khal_executable_sha256"],
            field_name="khal_executable_sha256",
        ),
        vdirsyncer_executable_sha256=_require_optional_string(
            payload["vdirsyncer_executable_sha256"],
            field_name="vdirsyncer_executable_sha256",
        ),
        smoke_test=_require_string(
            payload["smoke_test"],
            field_name="smoke_test",
        ),
        installed_at=installed_at,
    )


def _require_optional_string(
    value: object,
    *,
    field_name: str,
) -> str | None:
    """Require JSON null or one non-empty string."""
    if value is None:
        return None

    return _require_string(
        value,
        field_name=field_name,
    )


def _strict_json_object(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    """Reject duplicate JSON object keys."""
    result: dict[str, Any] = {}

    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}.")

        result[key] = value

    return result


def _prepare_record_parent(
    parent: Path,
) -> CalendarToolchainInstallerIssue | None:
    """Create one safe parent without traversing symlink ancestors."""
    try:
        current = parent

        while True:
            if current.is_symlink():
                return _record_issue(
                    message=(
                        "The calendar toolchain installation-record path "
                        "must not traverse a symbolic-link directory."
                    ),
                    path=current,
                )

            if current == current.parent:
                break

            current = current.parent

        parent.mkdir(
            mode=_RECORD_PARENT_MODE,
            parents=True,
            exist_ok=True,
        )

        if parent.is_symlink() or not parent.is_dir():
            return _record_issue(
                message=(
                    "The calendar toolchain installation-record parent "
                    "is not a real directory."
                ),
                path=parent,
            )

        parent.chmod(_RECORD_PARENT_MODE)
    except OSError as error:
        return _record_issue(
            message=(
                "The calendar toolchain installation-record parent could "
                f"not be prepared: {_error_detail(error)}."
            ),
            path=parent,
        )

    return None


def _inspect_existing_record(
    destination: Path,
    *,
    expected_document: str,
) -> tuple[CalendarToolchainInstallerIssue | None, bool]:
    """Accept an identical regular record and reject every mismatch."""
    try:
        if destination.is_symlink():
            return (
                _record_issue(
                    message=(
                        "The calendar toolchain installation record must "
                        "not be a symbolic link."
                    ),
                    path=destination,
                ),
                False,
            )

        if not destination.exists():
            return None, False

        if not destination.is_file():
            return (
                _record_issue(
                    message=(
                        "The calendar toolchain installation record exists "
                        "but is not a regular file."
                    ),
                    path=destination,
                ),
                False,
            )

        existing_document = destination.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return (
            _record_issue(
                message=(
                    "The existing calendar toolchain installation record "
                    f"could not be read: {_error_detail(error)}."
                ),
                path=destination,
            ),
            False,
        )

    if existing_document != expected_document:
        return (
            _record_issue(
                message=(
                    "The existing calendar toolchain installation record "
                    "differs from the requested record and was not "
                    "overwritten."
                ),
                path=destination,
            ),
            False,
        )

    return None, True


def _parse_canonical_utc(value: str) -> datetime:
    """Parse canonical ISO-8601 UTC text ending in Z."""
    if not value.endswith("Z"):
        raise ValueError("installed_at must use canonical UTC Z form.")

    parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00").astimezone(UTC)

    if _render_canonical_utc(parsed) != value:
        raise ValueError("installed_at must use canonical UTC Z form.")

    return parsed


def _render_canonical_utc(value: datetime) -> str:
    """Render one canonical UTC timestamp with a Z suffix."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("installed_at must be timezone-aware.")

    if value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("installed_at must be canonical UTC.")

    return value.isoformat().replace("+00:00", "Z")


def _require_string(value: object, *, field_name: str) -> str:
    """Require one non-empty JSON string."""
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be a non-empty string.")

    return value


def _record_read_failure(
    path: Path,
    message: str,
) -> tuple[None, tuple[CalendarToolchainInstallerIssue, ...]]:
    """Create one structured installation-record read failure."""
    return None, (_record_issue(message=message, path=path),)


def _record_issue(
    *,
    message: str,
    path: Path,
) -> CalendarToolchainInstallerIssue:
    """Create one structured record failure."""
    return CalendarToolchainInstallerIssue(
        code=CalendarToolchainInstallFailureCode.RECORD_FAILED,
        message=message,
        field="installation_record",
        path=path,
    )


def _fsync_directory(directory: Path) -> None:
    """Request filesystem synchronisation for one directory."""
    descriptor = os.open(directory, os.O_RDONLY)

    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _error_detail(error: BaseException) -> str:
    """Return bounded deterministic filesystem diagnostics."""
    strerror = getattr(error, "strerror", None)

    if isinstance(strerror, str) and strerror:
        return strerror

    rendered = str(error).strip()
    return rendered or type(error).__name__


def _validate_non_empty_string(
    value: str,
    *,
    field_name: str,
) -> None:
    """Validate one non-empty string."""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")

    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty.")


def _validate_sha256(value: str, *, field_name: str) -> None:
    """Validate canonical lower-case SHA-256 text."""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")

    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{field_name} must be lower-case hexadecimal SHA-256 text.")


def _validate_absolute_path(path: Path, *, field_name: str) -> None:
    """Validate one safe absolute pathlib path."""
    if not isinstance(path, Path):
        raise TypeError(f"{field_name} must be a pathlib.Path value.")

    if not path.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path.")

    if "\x00" in str(path):
        raise ValueError(f"{field_name} must not contain a null byte.")
