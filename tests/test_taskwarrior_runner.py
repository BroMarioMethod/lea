"""Tests for safe Taskwarrior subprocess execution."""

import os
import stat
from pathlib import Path

import pytest

from lea.adapters.taskwarrior import (
    TaskwarriorConfig,
    TaskwarriorRunner,
)


def make_executable(
    path: Path,
    body: str,
) -> None:
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
    timeout_seconds: float = 2.0,
) -> TaskwarriorConfig:
    """Return one explicit isolated runner configuration."""
    taskrc = tmp_path / "config" / "taskrc"
    data_dir = tmp_path / "data"
    home_dir = tmp_path / "home"
    working_dir = tmp_path / "working"

    taskrc.parent.mkdir(parents=True)
    taskrc.write_text("hooks=0\n", encoding="utf-8")
    data_dir.mkdir()
    home_dir.mkdir()
    working_dir.mkdir()

    return TaskwarriorConfig(
        executable=executable,
        taskrc=taskrc,
        data_dir=data_dir,
        home_dir=home_dir,
        timeout_seconds=timeout_seconds,
        working_dir=working_dir,
    )


def test_runner_uses_exact_arguments_and_environment(
    tmp_path: Path,
) -> None:
    """Runner should pass explicit paths without a shell."""
    executable = tmp_path / "bin" / "task"
    make_executable(
        executable,
        (
            "import json, os, sys\n"
            "print(json.dumps({"
            "'argv': sys.argv[1:], "
            "'home': os.environ['HOME'], "
            "'taskrc': os.environ['TASKRC'], "
            "'cwd': os.getcwd()"
            "}))\n"
        ),
    )
    config = make_config(tmp_path, executable=executable)
    runner = TaskwarriorRunner(config, base_environment={"LANG": "C"})

    result = runner.run(
        ("export",),
        operation="list",
    )

    assert result.success is True
    assert result.command is not None
    assert result.command.return_code == 0
    assert f"rc:{config.taskrc}" in result.command.arguments
    assert f"rc.data.location:{config.data_dir}" in result.command.arguments
    assert result.command.arguments[-1] == "export"
    assert str(config.home_dir) in result.command.stdout
    assert str(config.taskrc) in result.command.stdout
    assert str(config.working_dir) in result.command.stdout


def test_runner_reports_missing_executable(
    tmp_path: Path,
) -> None:
    """A missing binary should return a structured issue."""
    config = make_config(
        tmp_path,
        executable=tmp_path / "missing-task",
    )

    result = TaskwarriorRunner(config).run(
        ("--version",),
        operation="inspect",
    )

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_executable_missing"


def test_runner_reports_timeout(
    tmp_path: Path,
) -> None:
    """A process exceeding its deadline should fail explicitly."""
    executable = tmp_path / "bin" / "task"
    make_executable(
        executable,
        "import time\ntime.sleep(2)\n",
    )
    config = make_config(
        tmp_path,
        executable=executable,
        timeout_seconds=0.05,
    )

    result = TaskwarriorRunner(config).run(
        ("--version",),
        operation="inspect",
    )

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_process_timeout"


def test_runner_reports_non_zero_exit(
    tmp_path: Path,
) -> None:
    """Non-zero process results should retain bounded diagnostics."""
    executable = tmp_path / "bin" / "task"
    make_executable(
        executable,
        (
            "import sys\n"
            "print('diagnostic stdout')\n"
            "print('diagnostic stderr', file=sys.stderr)\n"
            "sys.exit(7)\n"
        ),
    )
    config = make_config(tmp_path, executable=executable)

    result = TaskwarriorRunner(config).run(
        ("export",),
        operation="list",
    )

    assert result.success is False
    assert result.command is not None
    assert result.command.return_code == 7
    assert result.command.stdout == "diagnostic stdout\n"
    assert result.command.stderr == "diagnostic stderr\n"
    assert result.issues[0].code == "taskwarrior_process_failed"
    assert result.issues[0].return_code == 7


def test_runner_rejects_blank_arguments(
    tmp_path: Path,
) -> None:
    """Blank subprocess arguments should fail before execution."""
    executable = tmp_path / "bin" / "task"
    make_executable(executable, "print('ok')\n")
    config = make_config(tmp_path, executable=executable)

    with pytest.raises(
        ValueError,
        match="must not contain empty values",
    ):
        TaskwarriorRunner(config).run(
            ("",),
            operation="test",
        )


def test_runner_does_not_change_parent_environment(
    tmp_path: Path,
) -> None:
    """Explicit child settings must not mutate os.environ."""
    executable = tmp_path / "bin" / "task"
    make_executable(executable, "print('ok')\n")
    config = make_config(tmp_path, executable=executable)
    original_home = os.environ.get("HOME")

    result = TaskwarriorRunner(config).run(
        ("--version",),
        operation="inspect",
    )

    assert result.success is True
    assert os.environ.get("HOME") == original_home


def test_unconfigured_runner_omits_managed_runtime_configuration(
    tmp_path: Path,
) -> None:
    """Unconfigured probes must not expose managed Taskwarrior storage."""
    executable = tmp_path / "bin" / "task"
    make_executable(
        executable,
        (
            "import json, os, sys\n"
            "print(json.dumps({"
            "'argv': sys.argv[1:], "
            "'home': os.environ.get('HOME'), "
            "'taskrc': os.environ.get('TASKRC'), "
            "'taskdata': os.environ.get('TASKDATA')"
            "}))\n"
        ),
    )
    config = make_config(tmp_path, executable=executable)
    runner = TaskwarriorRunner(
        config,
        base_environment={
            "HOME": "/root",
            "TASKRC": "/untrusted/taskrc",
            "TASKDATA": "/untrusted/data",
        },
    )

    result = runner.run(
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
    assert '"home": "/root"' in result.command.stdout
    assert '"taskrc": null' in result.command.stdout
    assert '"taskdata": null' in result.command.stdout
    assert str(config.taskrc) not in result.command.stdout
    assert str(config.data_dir) not in result.command.stdout
    assert str(config.home_dir) not in result.command.stdout
