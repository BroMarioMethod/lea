"""Tests for deterministic LEA runtime bootstrap."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from lea.runtime import (
    RuntimeBootstrapResult,
    RuntimePathResult,
    RuntimePaths,
    RuntimePathStatus,
    bootstrap_runtime,
)


def create_paths(root: Path) -> RuntimePaths:
    """Create one deterministic test runtime layout."""
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


def expected_directories(
    paths: RuntimePaths,
) -> tuple[Path, ...]:
    """Return the expected deterministic bootstrap order."""
    return (
        paths.state_dir,
        paths.log_dir,
        paths.run_dir,
        paths.audit_dir,
        paths.proposal_dir,
        paths.knowledge_dir,
        paths.index_dir,
        paths.adapter_dir,
        paths.backup_dir,
    )


def test_dry_run_reports_missing_directories(
    tmp_path: Path,
) -> None:
    """Dry-run mode should report without creating anything."""
    paths = create_paths(tmp_path / "runtime")

    result = bootstrap_runtime(
        paths,
        dry_run=True,
    )

    assert result.success is True
    assert result.dry_run is True
    assert tuple(item.path for item in result.paths) == (expected_directories(paths))
    assert all(item.status is RuntimePathStatus.WOULD_CREATE for item in result.paths)
    assert paths.state_dir.exists() is False


def test_bootstrap_creates_all_runtime_directories(
    tmp_path: Path,
) -> None:
    """Explicit bootstrap should create every required directory."""
    paths = create_paths(tmp_path / "runtime")

    result = bootstrap_runtime(paths)

    assert result.success is True
    assert result.dry_run is False
    assert all(item.status is RuntimePathStatus.CREATED for item in result.paths)
    assert all(path.is_dir() for path in expected_directories(paths))


def test_bootstrap_is_idempotent(
    tmp_path: Path,
) -> None:
    """A second bootstrap should preserve existing directories."""
    paths = create_paths(tmp_path / "runtime")

    first = bootstrap_runtime(paths)
    second = bootstrap_runtime(paths)

    assert first.success is True
    assert second.success is True
    assert all(item.status is RuntimePathStatus.ALREADY_EXISTS for item in second.paths)


def test_existing_parent_and_missing_children(
    tmp_path: Path,
) -> None:
    """Existing parent directories should be preserved."""
    paths = create_paths(tmp_path / "runtime")
    paths.state_dir.mkdir(parents=True)

    result = bootstrap_runtime(paths)

    assert result.success is True
    assert result.paths[0].status is (RuntimePathStatus.ALREADY_EXISTS)
    assert paths.audit_dir.is_dir()
    assert paths.proposal_dir.is_dir()


def test_conflicting_file_is_rejected(
    tmp_path: Path,
) -> None:
    """A required directory occupied by a file must fail closed."""
    paths = create_paths(tmp_path / "runtime")
    paths.state_dir.parent.mkdir(parents=True)
    paths.state_dir.write_text(
        "conflict",
        encoding="utf-8",
    )

    result = bootstrap_runtime(paths)

    assert result.success is False
    assert result.paths[-1].path == paths.state_dir
    assert result.paths[-1].status is RuntimePathStatus.CONFLICT
    assert paths.audit_dir.exists() is False


def test_bootstrap_stops_after_first_failure(
    tmp_path: Path,
) -> None:
    """Later paths must not be created after a conflict."""
    paths = create_paths(tmp_path / "runtime")
    paths.log_dir.parent.mkdir(parents=True)
    paths.log_dir.write_text(
        "conflict",
        encoding="utf-8",
    )

    result = bootstrap_runtime(paths)

    assert result.success is False
    assert paths.state_dir.is_dir()
    assert result.paths[-1].path == paths.log_dir
    assert paths.run_dir.exists() is False


def test_dry_run_detects_conflicting_file(
    tmp_path: Path,
) -> None:
    """Dry-run mode should still detect existing conflicts."""
    paths = create_paths(tmp_path / "runtime")
    paths.state_dir.parent.mkdir(parents=True)
    paths.state_dir.write_text(
        "conflict",
        encoding="utf-8",
    )

    result = bootstrap_runtime(
        paths,
        dry_run=True,
    )

    assert result.success is False
    assert result.paths[0].status is RuntimePathStatus.CONFLICT


def test_bootstrap_does_not_create_configuration_file(
    tmp_path: Path,
) -> None:
    """Bootstrap should create directories but not configuration."""
    paths = create_paths(tmp_path / "runtime")

    bootstrap_runtime(paths)

    assert paths.config_file.exists() is False


def test_bootstrap_does_not_create_audit_file(
    tmp_path: Path,
) -> None:
    """Bootstrap should not create the audit data file."""
    paths = create_paths(tmp_path / "runtime")

    bootstrap_runtime(paths)

    assert paths.audit_file.exists() is False
    assert paths.audit_dir.is_dir()


def test_bootstrap_does_not_create_log_file(
    tmp_path: Path,
) -> None:
    """Bootstrap should not create the configured log file."""
    paths = create_paths(tmp_path / "runtime")

    bootstrap_runtime(paths)

    assert paths.log_file.exists() is False
    assert paths.log_dir.is_dir()


def test_path_result_is_immutable() -> None:
    """Individual bootstrap path results should be immutable."""
    result = RuntimePathResult(
        path=Path("/var/lib/lea"),
        status=RuntimePathStatus.CREATED,
        message="Runtime directory was created.",
    )

    with pytest.raises(FrozenInstanceError):
        result.message = "Changed"  # type: ignore[misc]


def test_bootstrap_result_is_immutable() -> None:
    """The complete bootstrap result should be immutable."""
    result = RuntimeBootstrapResult(
        success=True,
        dry_run=True,
        paths=(),
    )

    with pytest.raises(FrozenInstanceError):
        result.success = False  # type: ignore[misc]


def test_success_result_rejects_conflict() -> None:
    """Successful results must not contain conflicting paths."""
    path_result = RuntimePathResult(
        path=Path("/var/lib/lea"),
        status=RuntimePathStatus.CONFLICT,
        message="Runtime path conflicts.",
    )

    with pytest.raises(
        ValueError,
        match="must not contain conflicting or failed",
    ):
        RuntimeBootstrapResult(
            success=True,
            dry_run=False,
            paths=(path_result,),
        )


def test_failed_result_requires_failure_path() -> None:
    """Failed results must identify a conflict or creation failure."""
    path_result = RuntimePathResult(
        path=Path("/var/lib/lea"),
        status=RuntimePathStatus.CREATED,
        message="Runtime directory was created.",
    )

    with pytest.raises(
        ValueError,
        match="must contain at least one",
    ):
        RuntimeBootstrapResult(
            success=False,
            dry_run=False,
            paths=(path_result,),
        )


def test_blank_path_result_message_is_rejected() -> None:
    """Bootstrap path messages must contain useful text."""
    with pytest.raises(
        ValueError,
        match="message must be non-empty",
    ):
        RuntimePathResult(
            path=Path("/var/lib/lea"),
            status=RuntimePathStatus.CREATED,
            message="   ",
        )


def test_bootstrap_result_order_is_deterministic(
    tmp_path: Path,
) -> None:
    """Repeated dry runs should report paths in the same order."""
    paths = create_paths(tmp_path / "runtime")

    first = bootstrap_runtime(paths, dry_run=True)
    second = bootstrap_runtime(paths, dry_run=True)

    assert first.paths == second.paths
