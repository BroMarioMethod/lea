"""Tests for read-only LEA runtime health checks."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from lea.runtime import (
    RUNTIME_SCHEMA_VERSION,
    ComponentRecordPaths,
    RuntimeConfig,
    RuntimeHealthIssue,
    RuntimeHealthResult,
    RuntimeHealthStatus,
    RuntimePaths,
    RuntimeProfile,
    SecretPaths,
    bootstrap_runtime,
    check_runtime_health,
)


def create_paths(root: Path) -> RuntimePaths:
    """Create one deterministic runtime layout."""
    state_dir = root / "state"
    log_dir = root / "log"
    run_dir = root / "run"

    return RuntimePaths(
        config_file=root / "config" / "lea.toml",
        state_dir=state_dir,
        log_dir=log_dir,
        run_dir=run_dir,
        audit_dir=state_dir / "audit",
        proposal_dir=state_dir / "proposals",
        knowledge_dir=state_dir / "knowledge",
        index_dir=state_dir / "indexes",
        adapter_dir=state_dir / "adapters",
        backup_dir=state_dir / "backups",
        audit_file=state_dir / "audit" / "actions-integrity.jsonl",
        log_file=log_dir / "lea.log",
    )


def create_config(
    root: Path,
    *,
    secret_path: Path | None = None,
) -> RuntimeConfig:
    """Create one deterministic runtime configuration."""
    return RuntimeConfig(
        schema_version=RUNTIME_SCHEMA_VERSION,
        profile=RuntimeProfile.TEST,
        display_timezone="Africa/Gaborone",
        paths=create_paths(root),
        component_records=ComponentRecordPaths(
            taskwarrior=root / "state" / "install" / "taskwarrior.json",
        ),
        secrets=SecretPaths(
            telegram_token_file=secret_path,
        ),
    )


def prepare_complete_runtime(
    config: RuntimeConfig,
) -> None:
    """Create a complete readable runtime for health tests."""
    config.paths.config_file.parent.mkdir(parents=True)
    config.paths.config_file.write_text(
        "schema_version = 1\n",
        encoding="utf-8",
    )

    result = bootstrap_runtime(config.paths)
    assert result.success is True


def test_complete_runtime_is_healthy(
    tmp_path: Path,
) -> None:
    """A complete runtime should pass all required checks."""
    secret_path = tmp_path / "runtime" / "secrets" / "token"
    config = create_config(
        tmp_path / "runtime",
        secret_path=secret_path,
    )
    prepare_complete_runtime(config)
    secret_path.parent.mkdir(parents=True)
    secret_path.write_text("secret", encoding="utf-8")

    result = check_runtime_health(config)

    assert result.healthy is True
    assert all(
        issue.status is not RuntimeHealthStatus.FAILED for issue in result.issues
    )


def test_missing_configuration_file_is_unhealthy(
    tmp_path: Path,
) -> None:
    """Missing configuration should fail the health check."""
    config = create_config(tmp_path / "runtime")
    bootstrap_runtime(config.paths)

    result = check_runtime_health(config)

    assert result.healthy is False
    assert any(issue.code == "configuration_not_found" for issue in result.issues)


def test_missing_runtime_directories_are_reported(
    tmp_path: Path,
) -> None:
    """Every missing runtime directory should be visible."""
    config = create_config(tmp_path / "runtime")
    config.paths.config_file.parent.mkdir(parents=True)
    config.paths.config_file.write_text(
        "schema_version = 1\n",
        encoding="utf-8",
    )

    result = check_runtime_health(config)

    assert result.healthy is False
    missing = tuple(
        issue for issue in result.issues if issue.code == "runtime_path_missing"
    )
    assert missing


def test_runtime_path_occupied_by_file_is_reported(
    tmp_path: Path,
) -> None:
    """A configured directory occupied by a file should fail."""
    config = create_config(tmp_path / "runtime")
    prepare_complete_runtime(config)

    config.paths.proposal_dir.rmdir()
    config.paths.proposal_dir.write_text(
        "conflict",
        encoding="utf-8",
    )

    result = check_runtime_health(config)

    assert result.healthy is False
    assert any(
        issue.code == "runtime_path_not_directory"
        and issue.path == config.paths.proposal_dir
        for issue in result.issues
    )


def test_missing_optional_secret_is_warning(
    tmp_path: Path,
) -> None:
    """A missing optional secret should not make runtime unhealthy."""
    secret_path = tmp_path / "runtime" / "secrets" / "token"
    config = create_config(
        tmp_path / "runtime",
        secret_path=secret_path,
    )
    prepare_complete_runtime(config)

    result = check_runtime_health(config)

    assert result.healthy is True
    assert any(
        issue.code == "secret_file_missing"
        and issue.status is RuntimeHealthStatus.WARNING
        for issue in result.issues
    )


def test_unconfigured_optional_secret_is_warning(
    tmp_path: Path,
) -> None:
    """An unused secret reference should be reported as a warning."""
    config = create_config(tmp_path / "runtime")
    prepare_complete_runtime(config)

    result = check_runtime_health(config)

    assert result.healthy is True
    assert any(
        issue.code == "secret_file_not_configured"
        and issue.status is RuntimeHealthStatus.WARNING
        for issue in result.issues
    )


def test_secret_file_content_is_not_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Health checking should inspect metadata, not secret content."""
    secret_path = tmp_path / "runtime" / "secrets" / "token"
    config = create_config(
        tmp_path / "runtime",
        secret_path=secret_path,
    )
    prepare_complete_runtime(config)
    secret_path.parent.mkdir(parents=True)
    secret_path.write_text("secret", encoding="utf-8")

    def reject_read(*args: object, **kwargs: object) -> str:
        raise AssertionError("Secret content was read.")

    monkeypatch.setattr(Path, "read_text", reject_read)

    result = check_runtime_health(config)

    assert result.healthy is True


def test_health_check_does_not_create_missing_paths(
    tmp_path: Path,
) -> None:
    """Health checks must never bootstrap the runtime."""
    config = create_config(tmp_path / "runtime")

    check_runtime_health(config)

    assert config.paths.state_dir.exists() is False
    assert config.paths.log_dir.exists() is False
    assert config.paths.run_dir.exists() is False


def test_health_check_does_not_create_files(
    tmp_path: Path,
) -> None:
    """Health checks must not create output or secret files."""
    secret_path = tmp_path / "runtime" / "secrets" / "token"
    config = create_config(
        tmp_path / "runtime",
        secret_path=secret_path,
    )
    prepare_complete_runtime(config)

    check_runtime_health(config)

    assert config.paths.audit_file.exists() is False
    assert config.paths.log_file.exists() is False
    assert secret_path.exists() is False


def test_configuration_directory_is_not_a_file(
    tmp_path: Path,
) -> None:
    """A directory used as config_file should fail."""
    config = create_config(tmp_path / "runtime")
    bootstrap_runtime(config.paths)
    config.paths.config_file.mkdir(parents=True)

    result = check_runtime_health(config)

    assert result.healthy is False
    assert any(issue.code == "configuration_not_readable" for issue in result.issues)


def test_health_issue_is_immutable() -> None:
    """Health issues should not permit field reassignment."""
    issue = RuntimeHealthIssue(
        code="runtime_path_missing",
        message="The runtime path is missing.",
        status=RuntimeHealthStatus.FAILED,
        path=Path("/var/lib/lea"),
    )

    with pytest.raises(FrozenInstanceError):
        issue.code = "changed"  # type: ignore[misc]


def test_health_result_is_immutable() -> None:
    """Health results should be immutable."""
    result = RuntimeHealthResult(
        healthy=True,
        issues=(),
    )

    with pytest.raises(FrozenInstanceError):
        result.healthy = False  # type: ignore[misc]


def test_healthy_result_rejects_failed_issue() -> None:
    """A healthy result must not contain failures."""
    issue = RuntimeHealthIssue(
        code="runtime_path_missing",
        message="The runtime path is missing.",
        status=RuntimeHealthStatus.FAILED,
        path=Path("/var/lib/lea"),
    )

    with pytest.raises(
        ValueError,
        match="must not contain failed checks",
    ):
        RuntimeHealthResult(
            healthy=True,
            issues=(issue,),
        )


def test_unhealthy_result_requires_failed_issue() -> None:
    """An unhealthy result must contain a failure."""
    issue = RuntimeHealthIssue(
        code="secret_file_missing",
        message="The secret file is missing.",
        status=RuntimeHealthStatus.WARNING,
        path=Path("/etc/lea/secrets/token"),
    )

    with pytest.raises(
        ValueError,
        match="must contain at least one failed check",
    ):
        RuntimeHealthResult(
            healthy=False,
            issues=(issue,),
        )


def test_health_check_order_is_deterministic(
    tmp_path: Path,
) -> None:
    """Repeated checks should report findings in the same order."""
    config = create_config(tmp_path / "runtime")
    prepare_complete_runtime(config)

    first = check_runtime_health(config)
    second = check_runtime_health(config)

    assert first == second
