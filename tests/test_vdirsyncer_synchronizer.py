"""Tests for explicit provider-neutral vdirsyncer synchronization."""

import sys
from pathlib import Path

from lea.adapters.vdirsyncer import (
    VdirsyncerCalendarSynchronizer,
    VdirsyncerConfig,
)
from lea.calendars import CalendarSynchronizer


def _config(tmp_path: Path, *, version: str = "0.20.0") -> VdirsyncerConfig:
    executable = tmp_path / "bin" / "vdirsyncer"
    configuration = tmp_path / "config" / "vdirsyncer.conf"
    working = tmp_path / "work"
    executable.parent.mkdir()
    configuration.parent.mkdir()
    working.mkdir()
    executable.write_text(
        (
            f"#!{sys.executable}\n"
            "import pathlib, sys\n"
            f"version = {version!r}\n"
            "if sys.argv[1:] == ['--version']:\n"
            "    print(f'vdirsyncer, version {version}')\n"
            "else:\n"
            "    pathlib.Path('synced').write_text('|'.join(sys.argv[1:]))\n"
        ),
        encoding="utf-8",
    )
    executable.chmod(0o700)
    configuration.write_text("[general]\n", encoding="utf-8")
    return VdirsyncerConfig(
        executable,
        configuration,
        working,
        expected_version="0.20.0",
    )


def test_inspection_has_no_synchronization_side_effect(tmp_path: Path) -> None:
    config = _config(tmp_path)
    synchronizer = VdirsyncerCalendarSynchronizer(config)

    result = synchronizer.inspect()

    assert isinstance(synchronizer, CalendarSynchronizer)
    assert result.available is True
    assert result.version == "0.20.0"
    assert not (config.working_directory / "synced").exists()


def test_synchronize_runs_only_after_exact_version_inspection(tmp_path: Path) -> None:
    config = _config(tmp_path)

    result = VdirsyncerCalendarSynchronizer(config).synchronize()

    assert result.success is True
    assert (config.working_directory / "synced").read_text() == (
        f"--config|{config.configuration}|sync"
    )


def test_discover_runs_only_after_exact_version_inspection(tmp_path: Path) -> None:
    config = _config(tmp_path)

    result = VdirsyncerCalendarSynchronizer(config).discover()

    assert result.success is True
    assert (config.working_directory / "synced").read_text() == (
        f"--config|{config.configuration}|discover"
    )


def test_version_mismatch_prevents_synchronization(tmp_path: Path) -> None:
    config = _config(tmp_path, version="0.19.3")

    result = VdirsyncerCalendarSynchronizer(config).synchronize()

    assert result.success is False
    assert result.issues[0].code == "vdirsyncer_version_mismatch"
    assert not (config.working_directory / "synced").exists()
