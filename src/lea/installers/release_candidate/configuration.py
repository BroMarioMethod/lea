"""Base configuration generation for release-candidate installation."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from lea.installers.release_candidate.contracts import (
    InstallerIssue,
    InstallerIssueCode,
    InstallerStepId,
    ReleaseCandidateInstallRequest,
)
from lea.runtime import (
    load_runtime_config,
    render_runtime_config,
    system_runtime_config,
)

Clock = Callable[[], datetime]


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
            if not value.strip():
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
        if self.schema_version != 1:
            raise ValueError("Unsupported installation record schema version.")

        for field_name, value in (
            ("lea_version", self.lea_version),
            ("installed_at_utc", self.installed_at_utc),
            ("installation_mode", self.installation_mode),
            ("display_timezone", self.display_timezone),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty.")

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


def create_base_configuration_plan(
    request: ReleaseCandidateInstallRequest,
) -> BaseConfigurationPlan:
    """Create deterministic base runtime configuration."""
    if not isinstance(request, ReleaseCandidateInstallRequest):
        raise TypeError("request must be a ReleaseCandidateInstallRequest value.")

    config_file = request.configuration_root / "lea.toml"
    runtime_config = system_runtime_config(
        display_timezone=request.display_timezone,
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


def install_base_configuration(
    plan: BaseConfigurationPlan,
    record: ReleaseCandidateInstallationRecord,
) -> BaseConfigurationResult:
    """Atomically install validated configuration and its installation record."""
    if not isinstance(plan, BaseConfigurationPlan):
        raise TypeError("plan must be a BaseConfigurationPlan value.")

    if not isinstance(record, ReleaseCandidateInstallationRecord):
        raise TypeError("record must be a ReleaseCandidateInstallationRecord value.")

    backups: list[Path] = []

    try:
        plan.configuration_file.parent.mkdir(parents=True, exist_ok=True)
        plan.installation_record.parent.mkdir(parents=True, exist_ok=True)
        plan.backup_directory.mkdir(parents=True, exist_ok=True)

        configuration_changed, configuration_backup = _write_if_changed(
            destination=plan.configuration_file,
            contents=plan.rendered_configuration,
            backup_directory=plan.backup_directory,
            mode=plan.mode,
        )
        if configuration_backup is not None:
            backups.append(configuration_backup)

        validation = load_runtime_config(plan.configuration_file)
        if not validation.success:
            raise ValueError("Generated runtime configuration failed validation.")

        record_changed, record_backup = _write_if_changed(
            destination=plan.installation_record,
            contents=render_installation_record(record),
            backup_directory=plan.backup_directory,
            mode=0o640,
        )
        if record_backup is not None:
            backups.append(record_backup)

    except (OSError, ValueError) as error:
        return BaseConfigurationResult(
            success=False,
            configuration_changed=False,
            record_changed=False,
            backups_created=tuple(backups),
            issues=(
                InstallerIssue(
                    code=InstallerIssueCode.STEP_FAILED,
                    message=(
                        "Base configuration installation failed: "
                        f"{type(error).__name__}."
                    ),
                    step=InstallerStepId.BASE_CONFIGURATION,
                ),
            ),
        )

    return BaseConfigurationResult(
        success=True,
        configuration_changed=configuration_changed,
        record_changed=record_changed,
        backups_created=tuple(backups),
        issues=(),
    )


def _write_if_changed(
    *,
    destination: Path,
    contents: str,
    backup_directory: Path,
    mode: int,
) -> tuple[bool, Path | None]:
    """Atomically write changed contents and back up an existing file."""
    if destination.exists():
        if not destination.is_file() or destination.is_symlink():
            raise OSError(f"Unsafe managed file path: {destination}")

        existing = destination.read_text(encoding="utf-8")
        if existing == contents:
            os.chmod(destination, mode)
            return False, None

        backup = _create_backup(destination, backup_directory)
    else:
        backup = None

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

    return True, backup


def _create_backup(
    source: Path,
    backup_directory: Path,
) -> Path:
    """Create a deterministic next-numbered backup."""
    index = 1
    while True:
        candidate = backup_directory / f"{source.name}.{index:04d}.bak"
        if not candidate.exists():
            break
        index += 1

    shutil.copy2(source, candidate)
    os.chmod(candidate, 0o640)
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
