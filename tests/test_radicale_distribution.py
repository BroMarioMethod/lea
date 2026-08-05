"""Regression tests for the reviewed Radicale distribution boundary."""

import hashlib
from pathlib import Path

from lea.installers.radicale.distribution import (
    RadicaleDistributionRequest,
    install_radicale_distribution,
)


def _request(tmp_path: Path, lock: Path) -> RadicaleDistributionRequest:
    uv = tmp_path / "uv"
    python = tmp_path / "python"
    uv.write_text("uv")
    python.write_text("python")
    uv.chmod(0o755)
    python.chmod(0o755)
    records = tmp_path / "records"
    records.mkdir()
    tools = tmp_path / "tools"
    tools.mkdir()
    return RadicaleDistributionRequest(
        lock,
        hashlib.sha256(lock.read_bytes()).hexdigest(),
        uv,
        python,
        tools / "3.5.4",
        records / "radicale.json",
    )


def test_rejects_unreviewed_radicale_lock(tmp_path: Path) -> None:
    lock = tmp_path / "lock"
    lock.write_text("reviewed")
    request = _request(tmp_path, lock)
    request = RadicaleDistributionRequest(
        request.requirements_lock,
        "0" * 64,
        request.uv_executable,
        request.python_executable,
        request.installation_root,
        request.record_file,
    )
    result = install_radicale_distribution(request)
    assert result.success is False
    assert result.code == "radicale_lock_digest_mismatch"


def test_existing_distribution_requires_matching_record(tmp_path: Path) -> None:
    lock = tmp_path / "lock"
    lock.write_text("reviewed")
    request = _request(tmp_path, lock)
    executable = request.installation_root / ".venv/bin/radicale"
    executable.parent.mkdir(parents=True)
    executable.write_text("binary")
    executable.chmod(0o755)
    result = install_radicale_distribution(request)
    assert result.success is False
    assert result.code == "radicale_distribution_record_mismatch"
