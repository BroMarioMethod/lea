"""Tests for Taskwarrior provider inspection."""

import stat
from pathlib import Path

from lea.adapters.taskwarrior import (
    TaskwarriorConfig,
    inspect_taskwarrior,
)


def make_executable(
    path: Path,
    *,
    version: str,
) -> None:
    """Create one version-reporting executable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (f"#!/usr/bin/env python3\nimport sys\nprint({version!r})\n"),
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def make_config(
    tmp_path: Path,
    *,
    version: str = "3.4.2",
) -> TaskwarriorConfig:
    """Return one isolated inspection configuration."""
    executable = tmp_path / "bin" / "task"
    taskrc = tmp_path / "config" / "taskrc"
    data_dir = tmp_path / "data"
    home_dir = tmp_path / "home"

    make_executable(executable, version=version)
    taskrc.parent.mkdir(parents=True)
    taskrc.write_text("hooks=0\n", encoding="utf-8")
    data_dir.mkdir()
    home_dir.mkdir()

    return TaskwarriorConfig(
        executable=executable,
        taskrc=taskrc,
        data_dir=data_dir,
        home_dir=home_dir,
    )


def test_supported_version_is_available(
    tmp_path: Path,
) -> None:
    """Taskwarrior 3.4.x should pass inspection."""
    result = inspect_taskwarrior(make_config(tmp_path))

    assert result.available is True
    assert result.provider == "taskwarrior"
    assert result.version == "3.4.2"
    assert result.issues == ()


def test_unsupported_version_fails(
    tmp_path: Path,
) -> None:
    """Taskwarrior 2.x should not pass the primary provider policy."""
    result = inspect_taskwarrior(make_config(tmp_path, version="2.6.2"))

    assert result.available is False
    assert result.version is None
    assert result.issues[0].code == "taskwarrior_unsupported_version"


def test_missing_taskrc_fails(
    tmp_path: Path,
) -> None:
    """Inspection should require the explicit configuration file."""
    config = make_config(tmp_path)
    config.taskrc.unlink()

    result = inspect_taskwarrior(config)

    assert result.available is False
    assert result.issues[0].code == "taskwarrior_configuration_invalid"


def test_missing_data_directory_fails(
    tmp_path: Path,
) -> None:
    """Inspection should require an explicit data directory."""
    config = make_config(tmp_path)
    config.data_dir.rmdir()

    result = inspect_taskwarrior(config)

    assert result.available is False
    assert result.issues[0].code == "taskwarrior_data_directory_missing"


def test_missing_executable_issue_is_preserved(
    tmp_path: Path,
) -> None:
    """Runner failures should pass through inspection unchanged."""
    config = make_config(tmp_path)
    config.executable.unlink()

    result = inspect_taskwarrior(config)

    assert result.available is False
    assert result.issues[0].code == "taskwarrior_executable_missing"
