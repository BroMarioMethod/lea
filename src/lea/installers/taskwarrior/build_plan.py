"""Deterministic Taskwarrior source-build dependency and command plans."""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from lea.installers.taskwarrior.contracts import (
    TaskwarriorInstallerIssue,
    TaskwarriorInstallFailureCode,
)

_MINIMUM_RUST_VERSION = (1, 81, 0)
_VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True, slots=True)
class TaskwarriorBuildTools:
    """Exact executable paths required for a Taskwarrior source build."""

    cmake: Path
    cxx: Path
    make: Path
    cargo: Path
    rustc: Path
    pkg_config: Path

    def __post_init__(self) -> None:
        """Validate all build-tool paths."""
        for field_name, executable in (
            ("cmake", self.cmake),
            ("cxx", self.cxx),
            ("make", self.make),
            ("cargo", self.cargo),
            ("rustc", self.rustc),
            ("pkg_config", self.pkg_config),
        ):
            _validate_absolute_path(
                executable,
                field_name=field_name,
            )


@dataclass(frozen=True, slots=True)
class TaskwarriorBuildDependencyResult:
    """Result of validating exact source-build dependencies."""

    tools: TaskwarriorBuildTools | None
    issues: tuple[TaskwarriorInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate dependency-result consistency."""
        if self.tools is not None:
            if self.issues:
                raise ValueError(
                    "A successful dependency result must not contain issues."
                )
            return

        if not self.issues:
            raise ValueError(
                "A failed dependency result must contain at least one issue."
            )


@dataclass(frozen=True, slots=True)
class TaskwarriorSourceBuildPlan:
    """Exact non-shell command plan for one Taskwarrior source build."""

    configure_command: tuple[str, ...]
    build_command: tuple[str, ...]
    install_command: tuple[str, ...]
    source_root: Path
    cmake_build_directory: Path
    installation_prefix: Path
    timeout_seconds: float

    def __post_init__(self) -> None:
        """Validate source-build plan fields."""
        for field_name, command in (
            ("configure_command", self.configure_command),
            ("build_command", self.build_command),
            ("install_command", self.install_command),
        ):
            if not command:
                raise ValueError(f"{field_name} must not be empty.")
            if any(not argument for argument in command):
                raise ValueError(f"{field_name} arguments must be non-empty.")

        for field_name, path in (
            ("source_root", self.source_root),
            ("cmake_build_directory", self.cmake_build_directory),
            ("installation_prefix", self.installation_prefix),
        ):
            _validate_absolute_path(path, field_name=field_name)

        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")


def default_taskwarrior_build_tools() -> TaskwarriorBuildTools:
    """Return LEA's explicit Debian-family source-build tool paths."""
    return TaskwarriorBuildTools(
        cmake=Path("/usr/bin/cmake"),
        cxx=Path("/usr/bin/c++"),
        make=Path("/usr/bin/make"),
        cargo=Path("/usr/bin/cargo"),
        rustc=Path("/usr/bin/rustc"),
        pkg_config=Path("/usr/bin/pkg-config"),
    )


def validate_taskwarrior_build_dependencies(
    tools: TaskwarriorBuildTools,
    *,
    timeout_seconds: float = 10.0,
) -> TaskwarriorBuildDependencyResult:
    """Validate exact build tools, Rust policy and libuuid availability."""
    if not isinstance(tools, TaskwarriorBuildTools):
        raise TypeError("tools must be a TaskwarriorBuildTools value.")

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero.")

    issues: list[TaskwarriorInstallerIssue] = []

    for field_name, executable in (
        ("cmake", tools.cmake),
        ("cxx", tools.cxx),
        ("make", tools.make),
        ("cargo", tools.cargo),
        ("rustc", tools.rustc),
        ("pkg_config", tools.pkg_config),
    ):
        issues.extend(
            _validate_executable(
                executable,
                field_name=field_name,
            )
        )

    if issues:
        return TaskwarriorBuildDependencyResult(
            tools=None,
            issues=tuple(issues),
        )

    rust_result = _run_version_command(
        (str(tools.rustc), "--version"),
        field_name="rustc",
        executable=tools.rustc,
        timeout_seconds=timeout_seconds,
    )

    if isinstance(rust_result, TaskwarriorInstallerIssue):
        issues.append(rust_result)
    else:
        rust_version = _parse_semantic_version(rust_result)

        if rust_version is None:
            issues.append(
                TaskwarriorInstallerIssue(
                    code=(TaskwarriorInstallFailureCode.DEPENDENCY_MISSING),
                    message=("The Rust compiler version could not be parsed."),
                    field="rustc",
                    path=tools.rustc,
                )
            )
        elif rust_version < _MINIMUM_RUST_VERSION:
            issues.append(
                TaskwarriorInstallerIssue(
                    code=(TaskwarriorInstallFailureCode.DEPENDENCY_MISSING),
                    message=("Taskwarrior requires Rust 1.81.0 or newer."),
                    field="rustc",
                    path=tools.rustc,
                )
            )

    uuid_result = _run_version_command(
        (
            str(tools.pkg_config),
            "--exists",
            "uuid",
        ),
        field_name="libuuid",
        executable=tools.pkg_config,
        timeout_seconds=timeout_seconds,
        require_output=False,
    )

    if isinstance(uuid_result, TaskwarriorInstallerIssue):
        issues.append(
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.DEPENDENCY_MISSING,
                message=(
                    "The libuuid development package is unavailable to pkg-config."
                ),
                field="libuuid",
                path=tools.pkg_config,
            )
        )

    if issues:
        return TaskwarriorBuildDependencyResult(
            tools=None,
            issues=tuple(issues),
        )

    return TaskwarriorBuildDependencyResult(
        tools=tools,
        issues=(),
    )


def create_taskwarrior_source_build_plan(
    *,
    tools: TaskwarriorBuildTools,
    source_root: Path,
    cmake_build_directory: Path,
    installation_prefix: Path,
    build_concurrency: int,
    timeout_seconds: float,
) -> TaskwarriorSourceBuildPlan:
    """Create exact CMake configure, build and install commands."""
    if not isinstance(tools, TaskwarriorBuildTools):
        raise TypeError("tools must be a TaskwarriorBuildTools value.")

    for field_name, path in (
        ("source_root", source_root),
        ("cmake_build_directory", cmake_build_directory),
        ("installation_prefix", installation_prefix),
    ):
        _validate_absolute_path(path, field_name=field_name)

    if build_concurrency <= 0:
        raise ValueError("build_concurrency must be greater than zero.")

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero.")

    configure_command = (
        str(tools.cmake),
        "-S",
        str(source_root),
        "-B",
        str(cmake_build_directory),
        "-G",
        "Unix Makefiles",
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DCMAKE_INSTALL_PREFIX={installation_prefix}",
        f"-DCMAKE_CXX_COMPILER={tools.cxx}",
        f"-DCMAKE_MAKE_PROGRAM={tools.make}",
    )
    build_command = (
        str(tools.cmake),
        "--build",
        str(cmake_build_directory),
        "--parallel",
        str(build_concurrency),
    )
    install_command = (
        str(tools.cmake),
        "--install",
        str(cmake_build_directory),
    )

    return TaskwarriorSourceBuildPlan(
        configure_command=configure_command,
        build_command=build_command,
        install_command=install_command,
        source_root=source_root,
        cmake_build_directory=cmake_build_directory,
        installation_prefix=installation_prefix,
        timeout_seconds=timeout_seconds,
    )


def _validate_executable(
    executable: Path,
    *,
    field_name: str,
) -> tuple[TaskwarriorInstallerIssue, ...]:
    """Validate one exact build-tool executable path."""
    if not executable.exists():
        return (
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.DEPENDENCY_MISSING,
                message=(f"The required build tool '{field_name}' does not exist."),
                field=field_name,
                path=executable,
            ),
        )

    if not executable.is_file():
        return (
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.DEPENDENCY_MISSING,
                message=(
                    f"The required build tool '{field_name}' is not a regular file."
                ),
                field=field_name,
                path=executable,
            ),
        )

    if not executable.stat().st_mode & 0o111:
        return (
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.DEPENDENCY_MISSING,
                message=(f"The required build tool '{field_name}' is not executable."),
                field=field_name,
                path=executable,
            ),
        )

    return ()


def _run_version_command(
    command: tuple[str, ...],
    *,
    field_name: str,
    executable: Path,
    timeout_seconds: float,
    require_output: bool = True,
) -> str | TaskwarriorInstallerIssue:
    """Run one finite dependency probe without a shell."""
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return TaskwarriorInstallerIssue(
            code=TaskwarriorInstallFailureCode.DEPENDENCY_MISSING,
            message=(
                f"The dependency probe for '{field_name}' failed: "
                f"{type(error).__name__}."
            ),
            field=field_name,
            path=executable,
        )

    output = completed.stdout.strip()

    if completed.returncode != 0 or (require_output and not output):
        return TaskwarriorInstallerIssue(
            code=TaskwarriorInstallFailureCode.DEPENDENCY_MISSING,
            message=(f"The dependency probe for '{field_name}' did not succeed."),
            field=field_name,
            path=executable,
        )

    return output


def _parse_semantic_version(
    output: str,
) -> tuple[int, int, int] | None:
    """Parse the first three-part numeric version from command output."""
    match = _VERSION_PATTERN.search(output)

    if match is None:
        return None

    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def _validate_absolute_path(
    path: Path,
    *,
    field_name: str,
) -> None:
    """Validate one absolute pathlib path."""
    if not isinstance(path, Path):
        raise TypeError(f"{field_name} must be a pathlib.Path value.")

    if not path.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path.")
