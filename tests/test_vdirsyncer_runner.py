"""Tests for hardened exact-path vdirsyncer execution."""

import sys
from pathlib import Path

from lea.adapters.vdirsyncer import VdirsyncerConfig, VdirsyncerRunner


def _config(tmp_path: Path, body: str) -> VdirsyncerConfig:
    executable = tmp_path / "bin" / "vdirsyncer"
    configuration = tmp_path / "config" / "vdirsyncer.conf"
    working = tmp_path / "work"
    executable.parent.mkdir()
    configuration.parent.mkdir()
    working.mkdir()
    executable.write_text(f"#!{sys.executable}\n{body}\n", encoding="utf-8")
    executable.chmod(0o700)
    configuration.write_text("[general]\n", encoding="utf-8")
    return VdirsyncerConfig(
        executable=executable,
        configuration=configuration,
        working_directory=working,
        expected_version="0.20.0",
        timeout_seconds=1.0,
    )


def test_runner_uses_exact_executable_config_and_bounded_environment(
    tmp_path: Path,
) -> None:
    config = _config(
        tmp_path,
        "import os, sys; print('|'.join(sys.argv[1:])); print(os.environ['HOME'])",
    )

    result = VdirsyncerRunner(
        config,
        base_environment={"SECRET": "hidden", "TZ": "UTC"},
    ).run(("sync", "personal"), operation="sync")

    assert result.success is True
    assert result.command is not None
    assert result.command.arguments == (
        str(config.executable),
        "--config",
        str(config.configuration),
        "sync",
        "personal",
    )
    assert result.command.stdout.splitlines() == [
        f"--config|{config.configuration}|sync|personal",
        str(config.working_directory),
    ]


def test_runner_reports_nonzero_without_exposing_stderr_in_issue(
    tmp_path: Path,
) -> None:
    config = _config(
        tmp_path,
        "import sys; print('secret detail', file=sys.stderr); raise SystemExit(3)",
    )

    result = VdirsyncerRunner(config).run(("sync",), operation="sync")

    assert result.success is False
    assert result.command is not None
    assert result.command.return_code == 3
    assert result.command.stderr == "secret detail\n"
    assert result.issues[0].code == "vdirsyncer_process_failed"
    assert "secret detail" not in result.issues[0].message


def test_runner_reports_conflict_without_exposing_provider_output(
    tmp_path: Path,
) -> None:
    """Provider conflicts must stop synchronization without an overwrite."""
    config = _config(
        tmp_path,
        "import sys; print('private conflict payload', file=sys.stderr); "
        "raise SystemExit(2)",
    )

    result = VdirsyncerRunner(config).run(("sync",), operation="calendar_sync")

    assert result.success is False
    assert result.command is not None
    assert result.issues[0].code == "vdirsyncer_conflict_detected"
    assert "private conflict payload" not in result.issues[0].message


def test_discovery_reports_missing_collection_bootstrap_without_prompt_text(
    tmp_path: Path,
) -> None:
    config = _config(
        tmp_path,
        (
            "print('Should vdirsyncer attempt to create it? [y/N]:'); "
            "raise SystemExit(1)"
        ),
    )

    result = VdirsyncerRunner(config).run(
        ("discover",),
        operation="calendar_discover",
    )

    assert result.success is False
    assert result.command is not None
    assert result.issues[0].code == "vdirsyncer_collection_creation_required"
    assert "attempt to create" not in result.issues[0].message


def test_explicit_bootstrap_supplies_only_declared_noninteractive_approval(
    tmp_path: Path,
) -> None:
    config = _config(
        tmp_path,
        "import sys; value = sys.stdin.read(); "
        "raise SystemExit(0 if value == 'y\\n' else 4)",
    )

    result = VdirsyncerRunner(config).run(
        ("discover",),
        operation="calendar_collection_bootstrap",
        approved_input=b"y\n",
    )

    assert result.success is True


def test_runner_fails_closed_for_symlinked_executable(tmp_path: Path) -> None:
    config = _config(tmp_path, "print('unexpected')")
    target = config.executable
    link = tmp_path / "linked-vdirsyncer"
    link.symlink_to(target)
    unsafe = VdirsyncerConfig(
        executable=link,
        configuration=config.configuration,
        working_directory=config.working_directory,
        expected_version=config.expected_version,
    )

    result = VdirsyncerRunner(unsafe).run(("sync",), operation="sync")

    assert result.success is False
    assert result.command is None
    assert result.issues[0].code == "vdirsyncer_executable_unavailable"


def test_runner_enforces_timeout(tmp_path: Path) -> None:
    config = _config(tmp_path, "import time; time.sleep(2)")

    result = VdirsyncerRunner(config).run(("sync",), operation="sync")

    assert result.success is False
    assert result.issues[0].code == "vdirsyncer_process_timeout"
