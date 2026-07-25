"""Base configuration generation for release-candidate installation."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from lea.installers.release_candidate.contracts import (
    InstallerIssue,
    InstallerIssueCode,
    InstallerStepId,
    ReleaseCandidateInstallMode,
    ReleaseCandidateInstallRequest,
)
from lea.runtime import (
    ConfigurationResult,
    load_runtime_config,
    render_runtime_config,
    system_runtime_config,
)

Clock = Callable[[], datetime]
OwnershipApplier = Callable[[Path, str, str], None]
RuntimeLoader = Callable[[Path], ConfigurationResult]

_RECORD_FIELDS = frozenset(
    {
        "configuration_file",
        "display_timezone",
        "installation_mode",
        "installed_at_utc",
        "lea_version",
        "schema_version",
    }
)


@dataclass(frozen=True, slots=True)
class BaseConfigurationPlan:
    """Immutable plan for LEA base configuration and installation records."""

    configuration_file: Path
    installation_record: Path
    backup_directory: Path
    owner: str
    group: str
    mode: int
    rendered_configuration: str

    def __post_init__(self) -> None:
        """Validate configuration-plan fields."""
        for field_name, path in (
            ("configuration_file", self.configuration_file),
            ("installation_record", self.installation_record),
            ("backup_directory", self.backup_directory),
        ):
            _validate_absolute_path(path, field_name=field_name)

        for field_name, value in (
            ("owner", self.owner),
            ("group", self.group),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be non-empty.")

        if self.mode < 0 or self.mode > 0o7777:
            raise ValueError("mode must be a valid Unix permission mode.")

        if not self.rendered_configuration.strip():
            raise ValueError("rendered_configuration must be non-empty.")


@dataclass(frozen=True, slots=True)
class ReleaseCandidateInstallationRecord:
    """Machine-readable record for one release-candidate installation."""

    schema_version: int
    lea_version: str
    installed_at_utc: str
    installation_mode: str
    display_timezone: str
    configuration_file: Path

    def __post_init__(self) -> None:
        """Validate installation-record fields."""
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != 1
        ):
            raise ValueError("Unsupported installation record schema version.")

        for field_name, value in (
            ("lea_version", self.lea_version),
            ("installed_at_utc", self.installed_at_utc),
            ("installation_mode", self.installation_mode),
            ("display_timezone", self.display_timezone),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be non-empty.")

        try:
            timestamp = datetime.fromisoformat(self.installed_at_utc)
        except ValueError as error:
            raise ValueError(
                "installed_at_utc must be a valid ISO-8601 timestamp."
            ) from error

        if timestamp.tzinfo is None or timestamp.utcoffset() != UTC.utcoffset(
            timestamp
        ):
            raise ValueError("installed_at_utc must use UTC.")

        try:
            ReleaseCandidateInstallMode(self.installation_mode)
        except ValueError as error:
            raise ValueError("installation_mode is not supported.") from error

        _validate_absolute_path(
            self.configuration_file,
            field_name="configuration_file",
        )


@dataclass(frozen=True, slots=True)
class BaseConfigurationResult:
    """Result of writing base configuration and installation records."""

    success: bool
    configuration_changed: bool
    record_changed: bool
    backups_created: tuple[Path, ...]
    issues: tuple[InstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate result consistency."""
        for path in self.backups_created:
            _validate_absolute_path(path, field_name="backups_created")

        if len(set(self.backups_created)) != len(self.backups_created):
            raise ValueError("backups_created must not contain duplicates.")

        if self.success:
            if self.issues:
                raise ValueError("A successful result must not contain issues.")
            return

        if not self.issues:
            raise ValueError("A failed result must contain at least one issue.")


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    """One pre-mutation managed-file state used for rollback."""

    existed: bool
    contents: str | None
    mode: int | None


def create_base_configuration_plan(
    request: ReleaseCandidateInstallRequest,
) -> BaseConfigurationPlan:
    """Create deterministic base runtime configuration."""
    if not isinstance(request, ReleaseCandidateInstallRequest):
        raise TypeError("request must be a ReleaseCandidateInstallRequest value.")

    config_file = request.configuration_root / "lea.toml"
    telegram_token_file = (
        request.configuration_root / "secrets" / "telegram-bot-token"
        if request.enable_telegram
        else None
    )
    runtime_config = system_runtime_config(
        display_timezone=request.display_timezone,
        telegram_token_file=telegram_token_file,
    )

    return BaseConfigurationPlan(
        configuration_file=config_file,
        installation_record=request.state_root / "install" / "release-candidate.json",
        backup_directory=request.state_root / "backups" / "configuration",
        owner="root",
        group=request.service_group,
        mode=0o640,
        rendered_configuration=render_runtime_config(runtime_config),
    )


def create_installation_record(
    *,
    request: ReleaseCandidateInstallRequest,
    lea_version: str,
    clock: Clock = lambda: datetime.now(UTC),
) -> ReleaseCandidateInstallationRecord:
    """Create one deterministic installation record."""
    if not lea_version.strip():
        raise ValueError("lea_version must be non-empty.")

    timestamp = clock()
    if timestamp.tzinfo is None:
        raise ValueError("clock must return a timezone-aware datetime.")

    return ReleaseCandidateInstallationRecord(
        schema_version=1,
        lea_version=lea_version,
        installed_at_utc=timestamp.astimezone(UTC).isoformat(),
        installation_mode=request.mode.value,
        display_timezone=request.display_timezone,
        configuration_file=request.configuration_root / "lea.toml",
    )


def render_installation_record(
    record: ReleaseCandidateInstallationRecord,
) -> str:
    """Render one deterministic installation record as JSON."""
    payload = {
        "configuration_file": str(record.configuration_file),
        "display_timezone": record.display_timezone,
        "installation_mode": record.installation_mode,
        "installed_at_utc": record.installed_at_utc,
        "lea_version": record.lea_version,
        "schema_version": record.schema_version,
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


def read_installation_record(
    source_path: Path,
) -> ReleaseCandidateInstallationRecord | None:
    """Read and validate one strict release-candidate installation record."""
    _validate_absolute_path(source_path, field_name="source_path")

    if source_path.is_symlink() or not source_path.is_file():
        return None

    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None

    if not isinstance(payload, Mapping) or set(payload) != _RECORD_FIELDS:
        return None

    data = cast(Mapping[str, object], payload)
    schema_version = data["schema_version"]
    lea_version = data["lea_version"]
    installed_at_utc = data["installed_at_utc"]
    installation_mode = data["installation_mode"]
    display_timezone = data["display_timezone"]
    configuration_file = data["configuration_file"]

    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or not isinstance(lea_version, str)
        or not isinstance(installed_at_utc, str)
        or not isinstance(installation_mode, str)
        or not isinstance(display_timezone, str)
        or not isinstance(configuration_file, str)
    ):
        return None

    try:
        return ReleaseCandidateInstallationRecord(
            schema_version=schema_version,
            lea_version=lea_version,
            installed_at_utc=installed_at_utc,
            installation_mode=installation_mode,
            display_timezone=display_timezone,
            configuration_file=Path(configuration_file),
        )
    except (TypeError, ValueError):
        return None


def install_base_configuration(
    plan: BaseConfigurationPlan,
    record: ReleaseCandidateInstallationRecord,
    *,
    apply_ownership: OwnershipApplier = lambda _path, _owner, _group: None,
    runtime_loader: RuntimeLoader = load_runtime_config,
) -> BaseConfigurationResult:
    """Install configuration and its record transactionally."""
    if not isinstance(plan, BaseConfigurationPlan):
        raise TypeError("plan must be a BaseConfigurationPlan value.")

    if not isinstance(record, ReleaseCandidateInstallationRecord):
        raise TypeError("record must be a ReleaseCandidateInstallationRecord value.")

    backups: list[Path] = []
    configuration_changed = False
    record_changed = False
    rollback_failed = False
    configuration_snapshot: _FileSnapshot | None = None
    record_snapshot: _FileSnapshot | None = None

    try:
        plan.configuration_file.parent.mkdir(parents=True, exist_ok=True)
        plan.installation_record.parent.mkdir(parents=True, exist_ok=True)
        plan.backup_directory.mkdir(parents=True, exist_ok=True)

        configuration_snapshot = _capture_snapshot(plan.configuration_file)
        record_snapshot = _capture_snapshot(plan.installation_record)
        effective_record = _preserve_initial_timestamp(
            plan.installation_record,
            record,
        )

        configuration_changed, configuration_backup = _write_if_changed(
            destination=plan.configuration_file,
            contents=plan.rendered_configuration,
            backup_directory=plan.backup_directory,
            mode=plan.mode,
            backup_mode=plan.mode,
        )
        apply_ownership(plan.configuration_file, plan.owner, plan.group)
        if configuration_backup is not None:
            backups.append(configuration_backup)
            apply_ownership(configuration_backup, plan.owner, plan.group)

        validation = runtime_loader(plan.configuration_file)
        if not validation.success:
            raise ValueError("Generated runtime configuration failed validation.")

        record_changed, record_backup = _write_if_changed(
            destination=plan.installation_record,
            contents=render_installation_record(effective_record),
            backup_directory=plan.backup_directory,
            mode=0o640,
            backup_mode=0o640,
        )
        apply_ownership(plan.installation_record, plan.owner, plan.group)
        if record_backup is not None:
            backups.append(record_backup)
            apply_ownership(record_backup, plan.owner, plan.group)

    except (OSError, RuntimeError, ValueError) as error:
        try:
            if record_snapshot is not None:
                _restore_snapshot(plan.installation_record, record_snapshot)
                if record_snapshot.existed:
                    apply_ownership(plan.installation_record, plan.owner, plan.group)

            if configuration_snapshot is not None:
                _restore_snapshot(plan.configuration_file, configuration_snapshot)
                if configuration_snapshot.existed:
                    apply_ownership(plan.configuration_file, plan.owner, plan.group)
        except (OSError, RuntimeError, ValueError):
            rollback_failed = True

        issues = [
            InstallerIssue(
                code=InstallerIssueCode.STEP_FAILED,
                message=(
                    f"Base configuration installation failed: {type(error).__name__}."
                ),
                step=InstallerStepId.BASE_CONFIGURATION,
            )
        ]
        if rollback_failed:
            issues.append(
                InstallerIssue(
                    code=InstallerIssueCode.ROLLBACK_FAILED,
                    message="Base configuration rollback failed.",
                    step=InstallerStepId.BASE_CONFIGURATION,
                )
            )

        return BaseConfigurationResult(
            success=False,
            configuration_changed=(configuration_changed if rollback_failed else False),
            record_changed=record_changed if rollback_failed else False,
            backups_created=tuple(backups),
            issues=tuple(issues),
        )

    return BaseConfigurationResult(
        success=True,
        configuration_changed=configuration_changed,
        record_changed=record_changed,
        backups_created=tuple(backups),
        issues=(),
    )


def _preserve_initial_timestamp(
    source_path: Path,
    proposed: ReleaseCandidateInstallationRecord,
) -> ReleaseCandidateInstallationRecord:
    """Preserve installed_at_utc for an otherwise identical installation."""
    existing = read_installation_record(source_path)

    if existing is None:
        return proposed

    if (
        existing.schema_version == proposed.schema_version
        and existing.lea_version == proposed.lea_version
        and existing.installation_mode == proposed.installation_mode
        and existing.display_timezone == proposed.display_timezone
        and existing.configuration_file == proposed.configuration_file
    ):
        return existing

    return proposed


def _capture_snapshot(destination: Path) -> _FileSnapshot:
    """Capture one safe managed file before mutation."""
    if not destination.exists():
        return _FileSnapshot(existed=False, contents=None, mode=None)

    if destination.is_symlink() or not destination.is_file():
        raise OSError(f"Unsafe managed file path: {destination}")

    return _FileSnapshot(
        existed=True,
        contents=destination.read_text(encoding="utf-8"),
        mode=destination.stat().st_mode & 0o7777,
    )


def _restore_snapshot(
    destination: Path,
    snapshot: _FileSnapshot,
) -> None:
    """Restore one managed file to its captured state."""
    if not snapshot.existed:
        destination.unlink(missing_ok=True)
        return

    if snapshot.contents is None or snapshot.mode is None:
        raise ValueError("Existing file snapshots require contents and mode.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    _atomic_replace(
        destination,
        contents=snapshot.contents,
        mode=snapshot.mode,
    )


def _write_if_changed(
    *,
    destination: Path,
    contents: str,
    backup_directory: Path,
    mode: int,
    backup_mode: int | None = None,
) -> tuple[bool, Path | None]:
    """Atomically write changed contents and back up an existing file."""
    if destination.exists():
        if not destination.is_file() or destination.is_symlink():
            raise OSError(f"Unsafe managed file path: {destination}")

        existing = destination.read_text(encoding="utf-8")
        if existing == contents:
            os.chmod(destination, mode)
            return False, None

        backup = _create_backup(
            destination,
            backup_directory,
            mode=mode if backup_mode is None else backup_mode,
        )
    else:
        backup = None

    _atomic_replace(destination, contents=contents, mode=mode)
    return True, backup


def _atomic_replace(
    destination: Path,
    *,
    contents: str,
    mode: int,
) -> None:
    """Atomically replace one UTF-8 managed file."""
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


def _create_backup(
    source: Path,
    backup_directory: Path,
    *,
    mode: int,
) -> Path:
    """Create a deterministic next-numbered backup."""
    index = 1
    while True:
        candidate = backup_directory / f"{source.name}.{index:04d}.bak"
        if not candidate.exists():
            break
        index += 1

    shutil.copy2(source, candidate)
    os.chmod(candidate, mode)
    return candidate


def _validate_absolute_path(
    path: Path,
    *,
    field_name: str,
) -> None:
    """Validate one absolute pathlib path."""
    if not isinstance(path, Path):
        raise TypeError(f"{field_name} must be a pathlib.Path value.")

    if not path.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path.")

    if "\x00" in str(path):
        raise ValueError(f"{field_name} must not contain a null byte.")
