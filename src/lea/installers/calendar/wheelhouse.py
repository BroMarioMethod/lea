"""Verified and safe extraction of bundled calendar wheelhouses."""

import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from lea.installers.calendar.contracts import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallerIssue,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
)
from lea.installers.calendar.preflight import calculate_calendar_sha256
from lea.installers.calendar.staging import (
    CalendarToolchainStagingLayout,
)

_DIRECTORY_MODE = 0o750
_FILE_MODE = 0o640
_ALLOWED_MANIFEST_NAMES = frozenset(
    {
        "manifest.json",
        "wheelhouse-manifest.json",
    }
)


@dataclass(frozen=True, slots=True)
class CalendarExtractedWheelhouse:
    """One verified wheelhouse extracted into private installer staging."""

    directory: Path
    archive_sha256: str
    wheel_files: tuple[Path, ...]
    manifest: Path | None

    def __post_init__(self) -> None:
        """Validate extracted-wheelhouse relationships."""
        _validate_absolute_path(
            self.directory,
            field_name="directory",
        )
        _validate_sha256(
            self.archive_sha256,
            field_name="archive_sha256",
        )

        if not self.wheel_files:
            raise ValueError("wheel_files must contain at least one wheel.")

        if tuple(sorted(self.wheel_files)) != self.wheel_files:
            raise ValueError("wheel_files must use deterministic ordering.")

        for wheel in self.wheel_files:
            _validate_absolute_path(
                wheel,
                field_name="wheel_files",
            )

            if wheel.parent != self.directory:
                raise ValueError("Every wheel file must be directly inside directory.")

            if not wheel.name.endswith(".whl"):
                raise ValueError("Every wheel file must use the .whl suffix.")

        if self.manifest is not None:
            _validate_absolute_path(
                self.manifest,
                field_name="manifest",
            )

            if self.manifest.parent != self.directory:
                raise ValueError("manifest must be directly inside directory.")

            if self.manifest.name not in _ALLOWED_MANIFEST_NAMES:
                raise ValueError(
                    "manifest must use an allowed wheelhouse manifest name."
                )


@dataclass(frozen=True, slots=True)
class CalendarWheelhouseExtractionResult:
    """Result of verifying and extracting one bundled wheelhouse."""

    extracted: CalendarExtractedWheelhouse | None
    issues: tuple[CalendarToolchainInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate extraction-result consistency."""
        if self.extracted is not None:
            if self.issues:
                raise ValueError("A successful extraction must not contain issues.")

            return

        if not self.issues:
            raise ValueError("A failed extraction must contain at least one issue.")


def extract_staged_calendar_wheelhouse(
    config: CalendarToolchainInstallerConfig,
    staged: CalendarToolchainStagingLayout,
) -> CalendarWheelhouseExtractionResult:
    """Verify and safely extract one bundled TAR wheelhouse."""
    if not isinstance(config, CalendarToolchainInstallerConfig):
        raise TypeError("config must be a CalendarToolchainInstallerConfig value.")

    if not isinstance(staged, CalendarToolchainStagingLayout):
        raise TypeError("staged must be a CalendarToolchainStagingLayout value.")

    if config.mode is not CalendarToolchainInstallMode.BUNDLED_WHEELHOUSE:
        return _failure(
            code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
            message=("Wheelhouse extraction requires bundled-wheelhouse mode."),
            field="mode",
        )

    if staged.staging_parent != config.tools_root:
        return _failure(
            code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
            message=(
                "The staged wheelhouse does not belong to the configured "
                "calendar tools root."
            ),
            field="tools_root",
            path=staged.staging_root,
        )

    destination = staged.wheelhouse_directory

    if destination is None:
        return _failure(
            code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
            message=("Bundled-wheelhouse staging has no extraction directory."),
            field="wheelhouse_directory",
        )

    if destination != staged.staging_root / "wheelhouse":
        return _failure(
            code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
            message=("The staged wheelhouse directory has an invalid relationship."),
            field="wheelhouse_directory",
            path=destination,
        )

    destination_issue = _inspect_destination(destination)

    if destination_issue is not None:
        return CalendarWheelhouseExtractionResult(
            extracted=None,
            issues=(destination_issue,),
        )

    archive = config.wheelhouse_archive
    expected_sha256 = config.expected_wheelhouse_sha256

    if archive is None:
        return _failure(
            code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
            message="The bundled wheelhouse archive path is missing.",
            field="wheelhouse_archive",
        )

    if expected_sha256 is None:
        return _failure(
            code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
            message=("The expected bundled wheelhouse checksum is missing."),
            field="expected_wheelhouse_sha256",
            path=archive,
        )

    archive_issue, actual_sha256 = _inspect_archive(
        archive,
        expected_sha256=expected_sha256,
    )

    if archive_issue is not None or actual_sha256 is None:
        return CalendarWheelhouseExtractionResult(
            extracted=None,
            issues=(
                archive_issue
                or CalendarToolchainInstallerIssue(
                    code=(CalendarToolchainInstallFailureCode.ARCHIVE_UNSAFE),
                    message=("The bundled wheelhouse archive could not be verified."),
                    field="wheelhouse_archive",
                    path=archive,
                ),
            ),
        )

    try:
        wheel_files, manifest = _extract_tar_safely(
            archive=archive,
            destination=destination,
        )
    except (OSError, tarfile.TarError, ValueError) as error:
        cleanup_issue = _clear_destination(destination)
        issues = [
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.ARCHIVE_UNSAFE,
                message=(
                    "The bundled calendar wheelhouse archive was "
                    f"rejected: {_error_detail(error)}."
                ),
                field="wheelhouse_archive",
                path=archive,
            )
        ]

        if cleanup_issue is not None:
            issues.append(cleanup_issue)

        return CalendarWheelhouseExtractionResult(
            extracted=None,
            issues=tuple(issues),
        )

    return CalendarWheelhouseExtractionResult(
        extracted=CalendarExtractedWheelhouse(
            directory=destination,
            archive_sha256=actual_sha256,
            wheel_files=wheel_files,
            manifest=manifest,
        ),
        issues=(),
    )


def _inspect_destination(
    destination: Path,
) -> CalendarToolchainInstallerIssue | None:
    """Require one empty real private extraction directory."""
    try:
        if destination.is_symlink():
            return CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=(
                    "The staged wheelhouse directory must not be a symbolic link."
                ),
                field="wheelhouse_directory",
                path=destination,
            )

        if not destination.exists() or not destination.is_dir():
            return CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=(
                    "The staged wheelhouse directory must be an existing "
                    "real directory."
                ),
                field="wheelhouse_directory",
                path=destination,
            )

        if any(destination.iterdir()):
            return CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.INVALID_ARGUMENT,
                message=(
                    "The staged wheelhouse directory must be empty before extraction."
                ),
                field="wheelhouse_directory",
                path=destination,
            )

        destination.chmod(_DIRECTORY_MODE)
    except OSError as error:
        return CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.PERMISSION_DENIED,
            message=(
                "The staged wheelhouse directory could not be inspected: "
                f"{_error_detail(error)}."
            ),
            field="wheelhouse_directory",
            path=destination,
        )

    return None


def _inspect_archive(
    archive: Path,
    *,
    expected_sha256: str,
) -> tuple[CalendarToolchainInstallerIssue | None, str | None]:
    """Recheck one exact regular archive immediately before opening it."""
    _validate_sha256(
        expected_sha256,
        field_name="expected_sha256",
    )

    try:
        if archive.is_symlink():
            return (
                CalendarToolchainInstallerIssue(
                    code=(CalendarToolchainInstallFailureCode.INVALID_ARGUMENT),
                    message=(
                        "The bundled wheelhouse archive must not be a symbolic link."
                    ),
                    field="wheelhouse_archive",
                    path=archive,
                ),
                None,
            )

        if not archive.exists():
            return (
                CalendarToolchainInstallerIssue(
                    code=(CalendarToolchainInstallFailureCode.ARTEFACT_MISSING),
                    message=("The bundled wheelhouse archive does not exist."),
                    field="wheelhouse_archive",
                    path=archive,
                ),
                None,
            )

        if not archive.is_file():
            return (
                CalendarToolchainInstallerIssue(
                    code=(CalendarToolchainInstallFailureCode.INVALID_ARGUMENT),
                    message=("The bundled wheelhouse archive is not a regular file."),
                    field="wheelhouse_archive",
                    path=archive,
                ),
                None,
            )

        actual_sha256 = calculate_calendar_sha256(archive)
    except OSError as error:
        return (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.PERMISSION_DENIED,
                message=(
                    "The bundled wheelhouse archive could not be read: "
                    f"{_error_detail(error)}."
                ),
                field="wheelhouse_archive",
                path=archive,
            ),
            None,
        )

    if actual_sha256 != expected_sha256:
        return (
            CalendarToolchainInstallerIssue(
                code=CalendarToolchainInstallFailureCode.CHECKSUM_MISMATCH,
                message=(
                    "The bundled wheelhouse archive checksum changed before extraction."
                ),
                field="expected_wheelhouse_sha256",
                path=archive,
            ),
            None,
        )

    return None, actual_sha256


def _extract_tar_safely(
    *,
    archive: Path,
    destination: Path,
) -> tuple[tuple[Path, ...], Path | None]:
    """Extract regular wheelhouse members without extractall or links."""
    with tarfile.open(archive, mode="r:*") as tar:
        members = tar.getmembers()

        if not members:
            raise ValueError("the archive is empty")

        validated = tuple((member, _safe_member_path(member)) for member in members)
        strip_root = _common_wrapper_root(validated)

        planned: dict[str, tarfile.TarInfo] = {}

        for member, relative in validated:
            normalised = _normalise_member_path(
                relative,
                strip_root=strip_root,
            )

            if normalised is None:
                if not member.isdir():
                    raise ValueError(f"empty archive destination: {member.name}")

                continue

            if member.isdir():
                raise ValueError(
                    f"nested wheelhouse directories are forbidden: {member.name}"
                )

            if len(normalised.parts) != 1:
                raise ValueError(
                    "wheelhouse files must be flat after an optional "
                    f"wrapper directory: {member.name}"
                )

            filename = normalised.name

            if (
                not filename.endswith(".whl")
                and filename not in _ALLOWED_MANIFEST_NAMES
            ):
                raise ValueError(f"unsupported wheelhouse file: {member.name}")

            if filename in planned:
                raise ValueError(f"duplicate archive destination: {member.name}")

            planned[filename] = member

        wheel_names = sorted(name for name in planned if name.endswith(".whl"))

        if not wheel_names:
            raise ValueError("the archive contains no wheel files")

        manifests = sorted(name for name in planned if name in _ALLOWED_MANIFEST_NAMES)

        if len(manifests) > 1:
            raise ValueError("the archive contains more than one wheelhouse manifest")

        for filename in sorted(planned):
            member = planned[filename]
            target = destination / filename
            _assert_direct_child(
                target=target,
                destination=destination,
            )
            _copy_member_payload(
                archive=tar,
                member=member,
                destination=target,
            )

    destination.chmod(_DIRECTORY_MODE)

    wheel_files = tuple(destination / name for name in wheel_names)
    manifest = destination / manifests[0] if manifests else None
    return wheel_files, manifest


def _safe_member_path(
    member: tarfile.TarInfo,
) -> PurePosixPath:
    """Return one validated relative regular-member path."""
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

    if member.islnk():
        raise ValueError(f"archive hard links are forbidden: {member.name}")

    if member.issym():
        raise ValueError(f"archive symbolic links are forbidden: {member.name}")

    if not member.isdir() and not member.isfile():
        raise ValueError(f"unsupported archive member type: {member.name}")

    return PurePosixPath(*parts)


def _common_wrapper_root(
    members: tuple[tuple[tarfile.TarInfo, PurePosixPath], ...],
) -> str | None:
    """Return one common directory prefix when every file is wrapped."""
    files = tuple(relative for member, relative in members if member.isfile())

    if not files:
        return None

    first_parts = {relative.parts[0] for relative in files}

    if len(first_parts) != 1:
        return None

    if any(len(relative.parts) < 2 for relative in files):
        return None

    return next(iter(first_parts))


def _normalise_member_path(
    relative: PurePosixPath,
    *,
    strip_root: str | None,
) -> PurePosixPath | None:
    """Strip one optional common wrapper directory."""
    parts = relative.parts

    if strip_root is not None:
        if parts[0] != strip_root:
            raise ValueError("archive members do not share one wrapper directory")

        parts = parts[1:]

    if not parts:
        return None

    return PurePosixPath(*parts)


def _copy_member_payload(
    *,
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    destination: Path,
) -> None:
    """Materialise one verified regular member."""
    stream = archive.extractfile(member)

    if stream is None:
        raise ValueError(f"archive member has no readable payload: {member.name}")

    with stream, destination.open("xb") as output:
        shutil.copyfileobj(stream, output)

    destination.chmod(_FILE_MODE)


def _assert_direct_child(
    *,
    target: Path,
    destination: Path,
) -> None:
    """Require one direct destination child without resolution escape."""
    if target.parent != destination:
        raise ValueError(f"wheelhouse destination escapes extraction root: {target}")

    resolved_root = destination.resolve()
    resolved_target = target.resolve(strict=False)

    try:
        resolved_target.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(
            f"wheelhouse destination escapes extraction root: {target}"
        ) from error


def _clear_destination(
    destination: Path,
) -> CalendarToolchainInstallerIssue | None:
    """Remove only partial children from the private wheelhouse directory."""
    try:
        for child in tuple(destination.iterdir()):
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()

        destination.chmod(_DIRECTORY_MODE)
    except OSError as error:
        return CalendarToolchainInstallerIssue(
            code=CalendarToolchainInstallFailureCode.COPY_FAILED,
            message=(
                "The partial calendar wheelhouse extraction could not be "
                f"removed: {_error_detail(error)}."
            ),
            field="wheelhouse_directory",
            path=destination,
        )

    return None


def _failure(
    *,
    code: CalendarToolchainInstallFailureCode,
    message: str,
    field: str,
    path: Path | None = None,
) -> CalendarWheelhouseExtractionResult:
    """Create one failed extraction result."""
    return CalendarWheelhouseExtractionResult(
        extracted=None,
        issues=(
            CalendarToolchainInstallerIssue(
                code=code,
                message=message,
                field=field,
                path=path,
            ),
        ),
    )


def _error_detail(error: BaseException) -> str:
    """Return deterministic filesystem or archive diagnostics."""
    strerror = getattr(error, "strerror", None)

    if isinstance(strerror, str) and strerror:
        return strerror

    rendered = str(error).strip()
    return rendered or type(error).__name__


def _validate_absolute_path(
    path: Path,
    *,
    field_name: str,
) -> None:
    """Validate one absolute pathlib path."""
    if not isinstance(path, Path):
        raise TypeError(f"{field_name} must be a pathlib.Path value.")

    if not path.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path.")


def _validate_sha256(
    value: str,
    *,
    field_name: str,
) -> None:
    """Validate canonical lower-case SHA-256 text."""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")

    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{field_name} must be lower-case hexadecimal SHA-256 text.")
