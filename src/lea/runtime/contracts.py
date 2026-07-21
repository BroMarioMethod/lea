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


class RuntimePathStatus(StrEnum):
    """Result status for one runtime bootstrap path."""

    WOULD_CREATE = "would_create"
    CREATED = "created"
    ALREADY_EXISTS = "already_exists"
    CONFLICT = "conflict"
    FAILED = "failed"


class RuntimeHealthStatus(StrEnum):
    """Status of one runtime health check."""

    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


class RuntimeInitialisationStatus(StrEnum):
    """Status of runtime configuration initialisation."""

    WOULD_CREATE = "would_create"
    CREATED = "created"
    ALREADY_EXISTS = "already_exists"
    CONFLICT = "conflict"
    FAILED = "failed"


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


@dataclass(frozen=True, slots=True)
class RuntimePathResult:
    """Immutable bootstrap result for one runtime directory."""

    path: Path
    status: RuntimePathStatus
    message: str

    def __post_init__(self) -> None:
        """Validate runtime-path result fields."""
        _validate_absolute_path(
            self.path,
            field_name="path",
        )

        if not self.message.strip():
            raise ValueError("Runtime path result message must be non-empty.")


@dataclass(frozen=True, slots=True)
class RuntimeBootstrapResult:
    """Immutable result of bootstrapping runtime directories."""

    success: bool
    dry_run: bool
    paths: tuple[RuntimePathResult, ...]

    def __post_init__(self) -> None:
        """Validate bootstrap-result consistency."""
        failure_statuses = {
            RuntimePathStatus.CONFLICT,
            RuntimePathStatus.FAILED,
        }
        has_failure = any(result.status in failure_statuses for result in self.paths)

        if self.success and has_failure:
            raise ValueError(
                "A successful bootstrap result must not contain "
                "conflicting or failed paths."
            )

        if not self.success and not has_failure:
            raise ValueError(
                "A failed bootstrap result must contain at least one "
                "conflicting or failed path."
            )


@dataclass(frozen=True, slots=True)
class RuntimeHealthIssue:
    """Immutable result of one runtime health check."""

    code: str
    message: str
    status: RuntimeHealthStatus
    path: Path | None = None
    field: str | None = None

    def __post_init__(self) -> None:
        """Validate runtime-health issue fields."""
        if not self.code.strip():
            raise ValueError("Runtime health issue code must be non-empty.")

        if not self.message.strip():
            raise ValueError("Runtime health issue message must be non-empty.")

        if self.path is not None:
            _validate_absolute_path(
                self.path,
                field_name="path",
            )

        if self.field is not None and not self.field.strip():
            raise ValueError(
                "Runtime health issue field must be non-empty when provided."
            )


@dataclass(frozen=True, slots=True)
class RuntimeHealthResult:
    """Immutable result of checking one configured runtime."""

    healthy: bool
    issues: tuple[RuntimeHealthIssue, ...]

    def __post_init__(self) -> None:
        """Validate health-result consistency."""
        has_failure = any(
            issue.status is RuntimeHealthStatus.FAILED for issue in self.issues
        )

        if self.healthy and has_failure:
            raise ValueError("A healthy runtime result must not contain failed checks.")

        if not self.healthy and not has_failure:
            raise ValueError(
                "An unhealthy runtime result must contain at least one failed check."
            )


@dataclass(frozen=True, slots=True)
class RuntimeInitialisationResult:
    """Immutable result of runtime configuration initialisation."""

    success: bool
    dry_run: bool
    status: RuntimeInitialisationStatus
    destination: Path
    message: str

    def __post_init__(self) -> None:
        """Validate initialisation-result consistency."""
        _validate_absolute_path(
            self.destination,
            field_name="destination",
        )

        if not self.message.strip():
            raise ValueError("Runtime initialisation message must be non-empty.")

        successful_statuses = {
            RuntimeInitialisationStatus.WOULD_CREATE,
            RuntimeInitialisationStatus.CREATED,
        }

        if self.success and self.status not in successful_statuses:
            raise ValueError(
                "A successful initialisation result must use a successful status."
            )

        if not self.success and self.status in successful_statuses:
            raise ValueError(
                "A failed initialisation result must use a failure status."
            )

        if self.dry_run and self.status is RuntimeInitialisationStatus.CREATED:
            raise ValueError(
                "A dry-run initialisation result must not report a "
                "created configuration."
            )

        if not self.dry_run and self.status is RuntimeInitialisationStatus.WOULD_CREATE:
            raise ValueError(
                "A non-dry-run initialisation result must not report "
                "that it would create a configuration."
            )


@dataclass(frozen=True, slots=True)
class RuntimeSetupResult:
    """Immutable result of coordinated runtime setup."""

    success: bool
    dry_run: bool
    initialisation: RuntimeInitialisationResult
    bootstrap: RuntimeBootstrapResult | None

    def __post_init__(self) -> None:
        """Validate combined setup-result consistency."""
        if self.initialisation.dry_run != self.dry_run:
            raise ValueError(
                "The initialisation result dry-run value must match the setup result."
            )

        if self.bootstrap is not None and self.bootstrap.dry_run != self.dry_run:
            raise ValueError(
                "The bootstrap result dry-run value must match the setup result."
            )

        expected_success = (
            self.initialisation.success
            and self.bootstrap is not None
            and self.bootstrap.success
        )

        if self.success != expected_success:
            raise ValueError(
                "Runtime setup success must match its underlying operation results."
            )

        if not self.initialisation.success and self.bootstrap is not None:
            raise ValueError(
                "Runtime bootstrap must not run after configuration "
                "initialisation fails."
            )


@dataclass(frozen=True, slots=True)
class RuntimeSetupVerificationResult:
    """Immutable result of runtime setup and health verification."""

    verified: bool
    dry_run: bool
    setup: RuntimeSetupResult
    health: RuntimeHealthResult | None

    def __post_init__(self) -> None:
        """Validate setup-verification result consistency."""
        if self.setup.dry_run != self.dry_run:
            raise ValueError(
                "The setup result dry-run value must match the verification result."
            )

        if not self.setup.success:
            if self.health is not None:
                raise ValueError(
                    "Runtime health must not be checked after setup fails."
                )

            if self.verified:
                raise ValueError("A failed runtime setup must not be verified.")

            return

        if self.dry_run:
            if self.health is not None:
                raise ValueError(
                    "Dry-run setup must not produce a runtime health result."
                )

            if self.verified:
                raise ValueError(
                    "Dry-run setup must not claim that the runtime was verified."
                )

            return

        if self.health is None:
            raise ValueError(
                "Successful real setup must include a runtime health result."
            )

        if self.verified != self.health.healthy:
            raise ValueError(
                "Runtime verification status must match the health result."
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
