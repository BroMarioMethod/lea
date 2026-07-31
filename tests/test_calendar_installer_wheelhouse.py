"""Tests for verified bundled calendar wheelhouse extraction."""

import hashlib
import io
import tarfile
from dataclasses import replace
from pathlib import Path

import pytest

from lea.installers.calendar import (
    CalendarExtractedWheelhouse,
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
    CalendarToolchainStagingLayout,
    CalendarWheelhouseExtractionResult,
    create_calendar_toolchain_staging,
    extract_staged_calendar_wheelhouse,
)


def _make_executable(path: Path) -> None:
    """Create one executable placeholder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o750)


def _write_tar(
    path: Path,
    members: tuple[tuple[tarfile.TarInfo, bytes | None], ...],
) -> str:
    """Write one gzip TAR and return its SHA-256 digest."""
    with tarfile.open(path, mode="w:gz") as archive:
        for member, payload in members:
            stream = io.BytesIO(payload) if payload is not None else None
            archive.addfile(member, stream)

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _regular(
    name: str,
    payload: bytes,
) -> tuple[tarfile.TarInfo, bytes]:
    """Return one regular TAR member."""
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    member.mode = 0o644
    return member, payload


def _directory(
    name: str,
) -> tuple[tarfile.TarInfo, None]:
    """Return one TAR directory member."""
    member = tarfile.TarInfo(name)
    member.type = tarfile.DIRTYPE
    member.mode = 0o755
    return member, None


def _config(
    tmp_path: Path,
    *,
    members: tuple[tuple[tarfile.TarInfo, bytes | None], ...],
) -> CalendarToolchainInstallerConfig:
    """Return one bundled-wheelhouse installer configuration."""
    uv = tmp_path / "uv"
    python = tmp_path / "python3.13"
    lock = tmp_path / "requirements.lock"
    archive = tmp_path / "calendar-wheelhouse.tar.gz"
    lock_payload = b"khal==0.11.4\nvdirsyncer==0.19.3\n"

    _make_executable(uv)
    _make_executable(python)
    lock.write_bytes(lock_payload)
    archive_sha256 = _write_tar(archive, members)

    return CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.BUNDLED_WHEELHOUSE,
        toolchain_version="calendar-1",
        khal_version="0.11.4",
        vdirsyncer_version="0.19.3",
        platform="linux-aarch64",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "install.json",
        service_user="lea",
        service_group="lea",
        uv_executable=uv,
        python_executable=python,
        requirements_lock=lock,
        expected_lock_sha256=hashlib.sha256(lock_payload).hexdigest(),
        wheelhouse_archive=archive,
        expected_wheelhouse_sha256=archive_sha256,
    )


def _stage(
    config: CalendarToolchainInstallerConfig,
) -> CalendarToolchainStagingLayout:
    """Create bundled staging and return its exact layout."""
    result = create_calendar_toolchain_staging(config)
    assert result.staged is not None
    assert result.staged.wheelhouse_directory is not None
    return result.staged


def _wheelhouse_directory(
    staged: CalendarToolchainStagingLayout,
) -> Path:
    """Return the required private wheelhouse directory."""
    wheelhouse = staged.wheelhouse_directory
    assert wheelhouse is not None
    return wheelhouse


def test_extracts_verified_flat_wheelhouse(
    tmp_path: Path,
) -> None:
    """Verified wheels and one optional manifest should extract flat."""
    config = _config(
        tmp_path,
        members=(
            _regular("khal-0.11.4-py3-none-any.whl", b"khal-wheel"),
            _regular(
                "vdirsyncer-0.19.3-py3-none-any.whl",
                b"vdirsyncer-wheel",
            ),
            _regular("wheelhouse-manifest.json", b"{}\n"),
        ),
    )
    staged = _stage(config)

    result = extract_staged_calendar_wheelhouse(
        config,
        staged,
    )

    assert result.issues == ()
    assert result.extracted is not None
    assert result.extracted.archive_sha256 == (config.expected_wheelhouse_sha256)
    assert tuple(path.name for path in result.extracted.wheel_files) == (
        "khal-0.11.4-py3-none-any.whl",
        "vdirsyncer-0.19.3-py3-none-any.whl",
    )
    assert result.extracted.manifest is not None
    assert result.extracted.manifest.name == ("wheelhouse-manifest.json")
    assert all(
        path.stat().st_mode & 0o777 == 0o640
        for path in (
            *result.extracted.wheel_files,
            result.extracted.manifest,
        )
    )
    assert result.extracted.directory.stat().st_mode & 0o777 == 0o750


def test_strips_one_common_wrapper_directory(
    tmp_path: Path,
) -> None:
    """A release-style wrapper directory should be flattened."""
    config = _config(
        tmp_path,
        members=(
            _directory("wheelhouse"),
            _regular(
                "wheelhouse/khal-0.11.4-py3-none-any.whl",
                b"khal-wheel",
            ),
        ),
    )
    staged = _stage(config)

    result = extract_staged_calendar_wheelhouse(
        config,
        staged,
    )

    assert result.extracted is not None
    wheelhouse = result.extracted.directory
    assert (wheelhouse / "khal-0.11.4-py3-none-any.whl").is_file()
    assert not (wheelhouse / "wheelhouse").exists()


def test_checksum_mismatch_extracts_nothing(
    tmp_path: Path,
) -> None:
    """Archive bytes must be rechecked immediately before extraction."""
    config = _config(
        tmp_path,
        members=(_regular("khal-0.11.4-py3-none-any.whl", b"wheel"),),
    )
    staged = _stage(config)
    assert config.wheelhouse_archive is not None
    config.wheelhouse_archive.write_bytes(b"changed")

    result = extract_staged_calendar_wheelhouse(
        config,
        staged,
    )

    assert result.extracted is None
    assert (
        result.issues[0].code is CalendarToolchainInstallFailureCode.CHECKSUM_MISMATCH
    )
    assert tuple(_wheelhouse_directory(staged).iterdir()) == ()


@pytest.mark.parametrize(
    "member",
    (
        _regular("../escape.whl", b"escape"),
        _regular("/tmp/escape.whl", b"escape"),
    ),
)
def test_rejects_path_escape(
    tmp_path: Path,
    member: tuple[tarfile.TarInfo, bytes],
) -> None:
    """Traversal and absolute destinations must fail closed."""
    config = _config(tmp_path, members=(member,))
    staged = _stage(config)

    result = extract_staged_calendar_wheelhouse(
        config,
        staged,
    )

    assert result.extracted is None
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.ARCHIVE_UNSAFE
    assert tuple(_wheelhouse_directory(staged).iterdir()) == ()
    assert not (tmp_path / "escape.whl").exists()


@pytest.mark.parametrize(
    "member_type",
    (
        tarfile.SYMTYPE,
        tarfile.LNKTYPE,
        tarfile.FIFOTYPE,
    ),
)
def test_rejects_links_and_special_files(
    tmp_path: Path,
    member_type: bytes,
) -> None:
    """Links and special archive members must never be materialised."""
    member = tarfile.TarInfo("unsafe")
    member.type = member_type

    if member_type in (tarfile.SYMTYPE, tarfile.LNKTYPE):
        member.linkname = "target"

    config = _config(
        tmp_path,
        members=((member, None),),
    )
    staged = _stage(config)

    result = extract_staged_calendar_wheelhouse(
        config,
        staged,
    )

    assert result.extracted is None
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.ARCHIVE_UNSAFE
    assert tuple(_wheelhouse_directory(staged).iterdir()) == ()


def test_rejects_non_wheel_payload(
    tmp_path: Path,
) -> None:
    """Unexpected release files must not enter the wheel source."""
    config = _config(
        tmp_path,
        members=(
            _regular("README.txt", b"not a wheel"),
            _regular("khal-0.11.4-py3-none-any.whl", b"wheel"),
        ),
    )
    staged = _stage(config)

    result = extract_staged_calendar_wheelhouse(
        config,
        staged,
    )

    assert result.extracted is None
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.ARCHIVE_UNSAFE
    assert tuple(_wheelhouse_directory(staged).iterdir()) == ()


def test_rejects_nested_wheel_after_wrapper(
    tmp_path: Path,
) -> None:
    """uv find-links should receive one flat wheelhouse directory."""
    config = _config(
        tmp_path,
        members=(
            _regular(
                "wheelhouse/nested/khal-0.11.4-py3-none-any.whl",
                b"wheel",
            ),
        ),
    )
    staged = _stage(config)

    result = extract_staged_calendar_wheelhouse(
        config,
        staged,
    )

    assert result.extracted is None
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.ARCHIVE_UNSAFE


def test_rejects_duplicate_destination(
    tmp_path: Path,
) -> None:
    """Duplicate TAR members must not overwrite earlier bytes."""
    config = _config(
        tmp_path,
        members=(
            _regular("khal-0.11.4-py3-none-any.whl", b"first"),
            _regular("khal-0.11.4-py3-none-any.whl", b"second"),
        ),
    )
    staged = _stage(config)

    result = extract_staged_calendar_wheelhouse(
        config,
        staged,
    )

    assert result.extracted is None
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.ARCHIVE_UNSAFE
    assert tuple(_wheelhouse_directory(staged).iterdir()) == ()


def test_requires_at_least_one_wheel(
    tmp_path: Path,
) -> None:
    """A manifest-only archive is not an installable wheelhouse."""
    config = _config(
        tmp_path,
        members=(_regular("manifest.json", b"{}\n"),),
    )
    staged = _stage(config)

    result = extract_staged_calendar_wheelhouse(
        config,
        staged,
    )

    assert result.extracted is None
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.ARCHIVE_UNSAFE


def test_non_empty_destination_is_preserved(
    tmp_path: Path,
) -> None:
    """Extraction must not overwrite administrator or prior-stage files."""
    config = _config(
        tmp_path,
        members=(_regular("khal-0.11.4-py3-none-any.whl", b"wheel"),),
    )
    staged = _stage(config)
    assert staged.wheelhouse_directory is not None
    sentinel = staged.wheelhouse_directory / "preserve"
    sentinel.write_text("preserve\n", encoding="utf-8")

    result = extract_staged_calendar_wheelhouse(
        config,
        staged,
    )

    assert result.extracted is None
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.INVALID_ARGUMENT
    assert sentinel.read_text(encoding="utf-8") == "preserve\n"


def test_staging_from_another_tools_root_is_rejected(
    tmp_path: Path,
) -> None:
    """Configuration and staging must identify the same installation."""
    first = _config(
        tmp_path / "first",
        members=(_regular("khal-0.11.4-py3-none-any.whl", b"wheel"),),
    )
    second = _config(
        tmp_path / "second",
        members=(_regular("khal-0.11.4-py3-none-any.whl", b"wheel"),),
    )
    staged = _stage(first)

    result = extract_staged_calendar_wheelhouse(
        second,
        staged,
    )

    assert result.extracted is None
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.INVALID_ARGUMENT


def test_network_mode_is_rejected(
    tmp_path: Path,
) -> None:
    """Verified-network mode does not consume a bundled archive."""
    bundled = _config(
        tmp_path,
        members=(_regular("khal-0.11.4-py3-none-any.whl", b"wheel"),),
    )
    staged = _stage(bundled)
    network = replace(
        bundled,
        mode=CalendarToolchainInstallMode.VERIFIED_NETWORK,
        wheelhouse_archive=None,
        expected_wheelhouse_sha256=None,
        package_index_url="https://pypi.org/simple",
    )

    result = extract_staged_calendar_wheelhouse(
        network,
        staged,
    )

    assert result.extracted is None
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.INVALID_ARGUMENT


def test_successful_result_requires_extracted_contract() -> None:
    """A successful-looking result cannot omit extraction evidence."""
    with pytest.raises(
        ValueError,
        match="must contain at least one issue",
    ):
        CalendarWheelhouseExtractionResult(
            extracted=None,
            issues=(),
        )


def test_extracted_contract_requires_wheels(
    tmp_path: Path,
) -> None:
    """Extracted-wheelhouse evidence cannot represent an empty source."""
    with pytest.raises(
        ValueError,
        match="at least one wheel",
    ):
        CalendarExtractedWheelhouse(
            directory=tmp_path,
            archive_sha256="a" * 64,
            wheel_files=(),
            manifest=None,
        )
