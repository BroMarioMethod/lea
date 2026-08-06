"""Install Radicale from one reviewed hash-pinned requirements lock."""

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RadicaleDistributionRequest:
    """Exact inputs for the independently managed Radicale distribution."""

    requirements_lock: Path
    expected_lock_sha256: str
    uv_executable: Path
    python_executable: Path
    installation_root: Path = Path("/opt/lea-tools/radicale/3.5.4")
    record_file: Path = Path("/var/lib/lea/install/radicale-distribution.json")
    version: str = "3.5.4"


@dataclass(frozen=True, slots=True)
class RadicaleDistributionResult:
    success: bool
    executable: Path | None
    executable_sha256: str | None
    changed: bool
    code: str | None = None


def install_radicale_distribution(
    request: RadicaleDistributionRequest,
) -> RadicaleDistributionResult:
    """Install with uv's hash enforcement and persist supply-chain evidence."""
    lock = request.requirements_lock
    if lock.is_symlink() or not lock.is_file():
        return _failure("radicale_lock_invalid")
    if _sha256(lock) != request.expected_lock_sha256:
        return _failure("radicale_lock_digest_mismatch")
    for path in (request.uv_executable, request.python_executable):
        if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
            return _failure("radicale_installer_executable_invalid")
    root = request.installation_root
    executable = root / ".venv/bin/radicale"
    changed = False
    if executable.exists():
        digest = _sha256(executable)
        if not _record_matches(request, executable, digest):
            return _failure("radicale_distribution_record_mismatch")
        if _run((str(executable), "--version"), expected=request.version) != 0:
            return _failure("radicale_version_mismatch")
        return RadicaleDistributionResult(True, executable, digest, False)
    if not executable.exists():
        if root.exists() or root.is_symlink() or not root.parent.is_dir():
            return _failure("radicale_installation_root_invalid")
        root.mkdir(mode=0o755)
        changed = True
        command: tuple[str, ...] = (
            str(request.uv_executable),
            "venv",
            "--python",
            str(request.python_executable),
            str(root / ".venv"),
        )
        if _run(command) != 0:
            return _failure("radicale_venv_creation_failed")
        command = (
            str(request.uv_executable),
            "pip",
            "sync",
            "--require-hashes",
            "--index-url",
            "https://pypi.org/simple",
            "--python",
            str(root / ".venv/bin/python"),
            str(lock),
        )
        if _run(command) != 0:
            return _failure("radicale_locked_install_failed")
    if (
        executable.is_symlink()
        or not executable.is_file()
        or not os.access(executable, os.X_OK)
    ):
        return _failure("radicale_executable_invalid")
    if _run((str(executable), "--version"), expected=request.version) != 0:
        return _failure("radicale_version_mismatch")
    executable_digest = _sha256(executable)
    record = {
        "schema_version": 1,
        "component": "radicale-distribution",
        "version": request.version,
        "requirements_lock": str(lock),
        "requirements_sha256": request.expected_lock_sha256,
        "installation_root": str(root),
        "executable": str(executable),
        "executable_sha256": executable_digest,
        "installed_at": datetime.now(UTC).isoformat(),
    }
    if not _write_record(request.record_file, record):
        return _failure("radicale_distribution_record_failed")
    return RadicaleDistributionResult(True, executable, executable_digest, changed)


def _record_matches(
    request: RadicaleDistributionRequest, executable: Path, digest: str
) -> bool:
    path = request.record_file
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o007:
        return False
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    expected = {
        "schema_version": 1,
        "component": "radicale-distribution",
        "version": request.version,
        "requirements_lock": str(request.requirements_lock),
        "requirements_sha256": request.expected_lock_sha256,
        "installation_root": str(request.installation_root),
        "executable": str(executable),
        "executable_sha256": digest,
    }
    return all(record.get(key) == value for key, value in expected.items())


def _run(arguments: tuple[str, ...], expected: str | None = None) -> int:
    try:
        result = subprocess.run(
            arguments,
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
            env={
                "HOME": "/var/empty",
                "LANG": "C.UTF-8",
                "PATH": "/usr/bin:/bin",
                "UV_CACHE_DIR": "/var/tmp/lea-uv-cache",
            },
        )
    except (OSError, subprocess.SubprocessError):
        return 1
    if result.returncode != 0 or (
        expected is not None and result.stdout.strip() != expected
    ):
        return 1
    return 0


def _write_record(path: Path, record: dict[str, object]) -> bool:
    if path.parent.is_symlink() or not path.parent.is_dir():
        return False
    data = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o640)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        return True
    except OSError:
        return False
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _failure(code: str) -> RadicaleDistributionResult:
    return RadicaleDistributionResult(False, None, None, False, code)
