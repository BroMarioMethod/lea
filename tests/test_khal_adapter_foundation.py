"""Tests for the deterministic khal adapter foundation."""

import json
import os
import stat
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from lea.adapters.khal import (
    KhalCommandResult,
    KhalConfig,
    KhalRunner,
    KhalRunResult,
    inspect_khal,
)


def make_executable(path: Path, body: str) -> None:
    """Create one executable Python helper script."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/usr/bin/env python3\n" + body,
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def make_config(
    tmp_path: Path,
    *,
    executable: Path,
    expected_version: str = "0.11.4",
    timeout_seconds: float = 2.0,
) -> KhalConfig:
    """Return one explicit isolated khal configuration."""
    configuration = tmp_path / "config" / "khal.conf"
    state_directory = tmp_path / "state"
    working_directory = tmp_path / "working"
    configuration.parent.mkdir(parents=True)
    configuration.write_text(
        "[locale]\nlocal_timezone = UTC\n",
        encoding="utf-8",
    )
    state_directory.mkdir()
    working_directory.mkdir()

    return KhalConfig(
        executable=executable,
        configuration=configuration,
        state_directory=state_directory,
        working_directory=working_directory,
        expected_version=expected_version,
        timeout_seconds=timeout_seconds,
    )


def test_config_is_immutable_and_requires_absolute_paths(
    tmp_path: Path,
) -> None:
    """Adapter configuration should be frozen and exact."""
    executable = tmp_path / "bin" / "khal"
    make_executable(executable, "print('ok')\n")
    config = make_config(tmp_path, executable=executable)

    with pytest.raises(FrozenInstanceError):
        config.expected_version = "changed"  # type: ignore[misc]

    with pytest.raises(ValueError, match="must be an absolute path"):
        KhalConfig(
            executable=Path("khal"),
            configuration=config.configuration,
            state_directory=config.state_directory,
            working_directory=config.working_directory,
            expected_version="0.11.4",
        )


def test_config_rejects_blank_version_and_invalid_timeout(
    tmp_path: Path,
) -> None:
    """Version and timeout policy should fail before execution."""
    executable = tmp_path / "bin" / "khal"
    make_executable(executable, "print('ok')\n")
    config = make_config(tmp_path, executable=executable)

    with pytest.raises(ValueError, match="expected_version"):
        KhalConfig(
            executable=config.executable,
            configuration=config.configuration,
            state_directory=config.state_directory,
            working_directory=config.working_directory,
            expected_version=" ",
        )

    with pytest.raises(ValueError, match="greater than zero"):
        KhalConfig(
            executable=config.executable,
            configuration=config.configuration,
            state_directory=config.state_directory,
            working_directory=config.working_directory,
            expected_version="0.11.4",
            timeout_seconds=0,
        )


def test_runner_uses_exact_command_and_isolated_environment(
    tmp_path: Path,
) -> None:
    """Configured runs should use explicit config and bounded environment."""
    executable = tmp_path / "bin" / "khal"
    make_executable(
        executable,
        (
            "import json, os, sys\n"
            "print(json.dumps({"
            "'argv': sys.argv[1:], "
            "'home': os.environ['HOME'], "
            "'xdg_config': os.environ['XDG_CONFIG_HOME'], "
            "'xdg_data': os.environ['XDG_DATA_HOME'], "
            "'xdg_cache': os.environ['XDG_CACHE_HOME'], "
            "'cwd': os.getcwd(), "
            "'no_color': os.environ['NO_COLOR']"
            "}))\n"
        ),
    )
    config = make_config(tmp_path, executable=executable)
    result = KhalRunner(config).run(
        ("printcalendars",),
        operation="list_calendars",
    )

    assert result.success is True
    assert result.command is not None
    payload = json.loads(result.command.stdout)
    assert result.command.arguments == (
        str(config.executable),
        "--no-color",
        "-c",
        str(config.configuration),
        "printcalendars",
    )
    assert payload["argv"] == [
        "--no-color",
        "-c",
        str(config.configuration),
        "printcalendars",
    ]
    assert payload["home"] == str(config.state_directory)
    assert payload["xdg_config"] == str(config.configuration.parent)
    assert payload["xdg_data"] == str(config.state_directory)
    assert payload["xdg_cache"] == str(config.state_directory)
    assert payload["cwd"] == str(config.working_directory)
    assert payload["no_color"] == "1"


def test_unconfigured_runner_uses_only_exact_version_command(
    tmp_path: Path,
) -> None:
    """Version probes must not address managed configuration or state."""
    executable = tmp_path / "bin" / "khal"
    make_executable(
        executable,
        (
            "import json, os, sys\n"
            "print(json.dumps({"
            "'argv': sys.argv[1:], "
            "'home': os.environ['HOME'], "
            "'xdg_config': os.environ.get('XDG_CONFIG_HOME'), "
            "'xdg_data': os.environ.get('XDG_DATA_HOME'), "
            "'xdg_cache': os.environ.get('XDG_CACHE_HOME')"
            "}))\n"
        ),
    )
    config = make_config(tmp_path, executable=executable)
    result = KhalRunner(
        config,
        base_environment={
            "HOME": "/untrusted",
            "XDG_CONFIG_HOME": "/untrusted/config",
            "XDG_DATA_HOME": "/untrusted/data",
            "XDG_CACHE_HOME": "/untrusted/cache",
        },
    ).run(
        ("--version",),
        operation="inspect",
        configured=False,
    )

    assert result.success is True
    assert result.command is not None
    assert result.command.arguments == (
        str(config.executable),
        "--version",
    )
    payload = json.loads(result.command.stdout)
    assert payload["argv"] == ["--version"]
    assert payload["home"] == str(config.working_directory)
    assert payload["xdg_config"] is None
    assert payload["xdg_data"] is None
    assert payload["xdg_cache"] is None


def test_runner_reports_missing_and_symbolic_executables(
    tmp_path: Path,
) -> None:
    """Unsafe executable paths should fail before process execution."""
    missing = tmp_path / "missing-khal"
    config = make_config(tmp_path, executable=missing)

    missing_result = KhalRunner(config).run(
        ("--version",),
        operation="inspect",
        configured=False,
    )

    assert missing_result.success is False
    assert missing_result.issues[0].code == "khal_executable_missing"

    target = tmp_path / "real-khal"
    make_executable(target, "print('ok')\n")
    symbolic = tmp_path / "symbolic-khal"
    symbolic.symlink_to(target)
    symbolic_config = KhalConfig(
        executable=symbolic,
        configuration=config.configuration,
        state_directory=config.state_directory,
        working_directory=config.working_directory,
        expected_version="0.11.4",
    )

    symbolic_result = KhalRunner(symbolic_config).run(
        ("--version",),
        operation="inspect",
        configured=False,
    )

    assert symbolic_result.success is False
    assert symbolic_result.issues[0].code == "khal_executable_invalid"


def test_runner_reports_missing_configured_runtime(
    tmp_path: Path,
) -> None:
    """Configured operations should require config and state paths."""
    executable = tmp_path / "bin" / "khal"
    make_executable(executable, "print('ok')\n")
    config = make_config(tmp_path, executable=executable)
    config.configuration.unlink()

    result = KhalRunner(config).run(
        ("printcalendars",),
        operation="list_calendars",
    )

    assert result.success is False
    assert result.issues[0].code == "khal_configuration_missing"


def test_runner_reports_timeout_and_non_zero_exit(
    tmp_path: Path,
) -> None:
    """Timeouts and process statuses should remain distinct."""
    timeout_executable = tmp_path / "timeout" / "khal"
    make_executable(
        timeout_executable,
        "import time\ntime.sleep(2)\n",
    )
    timeout_config = make_config(
        tmp_path / "timeout-config",
        executable=timeout_executable,
        timeout_seconds=0.05,
    )
    timeout_result = KhalRunner(timeout_config).run(
        ("--version",),
        operation="inspect",
        configured=False,
    )

    assert timeout_result.success is False
    assert timeout_result.issues[0].code == "khal_process_timeout"

    failing_executable = tmp_path / "failing" / "khal"
    make_executable(
        failing_executable,
        (
            "import sys\n"
            "print('diagnostic stdout')\n"
            "print('diagnostic stderr', file=sys.stderr)\n"
            "raise SystemExit(7)\n"
        ),
    )
    failing_config = make_config(
        tmp_path / "failing-config",
        executable=failing_executable,
    )
    failing_result = KhalRunner(failing_config).run(
        ("--version",),
        operation="inspect",
        configured=False,
    )

    assert failing_result.success is False
    assert failing_result.command is not None
    assert failing_result.command.return_code == 7
    assert failing_result.issues[0].code == "khal_process_failed"
    assert failing_result.issues[0].return_code == 7


def test_runner_rejects_invalid_utf8_and_blank_arguments(
    tmp_path: Path,
) -> None:
    """Malformed output and arguments should fail closed."""
    executable = tmp_path / "bin" / "khal"
    make_executable(
        executable,
        "import sys\nsys.stdout.buffer.write(b'\\xff')\n",
    )
    config = make_config(tmp_path, executable=executable)
    result = KhalRunner(config).run(
        ("--version",),
        operation="inspect",
        configured=False,
    )

    assert result.success is False
    assert result.issues[0].code == "khal_output_invalid_utf8"

    with pytest.raises(ValueError, match="non-empty strings"):
        KhalRunner(config).run(
            ("",),
            operation="inspect",
        )


def test_runner_does_not_change_parent_environment(
    tmp_path: Path,
) -> None:
    """Child environment construction must not mutate os.environ."""
    executable = tmp_path / "bin" / "khal"
    make_executable(executable, "print('ok')\n")
    config = make_config(tmp_path, executable=executable)
    original_home = os.environ.get("HOME")

    result = KhalRunner(config).run(
        ("--version",),
        operation="inspect",
        configured=False,
    )

    assert result.success is True
    assert os.environ.get("HOME") == original_home


def test_supported_version_is_available(tmp_path: Path) -> None:
    """The exact configured khal version should pass inspection."""
    executable = tmp_path / "bin" / "khal"
    make_executable(
        executable,
        "print('khal, version 0.11.4')\n",
    )
    config = make_config(tmp_path, executable=executable)
    result = inspect_khal(config)

    assert result.available is True
    assert result.provider == "khal"
    assert result.version == "0.11.4"
    assert result.issues == ()


def test_version_may_be_reported_on_stderr(tmp_path: Path) -> None:
    """Inspection should accept the proven khal stderr version format."""
    executable = tmp_path / "bin" / "khal"
    make_executable(
        executable,
        ("import sys\nprint('khal, version 0.11.4', file=sys.stderr)\n"),
    )
    config = make_config(tmp_path, executable=executable)
    result = inspect_khal(config)

    assert result.available is True
    assert result.version == "0.11.4"


def test_unsupported_and_malformed_versions_fail(
    tmp_path: Path,
) -> None:
    """Inspection should fail closed on unexpected version output."""
    unsupported = tmp_path / "unsupported" / "khal"
    make_executable(
        unsupported,
        "print('khal, version 0.10.0')\n",
    )
    unsupported_config = make_config(
        tmp_path / "unsupported-config",
        executable=unsupported,
    )
    unsupported_result = inspect_khal(unsupported_config)

    assert unsupported_result.available is False
    assert unsupported_result.issues[0].code == ("khal_unsupported_version")

    malformed = tmp_path / "malformed" / "khal"
    make_executable(malformed, "print('version unknown')\n")
    malformed_config = make_config(
        tmp_path / "malformed-config",
        executable=malformed,
    )
    malformed_result = inspect_khal(malformed_config)

    assert malformed_result.available is False
    assert malformed_result.issues[0].code == ("khal_version_output_invalid")


def test_inspection_preserves_bounded_process_diagnostics(
    tmp_path: Path,
) -> None:
    """Executed failures should expose compact bounded diagnostics."""
    executable = tmp_path / "bin" / "khal"
    make_executable(
        executable,
        (
            "import sys\n"
            "print('inspection stdout')\n"
            "print('inspection stderr', file=sys.stderr)\n"
            "raise SystemExit(9)\n"
        ),
    )
    config = make_config(tmp_path, executable=executable)
    result = inspect_khal(config)

    assert result.available is False
    assert result.issues[0].code == "khal_process_failed"
    assert result.issues[0].return_code == 9
    assert "inspection stderr" in result.issues[0].message
    assert "inspection stdout" in result.issues[0].message


def test_inspection_requires_runtime_paths(tmp_path: Path) -> None:
    """Provider inspection should require the complete local runtime."""
    executable = tmp_path / "bin" / "khal"
    make_executable(
        executable,
        "print('khal, version 0.11.4')\n",
    )
    config = make_config(tmp_path, executable=executable)
    config.state_directory.rmdir()
    result = inspect_khal(config)

    assert result.available is False
    assert result.issues[0].code == "khal_state_directory_missing"


def test_runner_and_result_contracts_are_consistent(
    tmp_path: Path,
) -> None:
    """Runner construction and result contracts should reject ambiguity."""
    executable = tmp_path / "bin" / "khal"
    make_executable(executable, "print('ok')\n")
    make_config(tmp_path, executable=executable)

    with pytest.raises(TypeError, match="KhalConfig"):
        KhalRunner(object())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="must contain a command result"):
        KhalRunResult(success=True, command=None, issues=())

    with pytest.raises(ValueError, match="at least the executable"):
        KhalCommandResult(
            arguments=(),
            return_code=0,
            stdout="",
            stderr="",
            duration_seconds=0,
        )
