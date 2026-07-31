"""Deterministic uv command plans for managed calendar environments."""

from dataclasses import dataclass
from pathlib import Path

from lea.installers.calendar.contracts import (
    CalendarToolchainInstallerConfig,
    CalendarToolchainInstallMode,
)
from lea.installers.calendar.staging import (
    CalendarToolchainStagingLayout,
)


@dataclass(frozen=True, slots=True)
class CalendarToolchainEnvironmentPlan:
    """Exact non-shell commands for one isolated calendar environment."""

    mode: CalendarToolchainInstallMode
    create_environment_command: tuple[str, ...]
    install_packages_command: tuple[str, ...]
    working_directory: Path
    environment_root: Path
    environment_python: Path
    requirements_lock: Path
    timeout_seconds: float

    def __post_init__(self) -> None:
        """Validate command and path invariants."""
        if not isinstance(self.mode, CalendarToolchainInstallMode):
            raise TypeError("mode must be a CalendarToolchainInstallMode value.")

        if self.mode is CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES:
            raise ValueError(
                "External-executables mode does not use a managed environment plan."
            )

        for field_name, command in (
            ("create_environment_command", self.create_environment_command),
            ("install_packages_command", self.install_packages_command),
        ):
            if not isinstance(command, tuple):
                raise TypeError(f"{field_name} must be a tuple.")

            if not command:
                raise ValueError(f"{field_name} must not be empty.")

            if any(
                not isinstance(argument, str) or not argument for argument in command
            ):
                raise ValueError(f"{field_name} arguments must be non-empty strings.")

        for field_name, path in (
            ("working_directory", self.working_directory),
            ("environment_root", self.environment_root),
            ("environment_python", self.environment_python),
            ("requirements_lock", self.requirements_lock),
        ):
            _validate_absolute_path(path, field_name=field_name)

        if self.environment_python != self.environment_root / "bin" / "python":
            raise ValueError(
                "environment_python must be inside the staged environment."
            )

        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")


def create_calendar_toolchain_environment_plan(
    config: CalendarToolchainInstallerConfig,
    staged: CalendarToolchainStagingLayout,
) -> CalendarToolchainEnvironmentPlan:
    """Create exact uv commands without executing or accessing the network."""
    if not isinstance(config, CalendarToolchainInstallerConfig):
        raise TypeError("config must be a CalendarToolchainInstallerConfig value.")

    if config.mode is CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES:
        raise ValueError(
            "External-executables mode does not use a managed environment plan."
        )

    if not isinstance(staged, CalendarToolchainStagingLayout):
        raise TypeError("staged must be a CalendarToolchainStagingLayout value.")

    if staged.staging_parent != config.tools_root:
        raise ValueError(
            "The staged layout does not belong to the configured tools root."
        )

    uv_executable = _require_path(
        config.uv_executable,
        field_name="uv_executable",
    )
    python_executable = _require_path(
        config.python_executable,
        field_name="python_executable",
    )

    environment_python = staged.environment_root / "bin" / "python"

    create_environment_command = (
        str(uv_executable),
        "--no-config",
        "--no-cache",
        "--no-python-downloads",
        "--no-progress",
        "venv",
        "--no-project",
        "--no-managed-python",
        "--relocatable",
        "--python",
        str(python_executable),
        str(staged.environment_root),
    )

    common_install_arguments = (
        str(uv_executable),
        "--no-config",
        "--no-cache",
        "--no-python-downloads",
        "--no-managed-python",
        "--no-progress",
    )

    pip_sync_arguments = (
        "pip",
        "sync",
        "--python",
        str(environment_python),
        "--require-hashes",
        "--only-binary",
        ":all:",
        "--strict",
        "--no-sources",
    )

    install_packages_command: tuple[str, ...]

    if config.mode is CalendarToolchainInstallMode.VERIFIED_NETWORK:
        package_index_url = _require_string(
            config.package_index_url,
            field_name="package_index_url",
        )
        install_packages_command = (
            *common_install_arguments,
            *pip_sync_arguments,
            "--default-index",
            package_index_url,
            str(staged.requirements_lock),
        )
    else:
        wheelhouse_directory = staged.wheelhouse_directory

        if wheelhouse_directory is None:
            raise ValueError(
                "Bundled-wheelhouse mode requires a staged wheelhouse directory."
            )

        install_packages_command = (
            *common_install_arguments,
            "--offline",
            *pip_sync_arguments,
            "--no-index",
            "--find-links",
            str(wheelhouse_directory),
            str(staged.requirements_lock),
        )

    return CalendarToolchainEnvironmentPlan(
        mode=config.mode,
        create_environment_command=create_environment_command,
        install_packages_command=install_packages_command,
        working_directory=staged.staging_root,
        environment_root=staged.environment_root,
        environment_python=environment_python,
        requirements_lock=staged.requirements_lock,
        timeout_seconds=float(config.timeout_seconds),
    )


def _require_path(
    path: Path | None,
    *,
    field_name: str,
) -> Path:
    """Return one required absolute path."""
    if path is None:
        raise ValueError(f"{field_name} is required.")

    _validate_absolute_path(path, field_name=field_name)
    return path


def _require_string(
    value: str | None,
    *,
    field_name: str,
) -> str:
    """Return one required stripped string."""
    if value is None or not value.strip():
        raise ValueError(f"{field_name} is required.")

    return value.strip()


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
