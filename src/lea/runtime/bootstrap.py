"""Deterministic runtime-directory bootstrap for LEA."""

from pathlib import Path

from lea.runtime.contracts import (
    RuntimeBootstrapResult,
    RuntimePathResult,
    RuntimePaths,
    RuntimePathStatus,
)


def bootstrap_runtime(
    paths: RuntimePaths,
    *,
    dry_run: bool = False,
) -> RuntimeBootstrapResult:
    """Create missing runtime directories when explicitly requested."""
    results: list[RuntimePathResult] = []

    for path in _required_directories(paths):
        result = _bootstrap_directory(
            path,
            dry_run=dry_run,
        )
        results.append(result)

        if result.status in {
            RuntimePathStatus.CONFLICT,
            RuntimePathStatus.FAILED,
        }:
            return RuntimeBootstrapResult(
                success=False,
                dry_run=dry_run,
                paths=tuple(results),
            )

    return RuntimeBootstrapResult(
        success=True,
        dry_run=dry_run,
        paths=tuple(results),
    )


def _required_directories(
    paths: RuntimePaths,
) -> tuple[Path, ...]:
    """Return required runtime directories in deterministic order."""
    candidates = (
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

    unique_paths: list[Path] = []
    seen: set[Path] = set()

    for path in candidates:
        if path in seen:
            continue

        seen.add(path)
        unique_paths.append(path)

    return tuple(unique_paths)


def _bootstrap_directory(
    path: Path,
    *,
    dry_run: bool,
) -> RuntimePathResult:
    """Inspect or create one required runtime directory."""
    if path.exists():
        if path.is_dir():
            return RuntimePathResult(
                path=path,
                status=RuntimePathStatus.ALREADY_EXISTS,
                message="Runtime directory already exists.",
            )

        return RuntimePathResult(
            path=path,
            status=RuntimePathStatus.CONFLICT,
            message=("Runtime path exists but is not a directory."),
        )

    if dry_run:
        return RuntimePathResult(
            path=path,
            status=RuntimePathStatus.WOULD_CREATE,
            message="Runtime directory would be created.",
        )

    try:
        path.mkdir(
            parents=True,
            exist_ok=False,
        )
    except FileExistsError:
        if path.is_dir():
            return RuntimePathResult(
                path=path,
                status=RuntimePathStatus.ALREADY_EXISTS,
                message="Runtime directory already exists.",
            )

        return RuntimePathResult(
            path=path,
            status=RuntimePathStatus.CONFLICT,
            message=("Runtime path exists but is not a directory."),
        )
    except OSError:
        return RuntimePathResult(
            path=path,
            status=RuntimePathStatus.FAILED,
            message="Runtime directory could not be created.",
        )

    return RuntimePathResult(
        path=path,
        status=RuntimePathStatus.CREATED,
        message="Runtime directory was created.",
    )
