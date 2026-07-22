"""Tests for Taskwarrior source-build dependencies and command plans."""

import stat
from pathlib import Path
from typing import Any

import pytest

from lea.installers.taskwarrior import (
    TaskwarriorBuildTools,
    TaskwarriorInstallFailureCode,
    create_taskwarrior_source_build_plan,
    default_taskwarrior_build_tools,
    validate_taskwarrior_build_dependencies,
)


def _executable(
    tmp_path: Path,
    name: str,
) -> Path:
    """Create one executable test double."""
    path = tmp_path / name
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _tools(tmp_path: Path) -> TaskwarriorBuildTools:
    """Return exact executable paths for dependency tests."""
    return TaskwarriorBuildTools(
        cmake=_executable(tmp_path, "cmake"),
        cxx=_executable(tmp_path, "c++"),
        make=_executable(tmp_path, "make"),
        cargo=_executable(tmp_path, "cargo"),
        rustc=_executable(tmp_path, "rustc"),
        pkg_config=_executable(tmp_path, "pkg-config"),
    )


def test_default_tools_use_explicit_paths() -> None:
    """Default dependency selection must not rely on PATH lookup."""
    tools = default_taskwarrior_build_tools()

    assert tools.cmake == Path("/usr/bin/cmake")
    assert tools.cxx == Path("/usr/bin/c++")
    assert tools.make == Path("/usr/bin/make")
    assert tools.cargo == Path("/usr/bin/cargo")
    assert tools.rustc == Path("/usr/bin/rustc")
    assert tools.pkg_config == Path("/usr/bin/pkg-config")


def test_missing_tool_returns_dependency_issue(
    tmp_path: Path,
) -> None:
    """A missing exact build tool should fail before probing versions."""
    tools = _tools(tmp_path)
    tools.rustc.unlink()

    result = validate_taskwarrior_build_dependencies(tools)

    assert result.tools is None
    assert result.issues[0].code is TaskwarriorInstallFailureCode.DEPENDENCY_MISSING
    assert result.issues[0].field == "rustc"


def test_dependency_validation_accepts_supported_probes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Supported Rust and libuuid probes should pass validation."""
    tools = _tools(tmp_path)

    def run(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> Any:
        if command[-1] == "--version":
            return type(
                "Completed",
                (),
                {
                    "returncode": 0,
                    "stdout": "rustc 1.85.0 (test)\n",
                    "stderr": "",
                },
            )()

        return type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": "",
                "stderr": "",
            },
        )()

    monkeypatch.setattr(
        "lea.installers.taskwarrior.build_plan.subprocess.run",
        run,
    )

    result = validate_taskwarrior_build_dependencies(tools)

    assert result.tools == tools
    assert result.issues == ()


def test_dependency_validation_rejects_old_rust(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rust older than Taskwarrior's MSRV must be rejected."""
    tools = _tools(tmp_path)

    def run(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> Any:
        return type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": ("rustc 1.80.1\n" if command[-1] == "--version" else ""),
                "stderr": "",
            },
        )()

    monkeypatch.setattr(
        "lea.installers.taskwarrior.build_plan.subprocess.run",
        run,
    )

    result = validate_taskwarrior_build_dependencies(tools)

    assert result.tools is None
    assert any(issue.field == "rustc" for issue in result.issues)


def test_dependency_validation_rejects_missing_libuuid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed pkg-config uuid probe must report libuuid."""
    tools = _tools(tmp_path)

    def run(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> Any:
        return type(
            "Completed",
            (),
            {
                "returncode": (1 if command[-1] == "uuid" else 0),
                "stdout": ("rustc 1.85.0\n" if command[-1] == "--version" else ""),
                "stderr": "",
            },
        )()

    monkeypatch.setattr(
        "lea.installers.taskwarrior.build_plan.subprocess.run",
        run,
    )

    result = validate_taskwarrior_build_dependencies(tools)

    assert result.tools is None
    assert any(issue.field == "libuuid" for issue in result.issues)


def test_build_plan_uses_exact_non_shell_commands(
    tmp_path: Path,
) -> None:
    """The source-build plan should be deterministic and explicit."""
    tools = _tools(tmp_path)
    source_root = tmp_path / "source"
    build_directory = tmp_path / "cmake-build"
    prefix = tmp_path / "install"

    plan = create_taskwarrior_source_build_plan(
        tools=tools,
        source_root=source_root,
        cmake_build_directory=build_directory,
        installation_prefix=prefix,
        build_concurrency=2,
        timeout_seconds=1800.0,
    )

    assert plan.configure_command == (
        str(tools.cmake),
        "-S",
        str(source_root),
        "-B",
        str(build_directory),
        "-G",
        "Unix Makefiles",
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DCMAKE_INSTALL_PREFIX={prefix}",
        f"-DCMAKE_CXX_COMPILER={tools.cxx}",
        f"-DCMAKE_MAKE_PROGRAM={tools.make}",
    )
    assert plan.build_command == (
        str(tools.cmake),
        "--build",
        str(build_directory),
        "--parallel",
        "2",
    )
    assert plan.install_command == (
        str(tools.cmake),
        "--install",
        str(build_directory),
    )


def test_build_plan_rejects_zero_concurrency(
    tmp_path: Path,
) -> None:
    """Build concurrency must remain finite and positive."""
    with pytest.raises(
        ValueError,
        match="build_concurrency must be greater than zero",
    ):
        create_taskwarrior_source_build_plan(
            tools=_tools(tmp_path),
            source_root=tmp_path / "source",
            cmake_build_directory=tmp_path / "build",
            installation_prefix=tmp_path / "install",
            build_concurrency=0,
            timeout_seconds=1800.0,
        )
