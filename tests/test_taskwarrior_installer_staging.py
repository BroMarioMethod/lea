"""Tests for safe Taskwarrior binary staging."""

import hashlib
from pathlib import Path

import pytest

from lea.installers.taskwarrior import (
    TaskwarriorInstallFailureCode,
    TaskwarriorStagedBinary,
    remove_taskwarrior_staging,
    stage_taskwarrior_binary,
)


def make_source(tmp_path: Path) -> tuple[Path, str]:
    """Create one deterministic Taskwarrior test binary."""
    source = tmp_path / "source-task"
    source.write_bytes(b"taskwarrior-binary")
    checksum = hashlib.sha256(b"taskwarrior-binary").hexdigest()
    return source, checksum


def test_stage_binary_copies_verified_source(
    tmp_path: Path,
) -> None:
    """A verified binary should be copied into private staging."""
    source, checksum = make_source(tmp_path)

    result = stage_taskwarrior_binary(
        source,
        expected_sha256=checksum,
        staging_parent=tmp_path / "staging",
    )

    assert result.issues == ()
    assert result.staged is not None
    assert result.staged.executable.read_bytes() == source.read_bytes()
    assert result.staged.sha256 == checksum
    assert result.staged.executable.name == "task"
    assert result.staged.executable.parent.name == "bin"
    assert result.staged.executable.stat().st_mode & 0o777 == 0o750
    assert result.staged.staging_root.stat().st_mode & 0o777 == 0o750


def test_stage_binary_rejects_checksum_mismatch(
    tmp_path: Path,
) -> None:
    """A source checksum mismatch should prevent staging."""
    source, _ = make_source(tmp_path)

    result = stage_taskwarrior_binary(
        source,
        expected_sha256="0" * 64,
        staging_parent=tmp_path / "staging",
    )

    assert result.staged is None
    assert len(result.issues) == 1
    assert result.issues[0].code is TaskwarriorInstallFailureCode.CHECKSUM_MISMATCH
    assert not (tmp_path / "staging").exists()


def test_stage_binary_rejects_missing_source(
    tmp_path: Path,
) -> None:
    """A missing source should return a structured issue."""
    source = tmp_path / "missing"

    result = stage_taskwarrior_binary(
        source,
        expected_sha256="0" * 64,
        staging_parent=tmp_path / "staging",
    )

    assert result.staged is None
    assert result.issues[0].code is TaskwarriorInstallFailureCode.ARTEFACT_MISSING


def test_stage_binary_rejects_relative_source(
    tmp_path: Path,
) -> None:
    """Staging should reject ambiguous source paths."""
    result = stage_taskwarrior_binary(
        Path("task"),
        expected_sha256="0" * 64,
        staging_parent=tmp_path / "staging",
    )

    assert result.staged is None
    assert result.issues[0].code is TaskwarriorInstallFailureCode.INVALID_ARGUMENT


def test_remove_staging_deletes_only_staging_root(
    tmp_path: Path,
) -> None:
    """Explicit staging cleanup should remove the staged directory."""
    source, checksum = make_source(tmp_path)
    unrelated = tmp_path / "unrelated"
    unrelated.write_text("preserve", encoding="utf-8")

    result = stage_taskwarrior_binary(
        source,
        expected_sha256=checksum,
        staging_parent=tmp_path / "staging",
    )
    assert result.staged is not None

    staging_root = result.staged.staging_root

    assert remove_taskwarrior_staging(result.staged) == ()
    assert not staging_root.exists()
    assert unrelated.read_text(encoding="utf-8") == "preserve"


def test_remove_missing_staging_is_idempotent(
    tmp_path: Path,
) -> None:
    """Repeated staging cleanup should be safe."""
    staged = TaskwarriorStagedBinary(
        staging_root=tmp_path / "missing-stage",
        executable=tmp_path / "missing-stage" / "bin" / "task",
        sha256="a" * 64,
    )

    assert remove_taskwarrior_staging(staged) == ()
    assert remove_taskwarrior_staging(staged) == ()


def test_staged_contract_rejects_executable_outside_bin(
    tmp_path: Path,
) -> None:
    """The staged executable must remain within its staging root."""
    with pytest.raises(
        ValueError,
        match="inside the staging bin directory",
    ):
        TaskwarriorStagedBinary(
            staging_root=tmp_path / "stage",
            executable=tmp_path / "outside-task",
            sha256="a" * 64,
        )
