"""Tests for disposable local-only calendar toolchain smoke tests."""

import hashlib
import stat
import subprocess
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from lea.installers.calendar import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallFailureCode,
    CalendarToolchainInstallMode,
    CalendarToolchainSmokeStepResult,
    CalendarToolchainSmokeTestResult,
    CalendarToolchainStagingLayout,
    create_calendar_toolchain_staging,
    run_calendar_toolchain_smoke_test,
    run_staged_calendar_toolchain_smoke_test,
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


def _successful_runner(
    calls: list[dict[str, Any]],
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Return one injected runner that simulates the real smoke sequence."""

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, **kwargs})
        cwd = kwargs["cwd"]
        phase = command[-1]

        if phase == "showconfig":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    '{"storages": ['
                    '{"instance_name": "smoke_source"}, '
                    '{"instance_name": "smoke_target"}'
                    "]}\n"
                ),
                stderr="",
            )

        if phase == "smoke":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="",
                stderr='Saved for smoke: collections = ["default"]\n',
            )

        if phase == "smoke/default":
            target = cwd / "target" / "default" / "copied.ics"
            target.write_text(
                (
                    "BEGIN:VCALENDAR\n"
                    "BEGIN:VEVENT\n"
                    "UID:lea-calendar-smoke@example.invalid\n"
                    "SUMMARY:LEA calendar smoke test\n"
                    "END:VEVENT\n"
                    "END:VCALENDAR\n"
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="",
                stderr="Syncing smoke/default\n",
            )

        if phase == "printcalendars":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="smoke\n",
                stderr="",
            )

        return subprocess.CompletedProcess(
            command,
            0,
            stdout=("Thursday, 2099-01-01\n09:00-10:00 LEA calendar smoke test\n"),
            stderr="",
        )

    return runner


def test_staged_smoke_test_runs_exact_local_sequence(
    tmp_path: Path,
) -> None:
    """The complete local-only sequence should pass and clean itself."""
    config, staged = _staged(tmp_path)
    calls: list[dict[str, Any]] = []

    result = run_staged_calendar_toolchain_smoke_test(
        config,
        staged,
        runner=_successful_runner(calls),
    )

    assert result.passed is True
    assert result.issues == ()
    assert tuple(step.phase for step in result.steps) == (
        "vdirsyncer-showconfig",
        "vdirsyncer-discover",
        "vdirsyncer-sync",
        "khal-printcalendars",
        "khal-list",
    )
    assert len(calls) == 5

    smoke_root = calls[0]["cwd"]
    assert isinstance(smoke_root, Path)
    assert not smoke_root.exists()

    assert calls[0]["command"][0] == str(staged.vdirsyncer_executable)
    assert calls[-1]["command"][0] == str(staged.khal_executable)

    for call in calls:
        assert call["cwd"] == smoke_root
        assert call["stdin"] == subprocess.DEVNULL
        assert call["capture_output"] is True
        assert call["text"] is True
        assert call["timeout"] == config.timeout_seconds
        assert call["check"] is False
        assert call["shell"] is False
        assert call["env"]["HOME"].startswith(str(smoke_root))
        assert call["env"]["XDG_CONFIG_HOME"].startswith(str(smoke_root))
        assert call["env"]["TZ"] == "UTC"
        assert call["env"]["PYTHONNOUSERSITE"] == "1"


def test_non_zero_smoke_command_stops_sequence(
    tmp_path: Path,
) -> None:
    """A failed command should stop before subsequent smoke phases."""
    config, staged = _staged(tmp_path)
    calls: list[tuple[str, ...]] = []

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            4,
            stdout="",
            stderr="invalid configuration",
        )

    result = run_staged_calendar_toolchain_smoke_test(
        config,
        staged,
        runner=runner,
    )

    assert result.passed is False
    assert len(calls) == 1
    assert result.steps[0].returncode == 4
    assert result.steps[0].stderr == "invalid configuration"
    assert (
        result.issues[0].code is CalendarToolchainInstallFailureCode.SMOKE_TEST_FAILED
    )


def test_smoke_timeout_preserves_partial_output(
    tmp_path: Path,
) -> None:
    """A finite timeout should preserve diagnostics and clean staging."""
    config, staged = _staged(tmp_path)
    roots: list[Path] = []

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        roots.append(kwargs["cwd"])
        raise subprocess.TimeoutExpired(
            command,
            config.timeout_seconds,
            output=b"partial stdout",
            stderr=b"partial stderr",
        )

    result = run_staged_calendar_toolchain_smoke_test(
        config,
        staged,
        runner=runner,
    )

    assert result.passed is False
    assert result.issues[0].code is CalendarToolchainInstallFailureCode.INSTALL_TIMEOUT
    assert result.steps[0].timed_out is True
    assert result.steps[0].stdout == "partial stdout"
    assert result.steps[0].stderr == "partial stderr"
    assert roots and not roots[0].exists()


def test_smoke_os_error_is_structured(
    tmp_path: Path,
) -> None:
    """Launch failures should not cause a shell or PATH fallback."""
    config, staged = _staged(tmp_path)

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        raise PermissionError("denied")

    result = run_staged_calendar_toolchain_smoke_test(
        config,
        staged,
        runner=runner,
    )

    assert result.passed is False
    assert result.steps[0].returncode == 127
    assert (
        result.issues[0].code is CalendarToolchainInstallFailureCode.SMOKE_TEST_FAILED
    )


def test_showconfig_requires_both_filesystem_storages(
    tmp_path: Path,
) -> None:
    """Configuration parsing must expose both disposable storages."""
    config, staged = _staged(tmp_path)

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"storages": []}\n',
            stderr="",
        )

    result = run_staged_calendar_toolchain_smoke_test(
        config,
        staged,
        runner=runner,
    )

    assert result.passed is False
    assert len(result.steps) == 1
    assert result.issues[0].field == "vdirsyncer_config"


def test_sync_requires_one_preserved_calendar_item(
    tmp_path: Path,
) -> None:
    """A zero exit status without copied event data must fail closed."""
    config, staged = _staged(tmp_path)
    calls: list[dict[str, Any]] = []

    good_runner = _successful_runner(calls)

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        if command[-1] == "smoke/default":
            calls.append({"command": command, **kwargs})
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="",
                stderr="Syncing smoke/default\n",
            )

        return good_runner(command, **kwargs)

    result = run_staged_calendar_toolchain_smoke_test(
        config,
        staged,
        runner=runner,
    )

    assert result.passed is False
    assert len(result.steps) == 3
    assert result.issues[0].field == "target_collection"


def test_khal_calendar_discovery_must_include_smoke(
    tmp_path: Path,
) -> None:
    """khal must load the explicit disposable calendar configuration."""
    config, staged = _staged(tmp_path)
    calls: list[dict[str, Any]] = []
    good_runner = _successful_runner(calls)

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        if command[-1] == "printcalendars":
            calls.append({"command": command, **kwargs})
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="other\n",
                stderr="",
            )

        return good_runner(command, **kwargs)

    result = run_staged_calendar_toolchain_smoke_test(
        config,
        staged,
        runner=runner,
    )

    assert result.passed is False
    assert len(result.steps) == 4
    assert result.issues[0].field == "khal_config"


def test_khal_list_must_read_synthetic_event(
    tmp_path: Path,
) -> None:
    """khal must read the event copied by vdirsyncer."""
    config, staged = _staged(tmp_path)
    calls: list[dict[str, Any]] = []
    good_runner = _successful_runner(calls)

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        if command[-3:] == (
            "list",
            "2099-01-01",
            "2099-01-02",
        ):
            calls.append({"command": command, **kwargs})
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="Thursday, 2099-01-01\n",
                stderr="",
            )

        return good_runner(command, **kwargs)

    result = run_staged_calendar_toolchain_smoke_test(
        config,
        staged,
        runner=runner,
    )

    assert result.passed is False
    assert len(result.steps) == 5
    assert result.issues[0].field == "target_collection"


def test_generic_smoke_test_supports_explicit_external_paths(
    tmp_path: Path,
) -> None:
    """The reusable smoke boundary should not depend on managed staging."""
    khal = tmp_path / "external" / "khal"
    vdirsyncer = tmp_path / "external" / "vdirsyncer"
    working_directory = tmp_path / "working"
    _make_executable(khal)
    _make_executable(vdirsyncer)
    working_directory.mkdir()
    calls: list[dict[str, Any]] = []

    result = run_calendar_toolchain_smoke_test(
        khal_executable=khal,
        vdirsyncer_executable=vdirsyncer,
        working_directory=working_directory,
        timeout_seconds=30.0,
        runner=_successful_runner(calls),
    )

    assert result.passed is True


def test_staged_smoke_test_rejects_unrelated_tools_root(
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
        run_staged_calendar_toolchain_smoke_test(
            second_config,
            first_staged,
        )


def test_smoke_result_contract_rejects_incomplete_success() -> None:
    """Successful result contracts must contain all five phases."""
    step = CalendarToolchainSmokeStepResult(
        phase="one",
        command=("/tmp/tool", "command"),
        returncode=0,
        stdout="",
        stderr="",
        duration_seconds=0.1,
        timed_out=False,
    )

    with pytest.raises(
        ValueError,
        match="five completed steps",
    ):
        CalendarToolchainSmokeTestResult(
            passed=True,
            steps=(step,),
            issues=(),
        )
