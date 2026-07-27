"""Taskwarrior integration for release-candidate installation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lea.installers.release_candidate.contracts import (
    InstallerIssue,
    InstallerIssueCode,
    InstallerStepId,
    ReleaseCandidateInstallRequest,
)
from lea.installers.taskwarrior import (
    TaskwarriorBuildProgressReporter,
    TaskwarriorInstallationRecord,
    TaskwarriorInstallerConfig,
    TaskwarriorInstallMode,
    TaskwarriorInstallResult,
    install_taskwarrior,
)

TaskwarriorInstaller = Callable[..., TaskwarriorInstallResult]


@dataclass(frozen=True, slots=True)
class ReleaseCandidateTaskwarriorInputs:
    """Pinned Taskwarrior source-build inputs for one installation."""

    version: str
    platform: str
    source_archive: Path
    expected_sha256: str
    build_directory: Path
    build_concurrency: int = 1

    def __post_init__(self) -> None:
        """Validate source-build inputs."""
        for field_name, value in (
            ("version", self.version),
            ("platform", self.platform),
            ("expected_sha256", self.expected_sha256),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty.")

        for field_name, path in (
            ("source_archive", self.source_archive),
            ("build_directory", self.build_directory),
        ):
            _validate_absolute_path(path, field_name=field_name)

        if len(self.expected_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.expected_sha256
        ):
            raise ValueError(
                "expected_sha256 must be lower-case hexadecimal SHA-256 text."
            )

        if self.build_concurrency <= 0:
            raise ValueError("build_concurrency must be greater than zero.")


@dataclass(frozen=True, slots=True)
class ReleaseCandidateTaskwarriorPlan:
    """Immutable Taskwarrior installation plan for the release candidate."""

    config: TaskwarriorInstallerConfig
    expected_executable: Path

    def __post_init__(self) -> None:
        """Validate plan consistency."""
        _validate_absolute_path(
            self.expected_executable,
            field_name="expected_executable",
        )

        expected = self.config.tools_root / self.config.version / "bin" / "task"
        if self.expected_executable != expected:
            raise ValueError(
                "expected_executable must match the managed Taskwarrior path."
            )


@dataclass(frozen=True, slots=True)
class ReleaseCandidateTaskwarriorResult:
    """Release-candidate view of one Taskwarrior installation result."""

    success: bool
    already_installed: bool
    executable: Path | None
    record: TaskwarriorInstallationRecord | None
    issues: tuple[InstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate result consistency."""
        if self.executable is not None:
            _validate_absolute_path(self.executable, field_name="executable")

        if self.success:
            if self.executable is None or self.record is None:
                raise ValueError(
                    "A successful result must contain executable and record."
                )
            if self.issues:
                raise ValueError("A successful result must not contain issues.")
            return

        if self.already_installed:
            raise ValueError("A failed result must not be marked already installed.")

        if self.executable is not None or self.record is not None:
            raise ValueError("A failed result must not contain executable or record.")

        if not self.issues:
            raise ValueError("A failed result must contain at least one issue.")


def create_taskwarrior_installation_plan(
    request: ReleaseCandidateInstallRequest,
    inputs: ReleaseCandidateTaskwarriorInputs,
) -> ReleaseCandidateTaskwarriorPlan:
    """Create the pinned Taskwarrior source-build installer configuration."""
    if not isinstance(request, ReleaseCandidateInstallRequest):
        raise TypeError("request must be a ReleaseCandidateInstallRequest value.")

    if not isinstance(inputs, ReleaseCandidateTaskwarriorInputs):
        raise TypeError("inputs must be a ReleaseCandidateTaskwarriorInputs value.")

    tools_root = Path("/opt/lea-tools/taskwarrior")
    config = TaskwarriorInstallerConfig(
        mode=TaskwarriorInstallMode.SOURCE_BUILD,
        version=inputs.version,
        platform=inputs.platform,
        tools_root=tools_root,
        configuration_dir=request.configuration_root / "taskwarrior",
        state_root=request.state_root / "taskwarrior",
        installation_record=(request.state_root / "install" / "taskwarrior.json"),
        service_user=request.service_user,
        service_group=request.service_group,
        source_archive=inputs.source_archive,
        expected_sha256=inputs.expected_sha256,
        build_directory=inputs.build_directory,
        build_concurrency=inputs.build_concurrency,
        non_interactive=True,
    )

    return ReleaseCandidateTaskwarriorPlan(
        config=config,
        expected_executable=(tools_root / inputs.version / "bin" / "task"),
    )


def install_release_candidate_taskwarrior(
    plan: ReleaseCandidateTaskwarriorPlan,
    *,
    installer: TaskwarriorInstaller = install_taskwarrior,
    fsync: bool = True,
    progress: TaskwarriorBuildProgressReporter | None = None,
) -> ReleaseCandidateTaskwarriorResult:
    """Install Taskwarrior through the existing installer dispatcher."""
    if not isinstance(plan, ReleaseCandidateTaskwarriorPlan):
        raise TypeError("plan must be a ReleaseCandidateTaskwarriorPlan value.")

    result = installer(
        plan.config,
        fsync=fsync,
        progress=progress,
    )

    if not result.success or result.record is None:
        issues = tuple(
            InstallerIssue(
                code=InstallerIssueCode.STEP_FAILED,
                message=issue.message,
                step=InstallerStepId.TASKWARRIOR,
                field=issue.field,
                path=issue.path,
            )
            for issue in result.issues
        )

        if not issues:
            issues = (
                InstallerIssue(
                    code=InstallerIssueCode.STEP_FAILED,
                    message=(
                        "Taskwarrior installation failed without a structured "
                        "component issue."
                    ),
                    step=InstallerStepId.TASKWARRIOR,
                ),
            )

        return ReleaseCandidateTaskwarriorResult(
            success=False,
            already_installed=False,
            executable=None,
            record=None,
            issues=issues,
        )

    if result.record.executable != plan.expected_executable:
        return ReleaseCandidateTaskwarriorResult(
            success=False,
            already_installed=False,
            executable=None,
            record=None,
            issues=(
                InstallerIssue(
                    code=InstallerIssueCode.STEP_FAILED,
                    message=(
                        "Taskwarrior installation returned an unexpected "
                        "managed executable path."
                    ),
                    step=InstallerStepId.TASKWARRIOR,
                    path=result.record.executable,
                ),
            ),
        )

    return ReleaseCandidateTaskwarriorResult(
        success=True,
        already_installed=result.already_installed,
        executable=result.record.executable,
        record=result.record,
        issues=(),
    )


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

    if "\x00" in str(path):
        raise ValueError(f"{field_name} must not contain a null byte.")
