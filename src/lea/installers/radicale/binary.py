"""Verification and registration of an exact separately supplied Radicale binary."""

import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class RadicaleBinaryConfig:
    """Pinned evidence required to trust one external Radicale executable."""

    executable: Path
    expected_version: str
    expected_sha256: str
    record_file: Path
    working_directory: Path
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        for name, path in (
            ("executable", self.executable),
            ("record_file", self.record_file),
            ("working_directory", self.working_directory),
        ):
            if not isinstance(path, Path) or not path.is_absolute():
                raise ValueError(f"{name} must be an absolute path.")
        if _VERSION.fullmatch(self.expected_version) is None:
            raise ValueError("expected_version must be a semantic numeric version.")
        if _SHA256.fullmatch(self.expected_sha256) is None:
            raise ValueError("expected_sha256 must be a lowercase SHA-256 digest.")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")


@dataclass(frozen=True, slots=True)
class RadicaleBinaryIssue:
    """One verification or registration problem."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class RadicaleInstallationRecord:
    """Persisted evidence for one verified Radicale executable."""

    schema_version: int
    component: str
    version: str
    executable: str
    sha256: str
    verified_at: str


@dataclass(frozen=True, slots=True)
class RadicaleBinaryResult:
    """Result of verification and atomic installation-record registration."""

    success: bool
    changed: bool
    record: RadicaleInstallationRecord | None
    issues: tuple[RadicaleBinaryIssue, ...]


Clock = Callable[[], datetime]


def verify_and_register_radicale_binary(
    config: RadicaleBinaryConfig,
    *,
    clock: Clock = lambda: datetime.now(UTC),
) -> RadicaleBinaryResult:
    """Verify exact binary evidence and atomically register it without repair."""
    issue = _inspect_path(config.executable, executable=True)
    if issue is not None:
        return _failure(issue)
    issue = _inspect_path(config.working_directory, executable=False, directory=True)
    if issue is not None:
        return _failure(issue)
    try:
        before = _sha256(config.executable)
    except OSError:
        return _failure(
            RadicaleBinaryIssue(
                "radicale_digest_failed",
                "The Radicale executable digest could not be calculated.",
            )
        )
    if before != config.expected_sha256:
        return _failure(
            RadicaleBinaryIssue(
                "radicale_digest_mismatch",
                "The Radicale executable does not match the pinned digest.",
            )
        )
    try:
        completed = subprocess.run(
            (str(config.executable), "--version"),
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            check=False,
            timeout=config.timeout_seconds,
            cwd=config.working_directory,
            env=_environment(),
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return _failure(
            RadicaleBinaryIssue(
                "radicale_version_inspection_failed",
                "The Radicale executable version could not be inspected.",
            )
        )
    if completed.returncode != 0 or completed.stdout.strip() != config.expected_version:
        return _failure(
            RadicaleBinaryIssue(
                "radicale_version_mismatch",
                "The Radicale executable does not match the pinned version.",
            )
        )
    try:
        after = _sha256(config.executable)
    except OSError:
        return _failure(
            RadicaleBinaryIssue(
                "radicale_digest_failed",
                "The Radicale executable digest could not be recalculated.",
            )
        )
    if after != before:
        return _failure(
            RadicaleBinaryIssue(
                "radicale_executable_changed",
                "The Radicale executable changed during verification.",
            )
        )
    timestamp = clock()
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware timestamp.")
    record = RadicaleInstallationRecord(
        schema_version=1,
        component="radicale",
        version=config.expected_version,
        executable=str(config.executable),
        sha256=after,
        verified_at=timestamp.astimezone(UTC).isoformat(),
    )
    return _write_record(config.record_file, record)


def _write_record(
    path: Path, record: RadicaleInstallationRecord
) -> RadicaleBinaryResult:
    document = (
        json.dumps(asdict(record), sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    if path.parent.is_symlink() or not path.parent.is_dir():
        return _failure(
            RadicaleBinaryIssue(
                "radicale_record_parent_invalid",
                "The Radicale installation-record directory is unavailable.",
            )
        )
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            return _failure(
                RadicaleBinaryIssue(
                    "radicale_record_invalid",
                    "The Radicale installation-record path is invalid.",
                )
            )
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            existing = RadicaleInstallationRecord(**raw)
            stable_match = (
                existing.schema_version == record.schema_version
                and existing.component == record.component
                and existing.version == record.version
                and existing.executable == record.executable
                and existing.sha256 == record.sha256
            )
            if stable_match and path.stat().st_mode & 0o777 == 0o640:
                return RadicaleBinaryResult(True, False, existing, ())
        except (OSError, TypeError, json.JSONDecodeError):
            pass
        return _failure(
            RadicaleBinaryIssue(
                "radicale_record_mismatch",
                "The existing Radicale installation record does not match.",
            )
        )
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(name)
        os.fchmod(descriptor, 0o640)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(document)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    except OSError:
        return _failure(
            RadicaleBinaryIssue(
                "radicale_record_write_failed",
                "The Radicale installation record could not be created.",
            )
        )
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
    return RadicaleBinaryResult(True, True, record, ())


def _inspect_path(
    path: Path, *, executable: bool, directory: bool = False
) -> RadicaleBinaryIssue | None:
    valid = path.is_dir() if directory else path.is_file()
    if path.is_symlink() or not valid or (executable and not os.access(path, os.X_OK)):
        return RadicaleBinaryIssue(
            "radicale_binary_path_invalid",
            "A required Radicale verification path is unavailable.",
        )
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _environment() -> Mapping[str, str]:
    return {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
    }


def _failure(issue: RadicaleBinaryIssue) -> RadicaleBinaryResult:
    return RadicaleBinaryResult(False, False, None, (issue,))
