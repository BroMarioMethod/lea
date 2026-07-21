"""Canonical runtime path layouts for supported LEA profiles."""

from pathlib import Path

from lea.runtime.contracts import RuntimePaths


def system_runtime_paths() -> RuntimePaths:
    """Return the canonical system-installation runtime layout."""
    return _build_runtime_paths(
        config_file=Path("/etc/lea/lea.toml"),
        state_dir=Path("/var/lib/lea"),
        log_dir=Path("/var/log/lea"),
        run_dir=Path("/run/lea"),
    )


def development_runtime_paths(
    root: Path,
) -> RuntimePaths:
    """Return a canonical development layout below an explicit root."""
    _validate_root(root)

    runtime_root = root / ".lea"

    return _build_runtime_paths(
        config_file=runtime_root / "config" / "lea.toml",
        state_dir=runtime_root / "state",
        log_dir=runtime_root / "log",
        run_dir=runtime_root / "run",
    )


def isolated_test_runtime_paths(
    root: Path,
) -> RuntimePaths:
    """Return a canonical isolated-test layout below an explicit root."""
    _validate_root(root)

    return _build_runtime_paths(
        config_file=root / "config" / "lea.toml",
        state_dir=root / "state",
        log_dir=root / "log",
        run_dir=root / "run",
    )


def _build_runtime_paths(
    *,
    config_file: Path,
    state_dir: Path,
    log_dir: Path,
    run_dir: Path,
) -> RuntimePaths:
    """Construct one canonical runtime layout."""
    audit_dir = state_dir / "audit"

    return RuntimePaths(
        config_file=config_file,
        state_dir=state_dir,
        log_dir=log_dir,
        run_dir=run_dir,
        audit_dir=audit_dir,
        proposal_dir=state_dir / "proposals",
        knowledge_dir=state_dir / "knowledge",
        index_dir=state_dir / "indexes",
        adapter_dir=state_dir / "adapters",
        backup_dir=state_dir / "backups",
        audit_file=audit_dir / "actions-integrity.jsonl",
        log_file=log_dir / "lea.log",
    )


def _validate_root(root: Path) -> None:
    """Validate an explicit development or test layout root."""
    if not isinstance(root, Path):
        raise TypeError("root must be a pathlib.Path value.")

    if not root.is_absolute():
        raise ValueError("root must be an absolute path.")

    if "\x00" in str(root):
        raise ValueError("root must not contain a null byte.")
