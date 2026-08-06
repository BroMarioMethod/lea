"""Fail-closed provisioning of Radicale runtime directories and configuration."""

import os
import tempfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from lea.installers.radicale.configuration import render_radicale_configuration
from lea.installers.radicale.contracts import RadicaleServerConfig

OwnershipApplier = Callable[[Path, str, str], bool]


@dataclass(frozen=True, slots=True)
class RadicaleProvisionIssue:
    """One non-secret runtime provisioning problem."""

    code: str
    message: str
    path: Path


@dataclass(frozen=True, slots=True)
class RadicaleProvisionResult:
    """Result of provisioning non-service Radicale runtime state."""

    success: bool
    changed_paths: tuple[Path, ...]
    issues: tuple[RadicaleProvisionIssue, ...]


def provision_radicale_runtime(
    config: RadicaleServerConfig,
    *,
    owner: str = "lea",
    group: str = "lea",
    apply_ownership: OwnershipApplier | None = None,
) -> RadicaleProvisionResult:
    """Provision exact runtime state without starting or enabling a service."""
    if not isinstance(config, RadicaleServerConfig):
        raise TypeError("config must be a RadicaleServerConfig value.")
    changed: list[Path] = []
    layout = config.layout
    policies = (
        (layout.configuration_directory, 0o750),
        (layout.secrets_directory, 0o700),
        (layout.storage_directory, 0o750),
    )
    for path, mode in policies:
        issue, directory_changed = _provision_directory(path, mode)
        if issue is not None:
            return RadicaleProvisionResult(False, tuple(changed), (issue,))
        if directory_changed:
            changed.append(path)
        if apply_ownership is not None:
            try:
                if apply_ownership(path, owner, group) and path not in changed:
                    changed.append(path)
            except (KeyError, OSError):
                return _failure(
                    changed,
                    "radicale_ownership_failed",
                    "Radicale runtime ownership could not be applied.",
                    path,
                )
    contents = render_radicale_configuration(config).encode("utf-8")
    file_result = _install_exact_file(layout.configuration_file, contents, 0o640)
    if isinstance(file_result, RadicaleProvisionIssue):
        return RadicaleProvisionResult(False, tuple(changed), (file_result,))
    if file_result:
        changed.append(layout.configuration_file)
    if apply_ownership is not None:
        try:
            if (
                apply_ownership(layout.configuration_file, owner, group)
                and layout.configuration_file not in changed
            ):
                changed.append(layout.configuration_file)
        except (KeyError, OSError):
            return _failure(
                changed,
                "radicale_ownership_failed",
                "Radicale configuration ownership could not be applied.",
                layout.configuration_file,
            )
    return RadicaleProvisionResult(True, tuple(changed), ())


def _provision_directory(
    path: Path, mode: int
) -> tuple[RadicaleProvisionIssue | None, bool]:
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir():
        return (
            RadicaleProvisionIssue(
                "radicale_parent_invalid",
                (
                    "A required Radicale parent must be an existing "
                    "non-symbolic directory."
                ),
                parent,
            ),
            False,
        )
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        return (
            RadicaleProvisionIssue(
                "radicale_directory_invalid",
                "A Radicale runtime path is not a non-symbolic directory.",
                path,
            ),
            False,
        )
    existed = path.exists()
    try:
        path.mkdir(mode=mode, parents=False, exist_ok=True)
        current_mode = path.stat().st_mode & 0o777
        if current_mode != mode:
            if existed:
                return (
                    RadicaleProvisionIssue(
                        "radicale_directory_mode_mismatch",
                        "An existing Radicale directory has unexpected permissions.",
                        path,
                    ),
                    False,
                )
            path.chmod(mode)
    except OSError:
        return (
            RadicaleProvisionIssue(
                "radicale_directory_write_failed",
                "A Radicale runtime directory could not be provisioned.",
                path,
            ),
            False,
        )
    return None, not existed


def _install_exact_file(
    path: Path, contents: bytes, mode: int
) -> bool | RadicaleProvisionIssue:
    if path.is_symlink() or path.exists():
        if path.is_symlink() or not path.is_file():
            return RadicaleProvisionIssue(
                "radicale_configuration_invalid",
                "The Radicale configuration path is not a regular file.",
                path,
            )
        try:
            stat = path.stat()
            actual = path.read_bytes()
        except OSError:
            actual = b""
            stat = None
        if actual != contents or stat is None or stat.st_mode & 0o777 != mode:
            return RadicaleProvisionIssue(
                "radicale_configuration_mismatch",
                "Existing Radicale configuration does not match requested state.",
                path,
            )
        return False
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(name)
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        _fsync_directory(path.parent)
    except OSError:
        return RadicaleProvisionIssue(
            "radicale_configuration_write_failed",
            "The Radicale configuration file could not be created.",
            path,
        )
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
    return True


def _failure(
    changed: list[Path], code: str, message: str, path: Path
) -> RadicaleProvisionResult:
    return RadicaleProvisionResult(
        False, tuple(changed), (RadicaleProvisionIssue(code, message, path),)
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
