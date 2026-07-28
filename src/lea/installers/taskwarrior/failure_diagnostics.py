"""Preservation of bounded Taskwarrior installation failure evidence."""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from lea.installers.taskwarrior.build_execution import (
    TaskwarriorSourceBuildExecutionResult,
)
from lea.installers.taskwarrior.contracts import TaskwarriorInstallerIssue
from lea.installers.taskwarrior.source_archive import TaskwarriorExtractedSource
from lea.installers.taskwarrior.staging import TaskwarriorStagedBinary


@dataclass(frozen=True, slots=True)
class TaskwarriorFailureDiagnostics:
    """Paths preserved from one failed source installation."""

    root: Path
    extracted_source: Path | None
    staged_binary: Path | None
    summary: Path

    def __post_init__(self) -> None:
        """Validate diagnostic paths."""
        if not self.root.is_absolute():
            raise ValueError("root must be absolute.")

        if not self.summary.is_absolute():
            raise ValueError("summary must be absolute.")

        for path in (self.extracted_source, self.staged_binary):
            if path is not None and not path.is_absolute():
                raise ValueError("Preserved diagnostic paths must be absolute.")


def preserve_taskwarrior_failure_diagnostics(
    *,
    destination_parent: Path,
    extracted: TaskwarriorExtractedSource,
    staged: TaskwarriorStagedBinary | None,
    build: TaskwarriorSourceBuildExecutionResult | None,
    issues: tuple[TaskwarriorInstallerIssue, ...],
) -> TaskwarriorFailureDiagnostics:
    """Move installer-managed failure evidence into persistent storage."""
    if not destination_parent.is_absolute():
        raise ValueError("destination_parent must be absolute.")

    destination_parent.mkdir(
        mode=0o750,
        parents=True,
        exist_ok=True,
    )

    root = Path(
        tempfile.mkdtemp(
            prefix="attempt-",
            dir=destination_parent,
        )
    )
    root.chmod(0o750)

    preserved_source: Path | None = None
    preserved_staged: Path | None = None

    try:
        preserved_source = root / "source-build"
        shutil.move(
            str(extracted.extraction_root),
            str(preserved_source),
        )

        if staged is not None and staged.staging_root.exists():
            preserved_staging_root = root / "staging"
            shutil.move(
                str(staged.staging_root),
                str(preserved_staging_root),
            )
            preserved_staged = preserved_staging_root / "bin" / "task"

        summary = root / "failure.json"
        summary.write_text(
            json.dumps(
                _failure_payload(
                    build=build,
                    issues=issues,
                    extracted_source=preserved_source,
                    staged_binary=preserved_staged,
                ),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        summary.chmod(0o640)

        return TaskwarriorFailureDiagnostics(
            root=root,
            extracted_source=preserved_source,
            staged_binary=preserved_staged,
            summary=summary,
        )
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def _failure_payload(
    *,
    build: TaskwarriorSourceBuildExecutionResult | None,
    issues: tuple[TaskwarriorInstallerIssue, ...],
    extracted_source: Path | None,
    staged_binary: Path | None,
) -> dict[str, object]:
    """Render non-secret machine-readable failure evidence."""
    return {
        "schema_version": 1,
        "component": "taskwarrior",
        "extracted_source": (
            str(extracted_source) if extracted_source is not None else None
        ),
        "staged_binary": (str(staged_binary) if staged_binary is not None else None),
        "issues": [
            {
                "code": issue.code.value,
                "message": issue.message,
                "field": issue.field,
                "path": str(issue.path) if issue.path is not None else None,
            }
            for issue in issues
        ],
        "build": (
            {
                "success": build.success,
                "steps": [
                    {
                        "phase": step.phase,
                        "command": list(step.command),
                        "returncode": step.returncode,
                        "duration_seconds": step.duration_seconds,
                        "timed_out": step.timed_out,
                        "stdout": step.stdout,
                        "stderr": step.stderr,
                    }
                    for step in build.steps
                ],
            }
            if build is not None
            else None
        ),
    }
