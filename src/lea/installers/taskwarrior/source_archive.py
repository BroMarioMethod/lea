"""Verified and safe Taskwarrior source-archive extraction."""

import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from lea.installers.taskwarrior.contracts import (
    TaskwarriorInstallerIssue,
    TaskwarriorInstallFailureCode,
)
from lea.installers.taskwarrior.preflight import calculate_sha256
from lea.installers.taskwarrior.validation import is_valid_sha256


@dataclass(frozen=True, slots=True)
class TaskwarriorExtractedSource:
    """One verified Taskwarrior source tree."""

    extraction_root: Path
    source_root: Path
    archive_sha256: str

    def __post_init__(self) -> None:
        """Validate extracted-source fields."""
        for field_name, path in (
            ("extraction_root", self.extraction_root),
            ("source_root", self.source_root),
        ):
            if not isinstance(path, Path):
                raise TypeError(f"{field_name} must be a pathlib.Path value.")
            if not path.is_absolute():
                raise ValueError(f"{field_name} must be an absolute path.")

        try:
            self.source_root.relative_to(self.extraction_root)
        except ValueError as error:
            raise ValueError("source_root must be within extraction_root.") from error

        if not is_valid_sha256(self.archive_sha256):
            raise ValueError("archive_sha256 must be lower-case SHA-256 text.")


@dataclass(frozen=True, slots=True)
class TaskwarriorSourceExtractionResult:
    """Result of verifying and extracting one source archive."""

    extracted: TaskwarriorExtractedSource | None
    issues: tuple[TaskwarriorInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate result consistency."""
        if self.extracted is not None:
            if self.issues:
                raise ValueError("A successful extraction must not contain issues.")
            return

        if not self.issues:
            raise ValueError("A failed extraction must contain at least one issue.")


def extract_taskwarrior_source_archive(
    source_archive: Path,
    *,
    expected_sha256: str,
    build_directory: Path,
) -> TaskwarriorSourceExtractionResult:
    """Verify and safely extract one pinned Taskwarrior TAR archive."""
    _validate_arguments(
        source_archive=source_archive,
        expected_sha256=expected_sha256,
        build_directory=build_directory,
    )

    if not source_archive.exists():
        return _failure(
            code=TaskwarriorInstallFailureCode.ARTEFACT_MISSING,
            message="The Taskwarrior source archive does not exist.",
            field="source_archive",
            path=source_archive,
        )

    if not source_archive.is_file():
        return _failure(
            code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
            message=("The Taskwarrior source archive is not a regular file."),
            field="source_archive",
            path=source_archive,
        )

    try:
        actual_sha256 = calculate_sha256(source_archive)
    except OSError as error:
        return _failure(
            code=TaskwarriorInstallFailureCode.PERMISSION_DENIED,
            message=(
                "The Taskwarrior source archive could not be read: "
                f"{error.strerror or type(error).__name__}."
            ),
            field="source_archive",
            path=source_archive,
        )

    if actual_sha256 != expected_sha256:
        return _failure(
            code=TaskwarriorInstallFailureCode.CHECKSUM_MISMATCH,
            message=(
                "The Taskwarrior source archive checksum does not match "
                "the pinned SHA-256 value."
            ),
            field="expected_sha256",
            path=source_archive,
        )

    try:
        build_directory.mkdir(
            mode=0o750,
            parents=True,
            exist_ok=True,
        )
    except OSError as error:
        return _failure(
            code=TaskwarriorInstallFailureCode.PERMISSION_DENIED,
            message=(
                "The Taskwarrior build directory could not be created: "
                f"{error.strerror or type(error).__name__}."
            ),
            field="build_directory",
            path=build_directory,
        )

    if build_directory.is_symlink() or not build_directory.is_dir():
        return _failure(
            code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
            message=("The Taskwarrior build directory must be a real directory."),
            field="build_directory",
            path=build_directory,
        )

    extraction_root = Path(
        tempfile.mkdtemp(
            prefix=".taskwarrior-source-",
            dir=build_directory,
        )
    )
    extraction_root.chmod(0o750)

    try:
        source_root = _extract_tar_safely(
            source_archive,
            extraction_root,
        )
    except (OSError, tarfile.TarError, ValueError) as error:
        shutil.rmtree(extraction_root, ignore_errors=True)
        return _failure(
            code=TaskwarriorInstallFailureCode.ARCHIVE_UNSAFE,
            message=(f"The Taskwarrior source archive was rejected: {error}."),
            field="source_archive",
            path=source_archive,
        )

    return TaskwarriorSourceExtractionResult(
        extracted=TaskwarriorExtractedSource(
            extraction_root=extraction_root,
            source_root=source_root,
            archive_sha256=actual_sha256,
        ),
        issues=(),
    )


def remove_taskwarrior_extracted_source(
    extracted: TaskwarriorExtractedSource,
) -> tuple[TaskwarriorInstallerIssue, ...]:
    """Remove one installer-managed extracted source tree."""
    if not isinstance(extracted, TaskwarriorExtractedSource):
        raise TypeError("extracted must be a TaskwarriorExtractedSource value.")

    try:
        shutil.rmtree(extracted.extraction_root)
    except FileNotFoundError:
        return ()
    except OSError as error:
        return (
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.BUILD_FAILED,
                message=(
                    "The extracted Taskwarrior source tree could not be "
                    f"removed: {error.strerror or type(error).__name__}."
                ),
                field="build_directory",
                path=extracted.extraction_root,
            ),
        )

    return ()


def _extract_tar_safely(
    source_archive: Path,
    extraction_root: Path,
) -> Path:
    """Extract regular TAR members without following archive links."""
    top_level_names: set[str] = set()
    extracted_any = False

    with tarfile.open(source_archive, mode="r:*") as archive:
        members = archive.getmembers()

        if not members:
            raise ValueError("the archive is empty")

        for member in members:
            relative = _safe_member_path(member)
            destination = extraction_root.joinpath(*relative.parts)
            _assert_within_root(
                destination=destination,
                extraction_root=extraction_root,
            )

            top_level_names.add(relative.parts[0])

            if member.isdir():
                destination.mkdir(
                    mode=0o750,
                    parents=True,
                    exist_ok=True,
                )
                destination.chmod(0o750)
                extracted_any = True
                continue

            if not member.isfile():
                raise ValueError(f"unsupported archive member type: {member.name}")

            destination.parent.mkdir(
                mode=0o750,
                parents=True,
                exist_ok=True,
            )

            if destination.exists() or destination.is_symlink():
                raise ValueError(f"duplicate archive destination: {member.name}")

            stream = archive.extractfile(member)

            if stream is None:
                raise ValueError(
                    f"archive member has no readable payload: {member.name}"
                )

            with stream, destination.open("xb") as output:
                shutil.copyfileobj(stream, output)

            destination.chmod(0o750 if member.mode & 0o111 else 0o640)
            extracted_any = True

    if not extracted_any:
        raise ValueError("the archive contains no extractable members")

    if len(top_level_names) == 1:
        candidate = extraction_root / next(iter(top_level_names))

        if candidate.is_dir() and not candidate.is_symlink():
            return candidate

    return extraction_root


def _safe_member_path(
    member: tarfile.TarInfo,
) -> PurePosixPath:
    """Return one validated relative archive member path."""
    if not member.name or "\x00" in member.name:
        raise ValueError("an archive member has an invalid name")

    path = PurePosixPath(member.name)

    if path.is_absolute():
        raise ValueError(f"absolute archive path is forbidden: {member.name}")

    parts = tuple(part for part in path.parts if part not in ("", "."))

    if not parts:
        raise ValueError(f"empty archive destination is forbidden: {member.name}")

    if any(part == ".." for part in parts):
        raise ValueError(f"archive traversal is forbidden: {member.name}")

    if member.issym() or member.islnk():
        raise ValueError(f"archive links are forbidden: {member.name}")

    if member.ischr() or member.isblk() or member.isfifo():
        raise ValueError(f"archive special files are forbidden: {member.name}")

    return PurePosixPath(*parts)


def _assert_within_root(
    *,
    destination: Path,
    extraction_root: Path,
) -> None:
    """Reject any destination escaping the private extraction root."""
    root = extraction_root.resolve()
    resolved_destination = destination.resolve(strict=False)

    try:
        resolved_destination.relative_to(root)
    except ValueError as error:
        raise ValueError(
            f"archive destination escapes extraction root: {destination}"
        ) from error


def _validate_arguments(
    *,
    source_archive: Path,
    expected_sha256: str,
    build_directory: Path,
) -> None:
    """Validate source-extraction call arguments."""
    for field_name, path in (
        ("source_archive", source_archive),
        ("build_directory", build_directory),
    ):
        if not isinstance(path, Path):
            raise TypeError(f"{field_name} must be a pathlib.Path value.")
        if not path.is_absolute():
            raise ValueError(f"{field_name} must be an absolute path.")

    if not isinstance(expected_sha256, str):
        raise TypeError("expected_sha256 must be a string.")

    if not is_valid_sha256(expected_sha256):
        raise ValueError("expected_sha256 must be lower-case SHA-256 text.")


def _failure(
    *,
    code: TaskwarriorInstallFailureCode,
    message: str,
    field: str,
    path: Path,
) -> TaskwarriorSourceExtractionResult:
    """Create one failed source-extraction result."""
    return TaskwarriorSourceExtractionResult(
        extracted=None,
        issues=(
            TaskwarriorInstallerIssue(
                code=code,
                message=message,
                field=field,
                path=path,
            ),
        ),
    )
