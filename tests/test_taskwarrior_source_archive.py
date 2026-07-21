"""Tests for verified Taskwarrior source-archive extraction."""

import hashlib
import io
import tarfile
from pathlib import Path

from lea.installers.taskwarrior import (
    TaskwarriorInstallFailureCode,
    extract_taskwarrior_source_archive,
    remove_taskwarrior_extracted_source,
)


def _write_tar(
    path: Path,
    members: tuple[tuple[tarfile.TarInfo, bytes | None], ...],
) -> str:
    """Write one TAR archive and return its SHA-256 digest."""
    with tarfile.open(path, mode="w:gz") as archive:
        for member, payload in members:
            stream = io.BytesIO(payload) if payload is not None else None
            archive.addfile(member, stream)

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _regular_member(
    name: str,
    payload: bytes,
    *,
    mode: int = 0o644,
) -> tuple[tarfile.TarInfo, bytes]:
    """Return one regular TAR member."""
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    member.mode = mode
    return member, payload


def test_extracts_verified_single_root_archive(
    tmp_path: Path,
) -> None:
    """A verified archive should produce one private source root."""
    archive = tmp_path / "task-3.4.2.tar.gz"
    checksum = _write_tar(
        archive,
        (
            _regular_member(
                "task-3.4.2/CMakeLists.txt",
                b"cmake_minimum_required(VERSION 3.20)\n",
            ),
            _regular_member(
                "task-3.4.2/scripts/build.sh",
                b"#!/bin/sh\n",
                mode=0o755,
            ),
        ),
    )

    result = extract_taskwarrior_source_archive(
        archive,
        expected_sha256=checksum,
        build_directory=tmp_path / "build",
    )

    assert result.issues == ()
    assert result.extracted is not None
    assert result.extracted.source_root.name == "task-3.4.2"
    assert (result.extracted.source_root / "CMakeLists.txt").is_file()
    assert (
        result.extracted.source_root / "scripts" / "build.sh"
    ).stat().st_mode & 0o111


def test_checksum_mismatch_creates_no_extraction(
    tmp_path: Path,
) -> None:
    """Checksum verification must happen before extraction."""
    archive = tmp_path / "task.tar.gz"
    _write_tar(
        archive,
        (_regular_member("task/file.txt", b"content"),),
    )
    build_directory = tmp_path / "build"

    result = extract_taskwarrior_source_archive(
        archive,
        expected_sha256="a" * 64,
        build_directory=build_directory,
    )

    assert result.extracted is None
    assert result.issues[0].code is TaskwarriorInstallFailureCode.CHECKSUM_MISMATCH
    assert not build_directory.exists()


def test_rejects_parent_traversal_and_cleans_temporary_root(
    tmp_path: Path,
) -> None:
    """Traversal members must fail closed and leave no source tree."""
    archive = tmp_path / "task.tar.gz"
    checksum = _write_tar(
        archive,
        (_regular_member("../escape.txt", b"escape"),),
    )
    build_directory = tmp_path / "build"

    result = extract_taskwarrior_source_archive(
        archive,
        expected_sha256=checksum,
        build_directory=build_directory,
    )

    assert result.extracted is None
    assert result.issues[0].code is TaskwarriorInstallFailureCode.ARCHIVE_UNSAFE
    assert tuple(build_directory.iterdir()) == ()
    assert not (tmp_path / "escape.txt").exists()


def test_rejects_absolute_archive_path(
    tmp_path: Path,
) -> None:
    """Absolute archive destinations must be rejected."""
    archive = tmp_path / "task.tar.gz"
    checksum = _write_tar(
        archive,
        (_regular_member("/tmp/escape.txt", b"escape"),),
    )

    result = extract_taskwarrior_source_archive(
        archive,
        expected_sha256=checksum,
        build_directory=tmp_path / "build",
    )

    assert result.extracted is None
    assert result.issues[0].code is TaskwarriorInstallFailureCode.ARCHIVE_UNSAFE


def test_rejects_symbolic_link_member(
    tmp_path: Path,
) -> None:
    """Symbolic links must not enter the extracted source tree."""
    archive = tmp_path / "task.tar.gz"
    link = tarfile.TarInfo("task/link")
    link.type = tarfile.SYMTYPE
    link.linkname = "../../outside"
    checksum = _write_tar(archive, ((link, None),))

    result = extract_taskwarrior_source_archive(
        archive,
        expected_sha256=checksum,
        build_directory=tmp_path / "build",
    )

    assert result.extracted is None
    assert result.issues[0].code is TaskwarriorInstallFailureCode.ARCHIVE_UNSAFE


def test_rejects_hard_link_member(
    tmp_path: Path,
) -> None:
    """Hard links must not enter the extracted source tree."""
    archive = tmp_path / "task.tar.gz"
    link = tarfile.TarInfo("task/link")
    link.type = tarfile.LNKTYPE
    link.linkname = "task/file"
    checksum = _write_tar(archive, ((link, None),))

    result = extract_taskwarrior_source_archive(
        archive,
        expected_sha256=checksum,
        build_directory=tmp_path / "build",
    )

    assert result.extracted is None
    assert result.issues[0].code is TaskwarriorInstallFailureCode.ARCHIVE_UNSAFE


def test_rejects_fifo_member(
    tmp_path: Path,
) -> None:
    """Archive special files must be rejected."""
    archive = tmp_path / "task.tar.gz"
    fifo = tarfile.TarInfo("task/pipe")
    fifo.type = tarfile.FIFOTYPE
    checksum = _write_tar(archive, ((fifo, None),))

    result = extract_taskwarrior_source_archive(
        archive,
        expected_sha256=checksum,
        build_directory=tmp_path / "build",
    )

    assert result.extracted is None
    assert result.issues[0].code is TaskwarriorInstallFailureCode.ARCHIVE_UNSAFE


def test_remove_extracted_source_is_idempotent(
    tmp_path: Path,
) -> None:
    """Installer-managed extracted source cleanup should be repeatable."""
    archive = tmp_path / "task.tar.gz"
    checksum = _write_tar(
        archive,
        (_regular_member("task/file.txt", b"content"),),
    )
    result = extract_taskwarrior_source_archive(
        archive,
        expected_sha256=checksum,
        build_directory=tmp_path / "build",
    )

    assert result.extracted is not None
    extracted = result.extracted

    assert remove_taskwarrior_extracted_source(extracted) == ()
    assert not extracted.extraction_root.exists()
    assert remove_taskwarrior_extracted_source(extracted) == ()
