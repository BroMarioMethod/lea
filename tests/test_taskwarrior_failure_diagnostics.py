"""Tests for preserved Taskwarrior installation failure evidence."""

import json
import stat
from pathlib import Path

from lea.installers.taskwarrior import (
    TaskwarriorBuildStepResult,
    TaskwarriorInstallerIssue,
    TaskwarriorInstallFailureCode,
    TaskwarriorSourceBuildExecutionResult,
    TaskwarriorStagedBinary,
)
from lea.installers.taskwarrior.failure_diagnostics import (
    preserve_taskwarrior_failure_diagnostics,
)
from lea.installers.taskwarrior.source_archive import (
    TaskwarriorExtractedSource,
)


def _extracted_source(
    tmp_path: Path,
) -> TaskwarriorExtractedSource:
    """Create one installer-managed extracted source tree."""
    extraction_root = tmp_path / "transient" / "extracted"
    source_root = extraction_root / "task-3.4.2"
    source_root.mkdir(parents=True)

    (source_root / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.20)\n",
        encoding="utf-8",
    )
    (extraction_root / "cmake-build").mkdir()
    (extraction_root / "cmake-build" / "failure.log").write_text(
        "compiler failure\n",
        encoding="utf-8",
    )

    return TaskwarriorExtractedSource(
        extraction_root=extraction_root,
        source_root=source_root,
        archive_sha256="a" * 64,
    )


def _staged_binary(
    tmp_path: Path,
) -> TaskwarriorStagedBinary:
    """Create one transient staged executable."""
    staging_root = tmp_path / "transient" / "staging"
    executable = staging_root / "bin" / "task"
    executable.parent.mkdir(parents=True)
    executable.write_text(
        "#!/bin/sh\nexit 127\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

    return TaskwarriorStagedBinary(
        staging_root=staging_root,
        executable=executable,
        sha256="b" * 64,
    )


def _failed_build() -> TaskwarriorSourceBuildExecutionResult:
    """Return one failed build with bounded process evidence."""
    step = TaskwarriorBuildStepResult(
        phase="build",
        command=("cmake", "--build", "/tmp/build"),
        returncode=2,
        stdout="compiler stdout\n",
        stderr="compiler stderr\n",
        duration_seconds=12.5,
        timed_out=False,
    )
    issue = TaskwarriorInstallerIssue(
        code=TaskwarriorInstallFailureCode.BUILD_FAILED,
        message="The Taskwarrior build phase failed.",
        field="build_directory",
        path=Path("/tmp/build"),
    )

    return TaskwarriorSourceBuildExecutionResult(
        success=False,
        installation_prefix=None,
        steps=(step,),
        issues=(issue,),
    )


def test_preserves_source_staging_and_machine_readable_summary(
    tmp_path: Path,
) -> None:
    """Failure preservation should move all managed diagnostic evidence."""
    extracted = _extracted_source(tmp_path)
    staged = _staged_binary(tmp_path)
    build = _failed_build()
    original_extraction_root = extracted.extraction_root
    original_staging_root = staged.staging_root

    result = preserve_taskwarrior_failure_diagnostics(
        destination_parent=tmp_path / "diagnostics",
        extracted=extracted,
        staged=staged,
        build=build,
        issues=build.issues,
    )

    assert result.root.parent == tmp_path / "diagnostics"
    assert result.root.name.startswith("attempt-")
    assert result.root.stat().st_mode & 0o777 == 0o750

    assert not original_extraction_root.exists()
    assert not original_staging_root.exists()

    assert result.extracted_source == result.root / "source-build"
    assert result.extracted_source is not None
    assert (result.extracted_source / "task-3.4.2" / "CMakeLists.txt").is_file()
    assert (result.extracted_source / "cmake-build" / "failure.log").read_text(
        encoding="utf-8"
    ) == "compiler failure\n"

    assert result.staged_binary == result.root / "staging" / "bin" / "task"
    assert result.staged_binary is not None
    assert result.staged_binary.is_file()
    assert result.staged_binary.stat().st_mode & stat.S_IXUSR

    payload = json.loads(result.summary.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["component"] == "taskwarrior"
    assert payload["extracted_source"] == str(result.extracted_source)
    assert payload["staged_binary"] == str(result.staged_binary)
    assert payload["issues"] == [
        {
            "code": "taskwarrior_install_build_failed",
            "field": "build_directory",
            "message": "The Taskwarrior build phase failed.",
            "path": "/tmp/build",
        }
    ]
    assert payload["build"]["success"] is False
    assert payload["build"]["steps"] == [
        {
            "command": ["cmake", "--build", "/tmp/build"],
            "duration_seconds": 12.5,
            "phase": "build",
            "returncode": 2,
            "stderr": "compiler stderr\n",
            "stdout": "compiler stdout\n",
            "timed_out": False,
        }
    ]


def test_preserves_build_failure_without_staged_binary(
    tmp_path: Path,
) -> None:
    """Early build failures should preserve source evidence without staging."""
    extracted = _extracted_source(tmp_path)
    build = _failed_build()

    result = preserve_taskwarrior_failure_diagnostics(
        destination_parent=tmp_path / "diagnostics",
        extracted=extracted,
        staged=None,
        build=build,
        issues=build.issues,
    )

    assert result.extracted_source is not None
    assert result.extracted_source.is_dir()
    assert result.staged_binary is None

    payload = json.loads(result.summary.read_text(encoding="utf-8"))

    assert payload["staged_binary"] is None
    assert payload["build"]["steps"][0]["returncode"] == 2


def test_rejects_relative_diagnostics_parent(
    tmp_path: Path,
) -> None:
    """Diagnostics must never be written through a relative destination."""
    extracted = _extracted_source(tmp_path)

    try:
        preserve_taskwarrior_failure_diagnostics(
            destination_parent=Path("relative"),
            extracted=extracted,
            staged=None,
            build=None,
            issues=(),
        )
    except ValueError as error:
        assert "destination_parent must be absolute" in str(error)
    else:
        raise AssertionError("Expected relative diagnostics destination rejection.")

    assert extracted.extraction_root.exists()
