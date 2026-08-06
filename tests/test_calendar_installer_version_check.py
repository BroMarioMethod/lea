"""Tests for exact staged calendar tool version checks."""

import hashlib
import stat
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from lea.installers.calendar import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
    CalendarToolchainStagingLayout,
    CalendarToolchainVersionCheckResult,
    CalendarToolchainVersionStepResult,
    create_calendar_toolchain_staging,
    validate_calendar_tool_versions,
    validate_staged_calendar_tool_versions,
)


def _make_executable(path: Path) -> None:
    """Create one executable test-double path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _config(
    tmp_path: Path,
) -> CalendarToolchainInstallerConfig:
    """Return one staged verified-network configuration."""
    uv_executable = tmp_path / "uv"
    python_executable = tmp_path / "python3"
    requirements_lock = tmp_path / "requirements.lock"
    payload = b"khal==0.11.4\nvdirsyncer==0.19.3\n"

    _make_executable(uv_executable)
    _make_executable(python_executable)
    requirements_lock.write_bytes(payload)

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
        uv_executable=uv_executable,
        python_executable=python_executable,
        requirements_lock=requirements_lock,
        expected_lock_sha256=hashlib.sha256(payload).hexdigest(),
        package_index_url="https://packages.example.invalid/simple",
        timeout_seconds=30.0,
    )


def _staged(
    tmp_path: Path,
) -> tuple[
    CalendarToolchainInstallerConfig,
    CalendarToolchainStagingLayout,
]:
    """Return one configuration and successful private staging layout."""
    config = _config(tmp_path)
    staging = create_calendar_toolchain_staging(config)
    assert staging.staged is not None
    _make_executable(staging.staged.khal_executable)
    _make_executable(staging.staged.vdirsyncer_executable)
    return config, staging.staged


def test_staged_version_check_accepts_exact_versions(
    tmp_path: Path,
) -> None:
    """Both pinned versions should pass through exact executable paths."""
    config, staged = _staged(tmp_path)
    calls: list[dict[str, Any]] = []

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, **kwargs})

        if command[0] == str(staged.khal_executable):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="khal, version 0.11.4\n",
                stderr="",
            )

        return subprocess.CompletedProcess(
            command,
            0,
            stdout="",
            stderr="vdirsyncer, version 0.19.3\n",
        )

    result = validate_staged_calendar_tool_versions(
        config,
        staged,
        runner=runner,
    )

    assert result.passed is True
    assert result.khal_version == "0.11.4"
    assert result.vdirsyncer_version == "0.19.3"
    assert result.issues == ()
    assert [call["command"] for call in calls] == [
        (str(staged.khal_executable), "--version"),
        (str(staged.vdirsyncer_executable), "--version"),
    ]

    for call in calls:
        assert call["cwd"] == staged.staging_root
        assert call["stdin"] == subprocess.DEVNULL
        assert call["capture_output"] is True
        assert call["text"] is True
        assert call["timeout"] == config.timeout_seconds
        assert call["check"] is False
        assert call["shell"] is False


def test_khal_version_mismatch_stops_vdirsyncer_check(
    tmp_path: Path,
) -> None:
    """An unsupported first tool should fail before checking the second."""
    config, staged = _staged(tmp_path)
    calls: list[tuple[str, ...]] = []

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="khal, version 0.11.5\n",
            stderr="",
        )

    result = validate_staged_calendar_tool_versions(
        config,
        staged,
        runner=runner,
    )

    assert result.passed is False
    assert calls == [(str(staged.khal_executable), "--version")]
    assert result.khal_version == "0.11.5"
    assert result.vdirsyncer_version is None
    assert (
        result.issues[0].code
        is CalendarToolchainInstallFailureCode.VERSION_CHECK_FAILED
    )
    assert result.issues[0].field == "khal_version"


def test_non_zero_version_command_fails_closed(
    tmp_path: Path,
) -> None:
    """A non-zero tool command should become a version-check issue."""
    config, staged = _staged(tmp_path)

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            9,
            stdout="",
            stderr="broken executable",
        )

    result = validate_staged_calendar_tool_versions(
        config,
        staged,
        runner=runner,
    )

    assert result.passed is False
    assert result.steps[0].returncode == 9
    assert result.steps[0].stderr == "broken executable"
    assert (
        result.issues[0].code
        is CalendarToolchainInstallFailureCode.VERSION_CHECK_FAILED
    )


def test_unrecognised_version_output_fails_closed(
    tmp_path: Path,
) -> None:
    """Successful commands must still emit the supported exact format."""
    config, staged = _staged(tmp_path)

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="0.11.4\n",
            stderr="",
        )

    result = validate_staged_calendar_tool_versions(
        config,
        staged,
        runner=runner,
    )

    assert result.passed is False
    assert result.steps[0].discovered_version is None
    assert result.issues[0].field == "khal_version"


def test_version_timeout_preserves_partial_diagnostics(
    tmp_path: Path,
) -> None:
    """A finite timeout should preserve captured output and stop."""
    config, staged = _staged(tmp_path)

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(
            command,
            config.timeout_seconds,
            output=b"partial stdout",
            stderr=b"partial stderr",
        )

    result = validate_staged_calendar_tool_versions(
        config,
        staged,
        runner=runner,
    )

    assert result.passed is False
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.INSTALL_TIMEOUT
    assert result.steps[0].timed_out is True
    assert result.steps[0].returncode is None
    assert result.steps[0].stdout == "partial stdout"
    assert result.steps[0].stderr == "partial stderr"


def test_version_os_error_is_structured(
    tmp_path: Path,
) -> None:
    """Launch failures should not cause shell or PATH fallback."""
    config, staged = _staged(tmp_path)

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        raise PermissionError("denied")

    result = validate_staged_calendar_tool_versions(
        config,
        staged,
        runner=runner,
    )

    assert result.passed is False
    assert result.steps[0].returncode == 127
    assert (
        result.issues[0].code
        is CalendarToolchainInstallFailureCode.VERSION_CHECK_FAILED
    )
    assert result.issues[0].path == staged.khal_executable


def test_generic_version_check_supports_explicit_external_paths(
    tmp_path: Path,
) -> None:
    """The reusable boundary should not depend on managed staging."""
    khal = tmp_path / "external" / "khal"
    vdirsyncer = tmp_path / "external" / "vdirsyncer"
    working_directory = tmp_path / "working"
    _make_executable(khal)
    _make_executable(vdirsyncer)
    working_directory.mkdir()

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        name = Path(command[0]).name
        version = "0.11.4" if name == "khal" else "0.19.3"
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"{name}, version {version}\n",
            stderr="",
        )

    result = validate_calendar_tool_versions(
        khal_executable=khal,
        expected_khal_version="0.11.4",
        vdirsyncer_executable=vdirsyncer,
        expected_vdirsyncer_version="0.19.3",
        working_directory=working_directory,
        timeout_seconds=30.0,
        runner=runner,
    )

    assert result.passed is True


def test_staged_version_check_rejects_unrelated_tools_root(
    tmp_path: Path,
) -> None:
    """Configuration and staging must belong to the same installation."""
    first_config, first_staged = _staged(tmp_path / "first")
    second_config = replace(
        first_config,
        tools_root=tmp_path / "second" / "tools",
    )

    with pytest.raises(
        ValueError,
        match="does not belong to the configured tools root",
    ):
        validate_staged_calendar_tool_versions(
            second_config,
            first_staged,
        )


def test_version_result_contract_rejects_incomplete_success(
    tmp_path: Path,
) -> None:
    """Successful result contracts must contain both tool versions."""
    step = CalendarToolchainVersionStepResult(
        tool="khal",
        command=("/tmp/khal", "--version"),
        returncode=0,
        stdout="khal, version 0.11.4\n",
        stderr="",
        duration_seconds=0.1,
        timed_out=False,
        discovered_version="0.11.4",
    )

    with pytest.raises(
        ValueError,
        match="vdirsyncer version",
    ):
        CalendarToolchainVersionCheckResult(
            passed=True,
            khal_version="0.11.4",
            vdirsyncer_version=None,
            steps=(step, step),
            issues=(),
        )
