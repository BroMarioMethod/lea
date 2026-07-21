"""Immutable contracts for LEA runtime configuration."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

RUNTIME_SCHEMA_VERSION = 1


class RuntimeProfile(StrEnum):
    """Supported LEA runtime deployment profiles."""

    SYSTEM = "system"
    DEVELOPMENT = "development"
    TEST = "test"


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    """Canonical filesystem paths used by one LEA runtime."""

    config_file: Path
    state_dir: Path
    log_dir: Path
    run_dir: Path
    audit_dir: Path
    proposal_dir: Path
    knowledge_dir: Path
    index_dir: Path
    adapter_dir: Path
    backup_dir: Path
    audit_file: Path
    log_file: Path

    def __post_init__(self) -> None:
        """Validate canonical runtime path relationships."""
        for field_name, path in self._named_paths():
            _validate_absolute_path(
                path,
                field_name=field_name,
            )

        if not self.audit_file.is_relative_to(self.audit_dir):
            raise ValueError("audit_file must be inside audit_dir.")

        if not self.log_file.is_relative_to(self.log_dir):
            raise ValueError("log_file must be inside log_dir.")

        persistent_directories = (
            self.state_dir,
            self.log_dir,
            self.audit_dir,
            self.proposal_dir,
            self.knowledge_dir,
            self.index_dir,
            self.adapter_dir,
            self.backup_dir,
        )

        for directory in persistent_directories:
            if directory.is_relative_to(self.run_dir):
                raise ValueError(
                    "Persistent runtime directories must not be inside run_dir."
                )

    def _named_paths(
        self,
    ) -> tuple[tuple[str, Path], ...]:
        """Return every runtime path with its public field name."""
        return (
            ("config_file", self.config_file),
            ("state_dir", self.state_dir),
            ("log_dir", self.log_dir),
            ("run_dir", self.run_dir),
            ("audit_dir", self.audit_dir),
            ("proposal_dir", self.proposal_dir),
            ("knowledge_dir", self.knowledge_dir),
            ("index_dir", self.index_dir),
            ("adapter_dir", self.adapter_dir),
            ("backup_dir", self.backup_dir),
            ("audit_file", self.audit_file),
            ("log_file", self.log_file),
        )


@dataclass(frozen=True, slots=True)
class SecretPaths:
    """Filesystem references to secrets without secret values."""

    telegram_token_file: Path | None = None

    def __post_init__(self) -> None:
        """Validate configured secret-file paths."""
        if self.telegram_token_file is not None:
            _validate_absolute_path(
                self.telegram_token_file,
                field_name="telegram_token_file",
            )


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Immutable validated LEA runtime configuration."""

    schema_version: int
    profile: RuntimeProfile
    display_timezone: str
    paths: RuntimePaths
    secrets: SecretPaths

    def __post_init__(self) -> None:
        """Validate top-level runtime configuration fields."""
        if self.schema_version != RUNTIME_SCHEMA_VERSION:
            raise ValueError("Unsupported runtime configuration schema version.")

        if not self.display_timezone.strip():
            raise ValueError("display_timezone must be a non-empty string.")


@dataclass(frozen=True, slots=True)
class ConfigurationIssue:
    """One deterministic runtime configuration problem."""

    code: str
    message: str
    field: str | None = None
    source_path: Path | None = None

    def __post_init__(self) -> None:
        """Validate configuration issue fields."""
        if not self.code.strip():
            raise ValueError("Configuration issue code must be non-empty.")

        if not self.message.strip():
            raise ValueError("Configuration issue message must be non-empty.")

        if self.field is not None and not self.field.strip():
            raise ValueError(
                "Configuration issue field must be non-empty when provided."
            )

        if self.source_path is not None:
            _validate_absolute_path(
                self.source_path,
                field_name="source_path",
            )


@dataclass(frozen=True, slots=True)
class ConfigurationResult:
    """Immutable result of loading or validating configuration."""

    success: bool
    config: RuntimeConfig | None
    issues: tuple[ConfigurationIssue, ...]

    def __post_init__(self) -> None:
        """Enforce consistency between result fields."""
        if self.success:
            if self.config is None:
                raise ValueError(
                    "A successful configuration result must contain "
                    "a runtime configuration."
                )

            if self.issues:
                raise ValueError(
                    "A successful configuration result must not contain issues."
                )

            return

        if self.config is not None:
            raise ValueError(
                "A failed configuration result must not contain "
                "a runtime configuration."
            )

        if not self.issues:
            raise ValueError(
                "A failed configuration result must contain at least one issue."
            )


def _validate_absolute_path(
    path: Path,
    *,
    field_name: str,
) -> None:
    """Validate one non-empty absolute path without filesystem access."""
    if not isinstance(path, Path):
        raise TypeError(f"{field_name} must be a pathlib.Path.")

    if "\x00" in str(path):
        raise ValueError(f"{field_name} must not contain a null byte.")

    if not path.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path.")
