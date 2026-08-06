"""Tests for finite calendar Python-version inspection."""

import hashlib
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

from lea.installers.calendar import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
    CalendarToolchainPythonVersionResult,
    create_calendar_toolchain_staging,
    inspect_calendar_python_version,
    inspect_staged_calendar_python_version,
)


def _make_executable(path: Path) -> None:
    """Create one executable test placeholder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _config(
    tmp_path: Path,
) -> CalendarToolchainInstallerConfig:
    """Return one managed verified-network configuration."""
    uv = tmp_path / "uv"
    python = tmp_path / "python3.13"
    lock = tmp_path / "requirements.lock"
    payload = b"khal==0.11.4\nvdirsyncer==0.19.3\n"

    _make_executable(uv)
    _make_executable(python)
    lock.write_bytes(payload)

    return CalendarToolchainInstallerConfig(
        mode=CalendarToolchainInstallMode.VERIFIED_NETWORK,
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
        expected_lock_sha256=hashlib.sha256(payload).hexdigest(),
        package_index_url="https://packages.example.invalid/simple",
        timeout_seconds=30.0,
    )


def test_inspection_runs_exact_non_shell_command(
    tmp_path: Path,
) -> None:
    """Python evidence should come from the exact managed executable."""
    python = tmp_path / "toolchain" / ".venv" / "bin" / "python"
    working = tmp_path / "toolchain"
    _make_executable(python)
    calls: list[dict[str, Any]] = []

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="3.13.5\n",
            stderr="",
        )

    result = inspect_calendar_python_version(
        python_executable=python,
        working_directory=working,
        timeout_seconds=12.0,
        runner=runner,
    )

    assert result.passed is True
    assert result.version == "3.13.5"
    assert result.command[0] == str(python)
    assert result.command[1] == "-c"
    assert "sys.version_info[:3]" in result.command[2]
    assert result.issues == ()
    assert len(calls) == 1
    assert calls[0]["cwd"] == working
    assert calls[0]["stdin"] == subprocess.DEVNULL
    assert calls[0]["capture_output"] is True
    assert calls[0]["text"] is True
    assert calls[0]["timeout"] == 12.0
    assert calls[0]["check"] is False
    assert calls[0]["shell"] is False


def test_staged_wrapper_uses_environment_python(
    tmp_path: Path,
) -> None:
    """The staged wrapper should inspect the staged .venv interpreter."""
    config = _config(tmp_path)
    staging = create_calendar_toolchain_staging(config)
    assert staging.staged is not None
    staged = staging.staged
    _make_executable(staged.environment_root / "bin" / "python")
    calls: list[tuple[str, ...]] = []

    def runner(
        command: tuple[str, ...],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="3.13.5\n",
            stderr="",
        )

    result = inspect_staged_calendar_python_version(
        config,
        staged,
        runner=runner,
    )

    assert result.passed is True
    assert calls[0][0] == str(staged.environment_root / "bin" / "python")


def test_non_zero_exit_is_structured(
    tmp_path: Path,
) -> None:
    """A failed interpreter process should fail closed."""
    python = tmp_path / "python"
    working = tmp_path / "working"
    _make_executable(python)
    working.mkdir()

    def runner(
        command: tuple[str, ...],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            2,
            stdout="",
            stderr="failed",
        )

    result = inspect_calendar_python_version(
        python_executable=python,
        working_directory=working,
        timeout_seconds=10.0,
        runner=runner,
    )

    assert result.passed is False
    assert result.version is None
    assert result.returncode == 2
    assert result.stderr == "failed"
    assert (
        result.issues[0].code
        is CalendarToolchainInstallFailureCode.VERSION_CHECK_FAILED
    )


def test_malformed_version_is_rejected(
    tmp_path: Path,
) -> None:
    """Only exact major.minor.micro evidence should be accepted."""
    python = tmp_path / "python"
    working = tmp_path / "working"
    _make_executable(python)
    working.mkdir()

    def runner(
        command: tuple[str, ...],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="Python 3.13.5\n",
            stderr="",
        )

    result = inspect_calendar_python_version(
        python_executable=python,
        working_directory=working,
        timeout_seconds=10.0,
        runner=runner,
    )

    assert result.passed is False
    assert result.version is None
    assert (
        result.issues[0].code
        is CalendarToolchainInstallFailureCode.VERSION_CHECK_FAILED
    )


def test_timeout_preserves_partial_diagnostics(
    tmp_path: Path,
) -> None:
    """A timeout should preserve bounded output and use timeout semantics."""
    python = tmp_path / "python"
    working = tmp_path / "working"
    _make_executable(python)
    working.mkdir()

    def runner(
        command: tuple[str, ...],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(
            command,
            10.0,
            output=b"partial stdout",
            stderr=b"partial stderr",
        )

    result = inspect_calendar_python_version(
        python_executable=python,
        working_directory=working,
        timeout_seconds=10.0,
        runner=runner,
    )

    assert result.passed is False
    assert result.timed_out is True
    assert result.returncode is None
    assert result.stdout == "partial stdout"
    assert result.stderr == "partial stderr"
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.INSTALL_TIMEOUT


def test_os_error_is_structured(
    tmp_path: Path,
) -> None:
    """Launch errors should not trigger PATH or shell fallback."""
    python = tmp_path / "python"
    working = tmp_path / "working"
    _make_executable(python)
    working.mkdir()

    def runner(
        command: tuple[str, ...],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        raise PermissionError("denied")

    result = inspect_calendar_python_version(
        python_executable=python,
        working_directory=working,
        timeout_seconds=10.0,
        runner=runner,
    )

    assert result.passed is False
    assert result.returncode == 127
    assert (
        result.issues[0].code
        is CalendarToolchainInstallFailureCode.VERSION_CHECK_FAILED
    )


def test_staged_wrapper_rejects_another_tools_root(
    tmp_path: Path,
) -> None:
    """Staged Python evidence must belong to the same installation."""
    first = _config(tmp_path / "first")
    second = _config(tmp_path / "second")
    staging = create_calendar_toolchain_staging(first)
    assert staging.staged is not None

    with pytest.raises(
        ValueError,
        match="does not belong",
    ):
        inspect_staged_calendar_python_version(
            second,
            staging.staged,
        )


def test_success_result_requires_version() -> None:
    """A passed result cannot omit the inspected Python version."""
    with pytest.raises(
        ValueError,
        match="must contain a version",
    ):
        CalendarToolchainPythonVersionResult(
            passed=True,
            version=None,
            command=("/tmp/python", "-c", "print('3.13.5')"),
            returncode=0,
            stdout="3.13.5\n",
            stderr="",
            duration_seconds=0.1,
            timed_out=False,
            issues=(),
        )
