"""Tests for strict calendar toolchain installation records."""

import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from lea.installers.calendar import (
    CalendarToolchainInstallationRecord,
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
    calendar_toolchain_installation_record_identity_matches,
    calendar_toolchain_installation_record_matches,
    create_calendar_toolchain_installation_record,
    read_calendar_toolchain_installation_record,
    render_calendar_toolchain_installation_record,
    replace_calendar_toolchain_installation_record,
    write_calendar_toolchain_installation_record,
)

INSTALLED_AT = datetime(2026, 7, 31, 10, 30, tzinfo=UTC)
MATERIAL_SHA256 = "a" * 64


def _make_executable(path: Path) -> None:
    """Create one executable placeholder required by installer contracts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o750)


def _config(
    tmp_path: Path,
) -> CalendarToolchainInstallerConfig:
    """Return one managed verified-network installer configuration."""
    uv = tmp_path / "uv"
    python = tmp_path / "python3.13"
    lock = tmp_path / "requirements.lock"

    _make_executable(uv)
    _make_executable(python)
    lock.write_text("khal==0.11.4\n", encoding="utf-8")

    return CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.VERIFIED_NETWORK,
        toolchain_version="calendar-1",
        khal_version="0.11.4",
        vdirsyncer_version="0.19.3",
        platform="linux-aarch64",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=(tmp_path / "install" / "calendar-toolchain.json"),
        service_user="lea",
        service_group="lea",
        uv_executable=uv,
        python_executable=python,
        requirements_lock=lock,
        expected_lock_sha256=MATERIAL_SHA256,
        package_index_url="https://packages.example.invalid/simple",
    )


def _record(
    tmp_path: Path,
) -> CalendarToolchainInstallationRecord:
    """Return one deterministic installation record."""
    config = _config(tmp_path)
    root = config.tools_root / config.toolchain_version / ".venv" / "bin"

    return create_calendar_toolchain_installation_record(
        config,
        python_version="3.13.5",
        khal_executable=root / "khal",
        vdirsyncer_executable=root / "vdirsyncer",
        lock_or_manifest_sha256=MATERIAL_SHA256,
        installed_at=INSTALLED_AT,
    )


def test_record_creation_uses_verified_installer_evidence(
    tmp_path: Path,
) -> None:
    """Record creation should preserve exact config and executable data."""
    config = _config(tmp_path)
    root = config.tools_root / config.toolchain_version / ".venv" / "bin"

    record = create_calendar_toolchain_installation_record(
        config,
        python_version="3.13.5",
        khal_executable=root / "khal",
        vdirsyncer_executable=root / "vdirsyncer",
        lock_or_manifest_sha256=MATERIAL_SHA256,
        installed_at=INSTALLED_AT,
    )

    assert record.schema_version == 2
    assert record.component == "calendar-toolchain"
    assert record.toolchain_version == config.toolchain_version
    assert record.installation_mode is config.mode
    assert record.platform == config.platform
    assert record.python_version == "3.13.5"
    assert record.khal_version == "0.11.4"
    assert record.vdirsyncer_version == "0.19.3"
    assert record.khal_executable == root / "khal"
    assert record.vdirsyncer_executable == root / "vdirsyncer"
    assert record.lock_or_manifest_sha256 == MATERIAL_SHA256
    assert record.khal_executable_sha256 is None
    assert record.vdirsyncer_executable_sha256 is None
    assert record.smoke_test == "passed"
    assert record.installed_at == INSTALLED_AT


def test_record_rendering_is_deterministic(
    tmp_path: Path,
) -> None:
    """Rendered JSON should be sorted and canonically UTC."""
    record = _record(tmp_path)

    first = render_calendar_toolchain_installation_record(record)
    second = render_calendar_toolchain_installation_record(record)
    payload = json.loads(first)

    assert first == second
    assert first.endswith("\n")
    assert payload["installed_at"] == "2026-07-31T10:30:00Z"
    assert payload["installation_mode"] == "verified-network"
    assert payload["lock_or_manifest_sha256"] == MATERIAL_SHA256
    assert list(payload) == sorted(payload)


def test_record_round_trip_is_lossless(
    tmp_path: Path,
) -> None:
    """A rendered record should read back without information loss."""
    record = _record(tmp_path)
    path = tmp_path / "record.json"
    path.write_text(
        render_calendar_toolchain_installation_record(record),
        encoding="utf-8",
    )

    parsed, issues = read_calendar_toolchain_installation_record(path)

    assert issues == ()
    assert parsed == record


def test_unknown_record_key_is_rejected(
    tmp_path: Path,
) -> None:
    """Strict parsing must reject unrecognised persisted fields."""
    record = _record(tmp_path)
    payload = json.loads(render_calendar_toolchain_installation_record(record))
    payload["unexpected"] = "value"
    path = tmp_path / "record.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    parsed, issues = read_calendar_toolchain_installation_record(path)

    assert parsed is None
    assert len(issues) == 1
    assert issues[0].code is CalendarToolchainInstallFailureCode.RECORD_FAILED


def test_duplicate_json_key_is_rejected(
    tmp_path: Path,
) -> None:
    """Duplicate object keys must not be silently accepted."""
    record = _record(tmp_path)
    document = render_calendar_toolchain_installation_record(record)
    duplicate = document.replace(
        '"component": "calendar-toolchain",',
        ('"component": "calendar-toolchain",\n  "component": "calendar-toolchain",'),
    )
    path = tmp_path / "record.json"
    path.write_text(duplicate, encoding="utf-8")

    parsed, issues = read_calendar_toolchain_installation_record(path)

    assert parsed is None
    assert len(issues) == 1


def test_non_canonical_utc_text_is_rejected(
    tmp_path: Path,
) -> None:
    """Persisted timestamps must use canonical Z-form UTC."""
    record = _record(tmp_path)
    payload = json.loads(render_calendar_toolchain_installation_record(record))
    payload["installed_at"] = "2026-07-31T12:30:00+02:00"
    path = tmp_path / "record.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    parsed, issues = read_calendar_toolchain_installation_record(path)

    assert parsed is None
    assert len(issues) == 1


def test_record_contract_rejects_non_utc_timestamp(
    tmp_path: Path,
) -> None:
    """The immutable record itself must require canonical UTC."""
    record = _record(tmp_path)

    with pytest.raises(
        ValueError,
        match="canonical UTC",
    ):
        replace(
            record,
            installed_at=datetime.fromisoformat("2026-07-31T12:30:00+02:00"),
        )


def test_record_contract_rejects_invalid_sha256(
    tmp_path: Path,
) -> None:
    """Material evidence must use canonical SHA-256 text."""
    record = _record(tmp_path)

    with pytest.raises(
        ValueError,
        match="lower-case hexadecimal",
    ):
        replace(
            record,
            lock_or_manifest_sha256="NOT-A-SHA256",
        )


def test_missing_record_returns_structured_issue(
    tmp_path: Path,
) -> None:
    """Missing installation evidence should fail closed."""
    path = tmp_path / "missing.json"

    record, issues = read_calendar_toolchain_installation_record(path)

    assert record is None
    assert len(issues) == 1
    assert issues[0].field == "installation_record"
    assert issues[0].path == path


def test_inaccessible_record_returns_structured_issue(
    tmp_path: Path,
) -> None:
    """Permission failures must return one deterministic record issue."""
    path = tmp_path / "record.json"

    with patch.object(
        Path,
        "is_symlink",
        side_effect=PermissionError("permission denied"),
    ):
        record, issues = read_calendar_toolchain_installation_record(path)

    assert record is None
    assert len(issues) == 1
    assert issues[0].code is CalendarToolchainInstallFailureCode.RECORD_FAILED
    assert issues[0].field == "installation_record"
    assert issues[0].path == path
    assert "could not be accessed" in issues[0].message


def test_symlinked_record_is_rejected(
    tmp_path: Path,
) -> None:
    """Record reads must not follow symbolic links."""
    target = tmp_path / "target.json"
    target.write_text("{}\n", encoding="utf-8")
    path = tmp_path / "record.json"
    path.symlink_to(target)

    record, issues = read_calendar_toolchain_installation_record(path)

    assert record is None
    assert len(issues) == 1
    assert "symbolic link" in issues[0].message


def test_matching_helper_compares_complete_identity(
    tmp_path: Path,
) -> None:
    """Idempotency must require every stable record identity field."""
    config = _config(tmp_path)
    record = _record(tmp_path)

    assert calendar_toolchain_installation_record_matches(
        record,
        config=config,
        python_version="3.13.5",
        khal_executable=record.khal_executable,
        vdirsyncer_executable=record.vdirsyncer_executable,
        lock_or_manifest_sha256=MATERIAL_SHA256,
    )

    assert not calendar_toolchain_installation_record_matches(
        record,
        config=config,
        python_version="3.13.6",
        khal_executable=record.khal_executable,
        vdirsyncer_executable=record.vdirsyncer_executable,
        lock_or_manifest_sha256=MATERIAL_SHA256,
    )

    assert not calendar_toolchain_installation_record_matches(
        record,
        config=config,
        python_version="3.13.5",
        khal_executable=record.khal_executable,
        vdirsyncer_executable=record.vdirsyncer_executable,
        lock_or_manifest_sha256="b" * 64,
    )


def test_managed_identity_match_ignores_only_lock_evidence(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    record = _record(tmp_path)

    assert calendar_toolchain_installation_record_identity_matches(
        replace(
            record,
            lock_or_manifest_sha256="b" * 64,
        ),
        config=config,
        python_version="3.13.5",
        khal_executable=record.khal_executable,
        vdirsyncer_executable=record.vdirsyncer_executable,
    )

    assert not calendar_toolchain_installation_record_identity_matches(
        replace(
            record,
            python_version="3.13.6",
            lock_or_manifest_sha256="b" * 64,
        ),
        config=config,
        python_version="3.13.5",
        khal_executable=record.khal_executable,
        vdirsyncer_executable=record.vdirsyncer_executable,
    )


def test_record_evidence_replacement_is_atomic(
    tmp_path: Path,
) -> None:
    current = _record(tmp_path)
    replacement_record = replace(
        current,
        lock_or_manifest_sha256="b" * 64,
    )
    destination = tmp_path / "install" / "calendar.json"
    destination.parent.mkdir()
    destination.write_text(
        render_calendar_toolchain_installation_record(current),
        encoding="utf-8",
    )
    destination.chmod(0o600)
    ownership: list[tuple[Path, str, str]] = []

    def apply_ownership(
        path: Path,
        owner: str,
        group: str,
    ) -> bool:
        ownership.append((path, owner, group))
        return True

    issues = replace_calendar_toolchain_installation_record(
        current,
        replacement_record,
        destination=destination,
        owner="root",
        group="lea",
        apply_ownership=apply_ownership,
    )

    assert issues == ()
    assert destination.read_text(encoding="utf-8") == (
        render_calendar_toolchain_installation_record(replacement_record)
    )
    assert destination.stat().st_mode & 0o777 == 0o640
    assert replacement_record.installed_at == current.installed_at
    assert ownership[-1] == (destination, "root", "lea")
    assert tuple(destination.parent.glob(".*.replacement")) == ()
    assert tuple(destination.parent.glob(".*.rollback")) == ()


def test_record_evidence_replacement_rejects_identity_drift(
    tmp_path: Path,
) -> None:
    current = _record(tmp_path)
    unsafe = replace(
        current,
        python_version="3.13.6",
        lock_or_manifest_sha256="b" * 64,
    )
    destination = tmp_path / "install" / "calendar.json"
    destination.parent.mkdir()
    original_document = render_calendar_toolchain_installation_record(current)
    destination.write_text(original_document, encoding="utf-8")

    issues = replace_calendar_toolchain_installation_record(
        current,
        unsafe,
        destination=destination,
    )

    assert len(issues) == 1
    assert "only the managed lock or manifest checksum" in (issues[0].message)
    assert destination.read_text(encoding="utf-8") == original_document


def test_record_evidence_replacement_requires_exact_current_bytes(
    tmp_path: Path,
) -> None:
    current = _record(tmp_path)
    replacement_record = replace(
        current,
        lock_or_manifest_sha256="b" * 64,
    )
    destination = tmp_path / "install" / "calendar.json"
    destination.parent.mkdir()
    destination.write_text(
        '{"administrator":"preserve"}\n',
        encoding="utf-8",
    )

    issues = replace_calendar_toolchain_installation_record(
        current,
        replacement_record,
        destination=destination,
    )

    assert len(issues) == 1
    assert destination.read_text(encoding="utf-8") == ('{"administrator":"preserve"}\n')


def test_writer_creates_atomic_managed_record(
    tmp_path: Path,
) -> None:
    """Initial persistence should create a 0640 root-group record."""
    record = _record(tmp_path)
    destination = tmp_path / "install" / "calendar.json"
    ownership: list[tuple[Path, str, str]] = []

    def apply_ownership(
        path: Path,
        owner: str,
        group: str,
    ) -> bool:
        ownership.append((path, owner, group))
        return True

    issues = write_calendar_toolchain_installation_record(
        record,
        destination=destination,
        owner="root",
        group="lea",
        apply_ownership=apply_ownership,
    )

    assert issues == ()
    assert destination.read_text(encoding="utf-8") == (
        render_calendar_toolchain_installation_record(record)
    )
    assert destination.parent.stat().st_mode & 0o777 == 0o750
    assert destination.stat().st_mode & 0o777 == 0o640
    assert ownership == [
        (destination.parent, "root", "lea"),
        (destination, "root", "lea"),
    ]
    assert tuple(destination.parent.glob(".*.tmp")) == ()


def test_writer_is_idempotent_for_identical_record(
    tmp_path: Path,
) -> None:
    """An identical record should be accepted without rewriting bytes."""
    record = _record(tmp_path)
    destination = tmp_path / "install" / "calendar.json"
    ownership: list[tuple[Path, str, str]] = []

    def apply_ownership(
        path: Path,
        owner: str,
        group: str,
    ) -> bool:
        ownership.append((path, owner, group))
        return True

    first = write_calendar_toolchain_installation_record(
        record,
        destination=destination,
        owner="root",
        group="lea",
        apply_ownership=apply_ownership,
    )
    before = destination.stat().st_ino
    destination.parent.chmod(0o700)

    second = write_calendar_toolchain_installation_record(
        record,
        destination=destination,
        owner="root",
        group="lea",
        apply_ownership=apply_ownership,
    )

    assert first == ()
    assert second == ()
    assert destination.stat().st_ino == before
    assert destination.parent.stat().st_mode & 0o777 == 0o750
    assert ownership == [
        (destination.parent, "root", "lea"),
        (destination, "root", "lea"),
        (destination.parent, "root", "lea"),
        (destination, "root", "lea"),
    ]


def test_mismatched_existing_record_is_not_overwritten(
    tmp_path: Path,
) -> None:
    """A different record must be preserved and fail closed."""
    record = _record(tmp_path)
    destination = tmp_path / "install" / "calendar.json"
    destination.parent.mkdir()
    destination.write_text(
        '{"administrator":"preserve"}\n',
        encoding="utf-8",
    )

    issues = write_calendar_toolchain_installation_record(
        record,
        destination=destination,
    )

    assert len(issues) == 1
    assert issues[0].code is CalendarToolchainInstallFailureCode.RECORD_FAILED
    assert destination.read_text(encoding="utf-8") == ('{"administrator":"preserve"}\n')


def test_symlinked_destination_is_not_overwritten(
    tmp_path: Path,
) -> None:
    """Record persistence must never follow an existing symlink."""
    record = _record(tmp_path)
    target = tmp_path / "preserve.json"
    target.write_text("preserve\n", encoding="utf-8")
    destination = tmp_path / "install" / "calendar.json"
    destination.parent.mkdir()
    destination.symlink_to(target)

    issues = write_calendar_toolchain_installation_record(
        record,
        destination=destination,
    )

    assert len(issues) == 1
    assert target.read_text(encoding="utf-8") == "preserve\n"


def test_destination_race_does_not_overwrite_new_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A record appearing during persistence must remain untouched."""
    record = _record(tmp_path)
    destination = tmp_path / "install" / "calendar.json"

    original_link = os.link

    def racing_link(
        source: Path | str,
        target: Path | str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        Path(target).write_text("racing writer\n", encoding="utf-8")
        original_link(source, target, *args, **kwargs)

    monkeypatch.setattr(os, "link", racing_link)

    issues = write_calendar_toolchain_installation_record(
        record,
        destination=destination,
    )

    assert len(issues) == 1
    assert destination.read_text(encoding="utf-8") == "racing writer\n"


def test_ownership_failure_removes_new_record(
    tmp_path: Path,
) -> None:
    """A failed post-create ownership step must roll back the new file."""
    record = _record(tmp_path)
    destination = tmp_path / "install" / "calendar.json"

    def fail_ownership(
        _path: Path,
        _owner: str,
        _group: str,
    ) -> bool:
        raise PermissionError("ownership denied")

    issues = write_calendar_toolchain_installation_record(
        record,
        destination=destination,
        owner="root",
        group="lea",
        apply_ownership=fail_ownership,
    )

    assert len(issues) == 1
    assert "ownership denied" in issues[0].message
    assert destination.exists() is False


def test_symbolic_link_parent_is_rejected(
    tmp_path: Path,
) -> None:
    """Record creation must not traverse a symlinked parent."""
    record = _record(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(external, target_is_directory=True)
    destination = linked_parent / "calendar.json"

    issues = write_calendar_toolchain_installation_record(
        record,
        destination=destination,
    )

    assert len(issues) == 1
    assert "symbolic-link directory" in issues[0].message
    assert (external / "calendar.json").exists() is False
