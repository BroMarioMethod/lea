"""Tests for the top-level release-candidate shell wrappers."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INSTALL_WRAPPER = REPOSITORY_ROOT / "install.sh"
UNINSTALL_WRAPPER = REPOSITORY_ROOT / "uninstall.sh"

TASKWARRIOR_SHA256 = "d302761fcd1268e4a5a545613a2b68c61abd50c0bcaade3b3e68d728dd02e716"
CALENDAR_REQUIREMENTS_SHA256 = (
    "f5f7a0749b993e49bbd50b8807242611fff1dbc2477a59a4a292c0aa42420ba5"
)
CALENDAR_REQUIREMENTS_LOCK = (
    REPOSITORY_ROOT
    / "third_party"
    / "calendar"
    / "requirements-linux-aarch64-py313.txt"
)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _environment(
    tmp_path: Path,
    *,
    user_id: str = "0",
    uv_exit: str = "0",
) -> tuple[dict[str, str], Path, Path]:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()

    fake_id = fake_bin / "id"
    _write_executable(
        fake_id,
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-u" ]]; then
    printf '%s\\n' "${LEA_TEST_UID:-0}"
    exit 0
fi
exit 2
""",
    )

    arguments_file = tmp_path / "uv-arguments.txt"
    working_directory_file = tmp_path / "uv-working-directory.txt"
    fake_uv = tmp_path / "uv"
    _write_executable(
        fake_uv,
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$PWD" > "$LEA_TEST_WORKING_DIRECTORY_FILE"
printf '%s\\n' "$@" > "$LEA_TEST_ARGUMENTS_FILE"
exit "${LEA_TEST_UV_EXIT:-0}"
""",
    )

    fake_python = tmp_path / "python3.13"
    _write_executable(
        fake_python,
        """#!/usr/bin/env bash
set -euo pipefail
exit 0
""",
    )

    environment = dict(os.environ)
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "LEA_TEST_UID": user_id,
            "LEA_TEST_UV_EXIT": uv_exit,
            "LEA_TEST_ARGUMENTS_FILE": str(arguments_file),
            "LEA_TEST_WORKING_DIRECTORY_FILE": str(working_directory_file),
            "LEA_UV_BIN": str(fake_uv),
            "LEA_CALENDAR_PYTHON_BIN": str(fake_python),
        }
    )
    return environment, arguments_file, working_directory_file


def _run(
    wrapper: Path,
    arguments: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(wrapper), *arguments],
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _captured_arguments(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_wrapper_scripts_are_executable_and_valid_bash() -> None:
    for wrapper in (INSTALL_WRAPPER, UNINSTALL_WRAPPER):
        assert wrapper.stat().st_mode & stat.S_IXUSR
        result = subprocess.run(
            ["bash", "-n", str(wrapper)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert result.stderr == ""


def test_install_wrapper_supplies_pinned_defaults_and_user_arguments(
    tmp_path: Path,
) -> None:
    environment, arguments_file, working_directory_file = _environment(tmp_path)

    result = _run(
        INSTALL_WRAPPER,
        [
            "--mode",
            "repair",
            "--display-timezone",
            "Africa/Gaborone",
            "--no-telegram",
            "--approve",
            "--approve-replacement",
        ],
        cwd=tmp_path,
        environment=environment,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert working_directory_file.read_text(encoding="utf-8").strip() == str(
        REPOSITORY_ROOT
    )
    assert _captured_arguments(arguments_file) == [
        "run",
        "lea",
        "install-release-candidate",
        "--taskwarrior-source-archive",
        "/opt/lea-release-assets/task-3.4.2.tar.gz",
        "--taskwarrior-sha256",
        TASKWARRIOR_SHA256,
        "--taskwarrior-version",
        "3.4.2",
        "--taskwarrior-platform",
        "linux-aarch64",
        "--taskwarrior-build-directory",
        "/var/tmp/lea-taskwarrior-build",
        "--taskwarrior-build-concurrency",
        "1",
        "--calendar-requirements-lock",
        str(CALENDAR_REQUIREMENTS_LOCK),
        "--calendar-requirements-sha256",
        CALENDAR_REQUIREMENTS_SHA256,
        "--calendar-uv-executable",
        environment["LEA_UV_BIN"],
        "--calendar-python-executable",
        environment["LEA_CALENDAR_PYTHON_BIN"],
        "--calendar-package-index-url",
        "https://pypi.org/simple",
        "--calendar-toolchain-version",
        "1.0.0",
        "--calendar-platform",
        "linux-aarch64",
        "--calendar-khal-version",
        "0.11.4",
        "--calendar-vdirsyncer-version",
        "0.19.3",
        "--mode",
        "repair",
        "--display-timezone",
        "Africa/Gaborone",
        "--no-telegram",
        "--approve",
        "--approve-replacement",
    ]


def test_install_help_does_not_require_root(tmp_path: Path) -> None:
    environment, arguments_file, _ = _environment(tmp_path, user_id="1000")

    result = _run(
        INSTALL_WRAPPER,
        ["--help"],
        cwd=tmp_path,
        environment=environment,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert _captured_arguments(arguments_file)[-1] == "--help"


def test_install_requires_root_for_mutating_runs(tmp_path: Path) -> None:
    environment, arguments_file, _ = _environment(tmp_path, user_id="1000")

    result = _run(
        INSTALL_WRAPPER,
        ["--no-telegram"],
        cwd=tmp_path,
        environment=environment,
    )

    assert result.returncode == 1
    assert "must be run as root" in result.stderr
    assert not arguments_file.exists()


def test_install_preserves_uv_exit_status(tmp_path: Path) -> None:
    environment, _, _ = _environment(tmp_path, uv_exit="37")

    result = _run(
        INSTALL_WRAPPER,
        ["--help"],
        cwd=tmp_path,
        environment=environment,
    )

    assert result.returncode == 37


def test_install_rejects_an_incomplete_repository(tmp_path: Path) -> None:
    orphan = tmp_path / "orphan"
    orphan.mkdir()
    wrapper = orphan / "install.sh"
    wrapper.write_text(INSTALL_WRAPPER.read_text(encoding="utf-8"), encoding="utf-8")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)

    environment, arguments_file, _ = _environment(tmp_path)

    result = _run(
        wrapper,
        ["--help"],
        cwd=tmp_path,
        environment=environment,
    )

    assert result.returncode == 1
    assert "repository is incomplete" in result.stderr
    assert not arguments_file.exists()


def test_uninstall_wrapper_adds_purge_and_preserves_confirmation(
    tmp_path: Path,
) -> None:
    environment, arguments_file, working_directory_file = _environment(tmp_path)

    result = _run(
        UNINSTALL_WRAPPER,
        ["--yes"],
        cwd=tmp_path,
        environment=environment,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert working_directory_file.read_text(encoding="utf-8").strip() == str(
        REPOSITORY_ROOT
    )
    assert _captured_arguments(arguments_file) == [
        "run",
        "lea",
        "uninstall-release-candidate",
        "--purge",
        "--yes",
    ]


def test_uninstall_help_does_not_require_root(tmp_path: Path) -> None:
    environment, arguments_file, _ = _environment(tmp_path, user_id="1000")

    result = _run(
        UNINSTALL_WRAPPER,
        ["--help"],
        cwd=tmp_path,
        environment=environment,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert _captured_arguments(arguments_file) == [
        "run",
        "lea",
        "uninstall-release-candidate",
        "--purge",
        "--help",
    ]


def test_uninstall_rejects_unsupported_wrapper_arguments(
    tmp_path: Path,
) -> None:
    environment, arguments_file, _ = _environment(tmp_path)

    result = _run(
        UNINSTALL_WRAPPER,
        ["--quiet"],
        cwd=tmp_path,
        environment=environment,
    )

    assert result.returncode == 2
    assert "Unsupported uninstall wrapper argument" in result.stderr
    assert not arguments_file.exists()
