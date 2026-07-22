"""Verified network preflight for clean Taskwarrior source builds."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from lea.installers.taskwarrior.contracts import (
    TaskwarriorInstallerIssue,
    TaskwarriorInstallFailureCode,
)

_CORROSION_REPOSITORY = "https://github.com/corrosion-rs/corrosion.git"


class _Runner(Protocol):
    def __call__(
        self,
        command: tuple[str, ...],
        *,
        capture_output: bool,
        text: bool,
        timeout: float,
        check: bool,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]: ...


@dataclass(frozen=True, slots=True)
class TaskwarriorSourceNetworkConfig:
    """Exact Git and CA paths used by online source builds."""

    git: Path = Path("/usr/bin/git")
    ca_bundle: Path = Path("/etc/ssl/certs/ca-certificates.crt")
    repository: str = _CORROSION_REPOSITORY

    def __post_init__(self) -> None:
        for name, path in (("git", self.git), ("ca_bundle", self.ca_bundle)):
            if not isinstance(path, Path):
                raise TypeError(f"{name} must be a pathlib.Path value.")
            if not path.is_absolute():
                raise ValueError(f"{name} must be absolute.")
        if not self.repository.startswith("https://"):
            raise ValueError("repository must use HTTPS.")


@dataclass(frozen=True, slots=True)
class TaskwarriorSourceNetworkResult:
    """Result of validating source-build network requirements."""

    valid: bool
    issues: tuple[TaskwarriorInstallerIssue, ...]

    def __post_init__(self) -> None:
        if self.valid and self.issues:
            raise ValueError("A valid result must not contain issues.")
        if not self.valid and not self.issues:
            raise ValueError("An invalid result must contain issues.")


def _run(
    command: tuple[str, ...],
    *,
    capture_output: bool,
    text: bool,
    timeout: float,
    check: bool,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=capture_output,
        text=text,
        timeout=timeout,
        check=check,
        env=env,
    )


def validate_taskwarrior_source_network(
    config: TaskwarriorSourceNetworkConfig,
    *,
    timeout_seconds: float = 30.0,
    runner: _Runner = _run,
) -> TaskwarriorSourceNetworkResult:
    """Validate Git, the CA bundle and verified Corrosion reachability."""
    if not isinstance(config, TaskwarriorSourceNetworkConfig):
        raise TypeError("config must be a TaskwarriorSourceNetworkConfig value.")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero.")

    issue = _validate_local_requirements(config)
    if issue is not None:
        return _failure(issue)

    environment = {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_SSL_CAINFO": str(config.ca_bundle),
    }

    try:
        completed = runner(
            (
                str(config.git),
                "-c",
                "http.sslVerify=true",
                "-c",
                f"http.sslCAInfo={config.ca_bundle}",
                "ls-remote",
                config.repository,
                "HEAD",
            ),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _failure(
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.DEPENDENCY_MISSING,
                message=(
                    "The Corrosion repository could not be reached over verified HTTPS."
                ),
                field="network",
                path=config.git,
            )
        )

    fields = completed.stdout.strip().split()
    valid_reference = (
        completed.returncode == 0
        and len(fields) == 2
        and fields[1] == "HEAD"
        and len(fields[0]) == 40
        and all(character in "0123456789abcdef" for character in fields[0])
    )

    if not valid_reference:
        return _failure(
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.DEPENDENCY_MISSING,
                message=(
                    "The Corrosion repository probe did not return a "
                    "canonical HEAD reference."
                ),
                field="network",
                path=config.git,
            )
        )

    return TaskwarriorSourceNetworkResult(valid=True, issues=())


def _validate_local_requirements(
    config: TaskwarriorSourceNetworkConfig,
) -> TaskwarriorInstallerIssue | None:
    if (
        not config.git.exists()
        or not config.git.is_file()
        or not config.git.stat().st_mode & 0o111
    ):
        return TaskwarriorInstallerIssue(
            code=TaskwarriorInstallFailureCode.DEPENDENCY_MISSING,
            message="The required Git executable is unavailable.",
            field="git",
            path=config.git,
        )

    if not config.ca_bundle.exists() or not config.ca_bundle.is_file():
        return TaskwarriorInstallerIssue(
            code=TaskwarriorInstallFailureCode.DEPENDENCY_MISSING,
            message="The system CA certificate bundle is unavailable.",
            field="ca_bundle",
            path=config.ca_bundle,
        )

    try:
        document = config.ca_bundle.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError):
        document = ""

    begin = document.count("-----BEGIN CERTIFICATE-----")
    end = document.count("-----END CERTIFICATE-----")

    if begin == 0 or begin != end:
        return TaskwarriorInstallerIssue(
            code=TaskwarriorInstallFailureCode.DEPENDENCY_MISSING,
            message="The system CA certificate bundle is malformed.",
            field="ca_bundle",
            path=config.ca_bundle,
        )

    return None


def _failure(
    issue: TaskwarriorInstallerIssue,
) -> TaskwarriorSourceNetworkResult:
    return TaskwarriorSourceNetworkResult(valid=False, issues=(issue,))
