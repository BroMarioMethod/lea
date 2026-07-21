"""Tests for immutable LEA runtime configuration contracts."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from lea.runtime import (
    RUNTIME_SCHEMA_VERSION,
    ConfigurationIssue,
    ConfigurationResult,
    RuntimeConfig,
    RuntimePaths,
    RuntimeProfile,
    SecretPaths,
)


def create_paths() -> RuntimePaths:
    """Create one deterministic system runtime layout."""
    return RuntimePaths(
        config_file=Path("/etc/lea/lea.toml"),
        state_dir=Path("/var/lib/lea"),
        log_dir=Path("/var/log/lea"),
        run_dir=Path("/run/lea"),
        audit_dir=Path("/var/lib/lea/audit"),
        proposal_dir=Path("/var/lib/lea/proposals"),
        knowledge_dir=Path("/var/lib/lea/knowledge"),
        index_dir=Path("/var/lib/lea/indexes"),
        adapter_dir=Path("/var/lib/lea/adapters"),
        backup_dir=Path("/var/lib/lea/backups"),
        audit_file=Path("/var/lib/lea/audit/actions-integrity.jsonl"),
        log_file=Path("/var/log/lea/lea.log"),
    )


def create_config() -> RuntimeConfig:
    """Create one deterministic runtime configuration."""
    return RuntimeConfig(
        schema_version=RUNTIME_SCHEMA_VERSION,
        profile=RuntimeProfile.SYSTEM,
        display_timezone="Africa/Gaborone",
        paths=create_paths(),
        secrets=SecretPaths(
            telegram_token_file=Path("/etc/lea/secrets/telegram-bot-token")
        ),
    )


def test_runtime_profiles_have_stable_values() -> None:
    """Runtime profiles should have stable serialised values."""
    assert RuntimeProfile.SYSTEM.value == "system"
    assert RuntimeProfile.DEVELOPMENT.value == "development"
    assert RuntimeProfile.TEST.value == "test"


def test_runtime_schema_version_is_one() -> None:
    """The initial runtime schema version should be stable."""
    assert RUNTIME_SCHEMA_VERSION == 1


def test_valid_runtime_paths() -> None:
    """A canonical system layout should be accepted."""
    paths = create_paths()

    assert paths.audit_file.parent == paths.audit_dir
    assert paths.log_file.parent == paths.log_dir


@pytest.mark.parametrize(
    "field_name",
    [
        "config_file",
        "state_dir",
        "log_dir",
        "run_dir",
        "audit_dir",
        "proposal_dir",
        "knowledge_dir",
        "index_dir",
        "adapter_dir",
        "backup_dir",
        "audit_file",
        "log_file",
    ],
)
def test_relative_runtime_paths_are_rejected(
    field_name: str,
) -> None:
    """Every runtime path must be absolute."""
    values = {
        field.name: getattr(create_paths(), field.name)
        for field in RuntimePaths.__dataclass_fields__.values()
    }
    values[field_name] = Path("relative/path")

    with pytest.raises(
        ValueError,
        match="must be an absolute path",
    ):
        RuntimePaths(**values)


def test_audit_file_must_be_inside_audit_directory() -> None:
    """The audit file must use its configured directory."""
    paths = create_paths()

    with pytest.raises(
        ValueError,
        match="audit_file must be inside audit_dir",
    ):
        RuntimePaths(
            config_file=paths.config_file,
            state_dir=paths.state_dir,
            log_dir=paths.log_dir,
            run_dir=paths.run_dir,
            audit_dir=paths.audit_dir,
            proposal_dir=paths.proposal_dir,
            knowledge_dir=paths.knowledge_dir,
            index_dir=paths.index_dir,
            adapter_dir=paths.adapter_dir,
            backup_dir=paths.backup_dir,
            audit_file=Path("/tmp/actions.jsonl"),
            log_file=paths.log_file,
        )


def test_log_file_must_be_inside_log_directory() -> None:
    """The log file must use its configured directory."""
    paths = create_paths()

    with pytest.raises(
        ValueError,
        match="log_file must be inside log_dir",
    ):
        RuntimePaths(
            config_file=paths.config_file,
            state_dir=paths.state_dir,
            log_dir=paths.log_dir,
            run_dir=paths.run_dir,
            audit_dir=paths.audit_dir,
            proposal_dir=paths.proposal_dir,
            knowledge_dir=paths.knowledge_dir,
            index_dir=paths.index_dir,
            adapter_dir=paths.adapter_dir,
            backup_dir=paths.backup_dir,
            audit_file=paths.audit_file,
            log_file=Path("/tmp/lea.log"),
        )


def test_persistent_directory_inside_run_directory_is_rejected() -> None:
    """Persistent state must not be placed beneath run_dir."""
    paths = create_paths()

    with pytest.raises(
        ValueError,
        match="must not be inside run_dir",
    ):
        RuntimePaths(
            config_file=paths.config_file,
            state_dir=Path("/run/lea/state"),
            log_dir=paths.log_dir,
            run_dir=paths.run_dir,
            audit_dir=paths.audit_dir,
            proposal_dir=paths.proposal_dir,
            knowledge_dir=paths.knowledge_dir,
            index_dir=paths.index_dir,
            adapter_dir=paths.adapter_dir,
            backup_dir=paths.backup_dir,
            audit_file=paths.audit_file,
            log_file=paths.log_file,
        )


def test_optional_secret_path_may_be_absent() -> None:
    """Unused secret references should be optional."""
    assert SecretPaths().telegram_token_file is None


def test_relative_secret_path_is_rejected() -> None:
    """Secret references must use absolute paths."""
    with pytest.raises(
        ValueError,
        match="must be an absolute path",
    ):
        SecretPaths(telegram_token_file=Path("secrets/token"))


def test_valid_runtime_configuration() -> None:
    """A valid immutable runtime configuration should be accepted."""
    config = create_config()

    assert config.profile is RuntimeProfile.SYSTEM
    assert config.display_timezone == "Africa/Gaborone"


def test_unsupported_schema_version_is_rejected() -> None:
    """Unknown configuration schema versions should fail."""
    with pytest.raises(
        ValueError,
        match="Unsupported runtime configuration schema version",
    ):
        RuntimeConfig(
            schema_version=2,
            profile=RuntimeProfile.SYSTEM,
            display_timezone="Africa/Gaborone",
            paths=create_paths(),
            secrets=SecretPaths(),
        )


def test_blank_display_timezone_is_rejected() -> None:
    """A display timezone must contain useful text."""
    with pytest.raises(
        ValueError,
        match="display_timezone must be a non-empty string",
    ):
        RuntimeConfig(
            schema_version=RUNTIME_SCHEMA_VERSION,
            profile=RuntimeProfile.SYSTEM,
            display_timezone="   ",
            paths=create_paths(),
            secrets=SecretPaths(),
        )


def test_runtime_configuration_is_immutable() -> None:
    """Runtime configuration fields must not be reassigned."""
    config = create_config()

    with pytest.raises(FrozenInstanceError):
        config.display_timezone = "UTC"  # type: ignore[misc]


def test_configuration_issue_is_immutable() -> None:
    """Configuration issues should not permit reassignment."""
    issue = ConfigurationIssue(
        code="invalid_path",
        message="The configured path is invalid.",
        field="paths.state_dir",
        source_path=Path("/etc/lea/lea.toml"),
    )

    with pytest.raises(FrozenInstanceError):
        issue.code = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("   ", "The configured path is invalid."),
        ("invalid_path", "   "),
    ],
)
def test_configuration_issue_rejects_blank_required_fields(
    code: str,
    message: str,
) -> None:
    """Issue codes and messages must contain useful text."""
    with pytest.raises(ValueError, match="must be non-empty"):
        ConfigurationIssue(
            code=code,
            message=message,
        )


def test_successful_configuration_result() -> None:
    """A successful result should contain configuration only."""
    config = create_config()

    result = ConfigurationResult(
        success=True,
        config=config,
        issues=(),
    )

    assert result.config is config
    assert result.issues == ()


def test_failed_configuration_result() -> None:
    """A failed result should contain one or more issues."""
    issue = ConfigurationIssue(
        code="configuration_not_found",
        message="The configuration file was not found.",
        source_path=Path("/etc/lea/lea.toml"),
    )

    result = ConfigurationResult(
        success=False,
        config=None,
        issues=(issue,),
    )

    assert result.success is False
    assert result.issues == (issue,)


def test_successful_result_requires_configuration() -> None:
    """Success without configuration should be impossible."""
    with pytest.raises(
        ValueError,
        match="must contain a runtime configuration",
    ):
        ConfigurationResult(
            success=True,
            config=None,
            issues=(),
        )


def test_successful_result_rejects_issues() -> None:
    """Successful results must not contain issues."""
    issue = ConfigurationIssue(
        code="invalid_path",
        message="The configured path is invalid.",
    )

    with pytest.raises(
        ValueError,
        match="must not contain issues",
    ):
        ConfigurationResult(
            success=True,
            config=create_config(),
            issues=(issue,),
        )


def test_failed_result_rejects_configuration() -> None:
    """Failed results must not expose a configuration."""
    issue = ConfigurationIssue(
        code="invalid_path",
        message="The configured path is invalid.",
    )

    with pytest.raises(
        ValueError,
        match="must not contain a runtime configuration",
    ):
        ConfigurationResult(
            success=False,
            config=create_config(),
            issues=(issue,),
        )


def test_failed_result_requires_issues() -> None:
    """Failure without diagnostic issues should be impossible."""
    with pytest.raises(
        ValueError,
        match="must contain at least one issue",
    ):
        ConfigurationResult(
            success=False,
            config=None,
            issues=(),
        )
