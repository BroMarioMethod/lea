"""Tests for exact Radicale binary verification and registration."""

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path

from lea.installers.radicale import (
    RadicaleBinaryConfig,
    verify_and_register_radicale_binary,
)


def _binary(tmp_path: Path, *, version: str = "3.5.4") -> Path:
    executable = tmp_path / "bin" / "radicale"
    executable.parent.mkdir()
    executable.write_text(f"#!/bin/sh\nprintf '%s\\n' '{version}'\n", encoding="utf-8")
    os.chmod(executable, 0o750)
    return executable


def _config(
    tmp_path: Path, executable: Path, *, digest: str | None = None
) -> RadicaleBinaryConfig:
    records = tmp_path / "records"
    records.mkdir(exist_ok=True)
    return RadicaleBinaryConfig(
        executable=executable,
        expected_version="3.5.4",
        expected_sha256=digest or hashlib.sha256(executable.read_bytes()).hexdigest(),
        record_file=records / "radicale.json",
        working_directory=tmp_path,
    )


def test_exact_binary_is_verified_and_registered_idempotently(tmp_path: Path) -> None:
    executable = _binary(tmp_path)
    config = _config(tmp_path, executable)

    created = verify_and_register_radicale_binary(
        config, clock=lambda: datetime(2026, 8, 4, tzinfo=UTC)
    )
    repeated = verify_and_register_radicale_binary(
        config, clock=lambda: datetime(2026, 8, 5, tzinfo=UTC)
    )

    assert created.success is True
    assert created.changed is True
    assert repeated.success is True
    assert repeated.changed is False
    assert repeated.record == created.record
    assert config.record_file.stat().st_mode & 0o777 == 0o640
    assert created.record is not None
    assert created.record.executable == str(executable)
    assert created.record.sha256 == config.expected_sha256


def test_digest_mismatch_fails_before_executable_invocation(tmp_path: Path) -> None:
    executable = _binary(tmp_path)
    config = _config(tmp_path, executable, digest="0" * 64)

    result = verify_and_register_radicale_binary(config)

    assert result.success is False
    assert result.issues[0].code == "radicale_digest_mismatch"
    assert not config.record_file.exists()


def test_version_mismatch_does_not_create_record(tmp_path: Path) -> None:
    executable = _binary(tmp_path, version="3.5.3")
    config = _config(tmp_path, executable)

    result = verify_and_register_radicale_binary(config)

    assert result.success is False
    assert result.issues[0].code == "radicale_version_mismatch"
    assert not config.record_file.exists()


def test_symlinked_executable_is_rejected(tmp_path: Path) -> None:
    target = _binary(tmp_path)
    executable = tmp_path / "radicale-link"
    executable.symlink_to(target)
    config = _config(
        tmp_path, executable, digest=hashlib.sha256(target.read_bytes()).hexdigest()
    )

    result = verify_and_register_radicale_binary(config)

    assert result.success is False
    assert result.issues[0].code == "radicale_binary_path_invalid"
