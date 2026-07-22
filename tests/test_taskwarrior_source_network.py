"""Tests for Taskwarrior source-build network preflight."""

import stat
import subprocess
from pathlib import Path
from typing import Any

from lea.installers.taskwarrior.source_network import (
    TaskwarriorSourceNetworkConfig,
    validate_taskwarrior_source_network,
)


def _git(tmp_path: Path) -> Path:
    path = tmp_path / "git"
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _ca(tmp_path: Path) -> Path:
    path = tmp_path / "ca.crt"
    path.write_text(
        "-----BEGIN CERTIFICATE-----\nTEST\n-----END CERTIFICATE-----\n",
        encoding="ascii",
    )
    return path


def test_accepts_verified_remote(tmp_path: Path) -> None:
    config = TaskwarriorSourceNetworkConfig(
        git=_git(tmp_path),
        ca_bundle=_ca(tmp_path),
    )
    calls: list[dict[str, Any]] = []

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="a" * 40 + "\tHEAD\n",
            stderr="",
        )

    result = validate_taskwarrior_source_network(config, runner=runner)

    assert result.valid is True
    assert result.issues == ()
    assert calls[0]["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert calls[0]["env"]["GIT_SSL_CAINFO"] == str(config.ca_bundle)
    assert "shell" not in calls[0]


def test_rejects_missing_git(tmp_path: Path) -> None:
    result = validate_taskwarrior_source_network(
        TaskwarriorSourceNetworkConfig(
            git=tmp_path / "missing",
            ca_bundle=_ca(tmp_path),
        )
    )

    assert result.valid is False
    assert result.issues[0].field == "git"


def test_rejects_malformed_ca_bundle(tmp_path: Path) -> None:
    ca = tmp_path / "ca.crt"
    ca.write_text("broken\n", encoding="ascii")

    result = validate_taskwarrior_source_network(
        TaskwarriorSourceNetworkConfig(
            git=_git(tmp_path),
            ca_bundle=ca,
        )
    )

    assert result.valid is False
    assert result.issues[0].field == "ca_bundle"


def test_rejects_failed_remote_probe(tmp_path: Path) -> None:
    config = TaskwarriorSourceNetworkConfig(
        git=_git(tmp_path),
        ca_bundle=_ca(tmp_path),
    )

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            128,
            stdout="",
            stderr="TLS failure",
        )

    result = validate_taskwarrior_source_network(config, runner=runner)

    assert result.valid is False
    assert result.issues[0].field == "network"


def test_rejects_unexpected_remote_output(tmp_path: Path) -> None:
    config = TaskwarriorSourceNetworkConfig(
        git=_git(tmp_path),
        ca_bundle=_ca(tmp_path),
    )

    def runner(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="unexpected\n",
            stderr="",
        )

    result = validate_taskwarrior_source_network(config, runner=runner)

    assert result.valid is False
    assert result.issues[0].field == "network"
