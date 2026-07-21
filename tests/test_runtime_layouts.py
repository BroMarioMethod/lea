"""Tests for canonical LEA runtime profile layouts."""

from collections.abc import Callable
from pathlib import Path

import pytest

from lea.runtime import (
    RuntimePaths,
    development_runtime_paths,
    isolated_test_runtime_paths,
    system_runtime_paths,
)


def assert_common_relationships(
    *,
    state_dir: Path,
    log_dir: Path,
    paths: RuntimePaths,
) -> None:
    """Assert canonical relationships shared by all layouts."""
    assert paths.audit_dir == state_dir / "audit"
    assert paths.proposal_dir == state_dir / "proposals"
    assert paths.knowledge_dir == state_dir / "knowledge"
    assert paths.index_dir == state_dir / "indexes"
    assert paths.adapter_dir == state_dir / "adapters"
    assert paths.backup_dir == state_dir / "backups"
    assert paths.audit_file == state_dir / "audit" / "actions-integrity.jsonl"
    assert paths.log_file == log_dir / "lea.log"


def test_system_layout_uses_canonical_linux_paths() -> None:
    """System installations should use stable Linux locations."""
    paths = system_runtime_paths()

    assert paths.config_file == Path("/etc/lea/lea.toml")
    assert paths.state_dir == Path("/var/lib/lea")
    assert paths.log_dir == Path("/var/log/lea")
    assert paths.run_dir == Path("/run/lea")

    assert_common_relationships(
        state_dir=Path("/var/lib/lea"),
        log_dir=Path("/var/log/lea"),
        paths=paths,
    )


def test_development_layout_is_below_explicit_root(
    tmp_path: Path,
) -> None:
    """Development state should remain below its chosen root."""
    root = tmp_path / "workspace"

    paths = development_runtime_paths(root)

    runtime_root = root / ".lea"

    assert paths.config_file == (runtime_root / "config" / "lea.toml")
    assert paths.state_dir == runtime_root / "state"
    assert paths.log_dir == runtime_root / "log"
    assert paths.run_dir == runtime_root / "run"

    assert_common_relationships(
        state_dir=runtime_root / "state",
        log_dir=runtime_root / "log",
        paths=paths,
    )


def test_test_layout_is_below_explicit_root(
    tmp_path: Path,
) -> None:
    """Test state should be isolated below its supplied root."""
    root = tmp_path / "test-runtime"

    paths = isolated_test_runtime_paths(root)

    assert paths.config_file == root / "config" / "lea.toml"
    assert paths.state_dir == root / "state"
    assert paths.log_dir == root / "log"
    assert paths.run_dir == root / "run"

    assert_common_relationships(
        state_dir=root / "state",
        log_dir=root / "log",
        paths=paths,
    )


@pytest.mark.parametrize(
    "builder",
    [
        development_runtime_paths,
        isolated_test_runtime_paths,
    ],
)
def test_explicit_root_must_be_absolute(
    builder: Callable[[Path], object],
) -> None:
    """Profile constructors must not depend on the current directory."""
    with pytest.raises(
        ValueError,
        match="root must be an absolute path",
    ):
        builder(Path("relative/runtime"))


@pytest.mark.parametrize(
    "builder",
    [
        development_runtime_paths,
        isolated_test_runtime_paths,
    ],
)
def test_root_must_be_path(
    builder: Callable[[Path], object],
) -> None:
    """Profile constructors should reject untyped path values."""
    with pytest.raises(
        TypeError,
        match=r"root must be a pathlib\.Path",
    ):
        builder("/tmp/lea")  # type: ignore[arg-type]


def test_development_layout_does_not_create_paths(
    tmp_path: Path,
) -> None:
    """Constructing paths must not mutate the filesystem."""
    root = tmp_path / "workspace"

    development_runtime_paths(root)

    assert root.exists() is False


def test_test_layout_does_not_create_paths(
    tmp_path: Path,
) -> None:
    """Constructing test paths must not create their root."""
    root = tmp_path / "test-runtime"

    isolated_test_runtime_paths(root)

    assert root.exists() is False


def test_development_layout_is_deterministic(
    tmp_path: Path,
) -> None:
    """The same root should always produce the same layout."""
    root = tmp_path / "workspace"

    first = development_runtime_paths(root)
    second = development_runtime_paths(root)

    assert first == second


def test_test_layout_is_deterministic(
    tmp_path: Path,
) -> None:
    """The same test root should always produce the same layout."""
    root = tmp_path / "test-runtime"

    first = isolated_test_runtime_paths(root)
    second = isolated_test_runtime_paths(root)

    assert first == second


def test_different_development_roots_are_isolated(
    tmp_path: Path,
) -> None:
    """Separate workspaces should not share runtime state."""
    first = development_runtime_paths(tmp_path / "first")
    second = development_runtime_paths(tmp_path / "second")

    assert first.state_dir != second.state_dir
    assert first.log_dir != second.log_dir
    assert first.run_dir != second.run_dir


def test_different_test_roots_are_isolated(
    tmp_path: Path,
) -> None:
    """Separate test runs should not share runtime state."""
    first = isolated_test_runtime_paths(tmp_path / "first")
    second = isolated_test_runtime_paths(tmp_path / "second")

    assert first.state_dir != second.state_dir
    assert first.log_dir != second.log_dir
    assert first.run_dir != second.run_dir


def test_layout_is_independent_of_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing directory must not affect an explicit layout root."""
    root = tmp_path / "workspace"
    other_directory = tmp_path / "other"
    other_directory.mkdir()

    before = development_runtime_paths(root)

    monkeypatch.chdir(other_directory)

    after = development_runtime_paths(root)

    assert after == before
