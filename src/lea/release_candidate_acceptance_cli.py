"""Command-line interface for release-candidate acceptance."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TextIO

from lea.installers.release_candidate import (
    BotApiTelegramOnboardingClient,
    PostInstallCheck,
    PostInstallHealthPlan,
    PostInstallHealthResult,
    ReleaseCandidateAcceptanceHarnessDependencies,
    ReleaseCandidateAcceptanceHarnessPlan,
    ReleaseCandidateAcceptanceHarnessResult,
    ReleaseCandidateAcceptanceResult,
    TelegramBotValidationResult,
    create_release_candidate_acceptance_harness_plan,
    run_release_candidate_acceptance,
    run_release_candidate_acceptance_harness,
    validate_bot_with_telegram,
)
from lea.runtime import load_runtime_config

EXIT_SUCCESS = 0
EXIT_ACCEPTANCE_FAILED = 1
EXIT_USAGE_ERROR = 2
EXIT_INTERNAL_ERROR = 70


class AcceptanceHarnessRunner(Protocol):
    """Callable boundary for one acceptance-harness execution."""

    def __call__(
        self,
        __plan: ReleaseCandidateAcceptanceHarnessPlan,
    ) -> ReleaseCandidateAcceptanceHarnessResult:
        """Run one release-candidate acceptance harness."""
        ...


def _run_production_harness(
    plan: ReleaseCandidateAcceptanceHarnessPlan,
) -> ReleaseCandidateAcceptanceHarnessResult:
    """Run acceptance with installed Telegram validation when selected."""

    def run_acceptance(
        health_plan: PostInstallHealthPlan,
        health: PostInstallHealthResult,
    ) -> ReleaseCandidateAcceptanceResult:

        if not isinstance(health, PostInstallHealthResult):
            raise TypeError("health must be a PostInstallHealthResult value.")

        if not health_plan.telegram_enabled:
            return run_release_candidate_acceptance(
                health_plan,
                health,
            )

        def validate_telegram() -> TelegramBotValidationResult:
            loaded = load_runtime_config(health_plan.runtime_config_file)

            if not loaded.success or loaded.config is None:
                raise ValueError(
                    "The installed runtime configuration could not be loaded."
                )

            token_file = loaded.config.secrets.telegram_token_file

            if (
                token_file is None
                or token_file.is_symlink()
                or not token_file.is_file()
            ):
                raise ValueError("The installed Telegram token file is invalid.")

            token = token_file.read_text(encoding="utf-8").strip()

            if not token:
                raise ValueError("The installed Telegram token is empty.")

            return validate_bot_with_telegram(
                token,
                BotApiTelegramOnboardingClient(),
            )

        result = run_release_candidate_acceptance(
            health_plan,
            health,
            telegram_validation=validate_telegram,
        )

        if not isinstance(result, ReleaseCandidateAcceptanceResult):
            raise TypeError("Acceptance execution returned an invalid result.")

        return result

    dependencies = ReleaseCandidateAcceptanceHarnessDependencies(
        run_acceptance=run_acceptance,
    )
    return run_release_candidate_acceptance_harness(
        plan,
        dependencies=dependencies,
    )


@dataclass(frozen=True, slots=True)
class ReleaseCandidateAcceptanceCliDependencies:
    """Injected acceptance CLI boundaries."""

    harness_runner: AcceptanceHarnessRunner = _run_production_harness


def create_release_candidate_acceptance_parser() -> argparse.ArgumentParser:
    """Create the release-candidate acceptance parser."""
    parser = argparse.ArgumentParser(
        prog="lea accept-release-candidate",
        description=("Run installed-system health and functional acceptance checks."),
    )
    parser.add_argument(
        "--configuration-root",
        type=Path,
        default=Path("/etc/lea"),
        metavar="PATH",
        help="Absolute LEA configuration root.",
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=Path("/var/lib/lea"),
        metavar="PATH",
        help="Absolute LEA state root.",
    )
    parser.add_argument(
        "--systemctl",
        type=Path,
        default=Path("/usr/bin/systemctl"),
        metavar="PATH",
        help="Absolute systemctl executable path.",
    )
    parser.add_argument(
        "--record-file",
        type=Path,
        metavar="PATH",
        help=(
            "Optional absolute acceptance-record destination. "
            "Defaults beneath the state root."
        ),
    )

    telegram_group = parser.add_mutually_exclusive_group(required=True)
    telegram_group.add_argument(
        "--telegram",
        dest="telegram_enabled",
        action="store_true",
        help="Include installed Telegram health and identity checks.",
    )
    telegram_group.add_argument(
        "--no-telegram",
        dest="telegram_enabled",
        action="store_false",
        help="Accept an installation that does not use Telegram.",
    )

    return parser


def execute_release_candidate_acceptance_cli(
    arguments: Sequence[str],
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    dependencies: ReleaseCandidateAcceptanceCliDependencies | None = None,
) -> int:
    """Execute release-candidate acceptance from explicit arguments."""
    parser = create_release_candidate_acceptance_parser()

    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            namespace = parser.parse_args(list(arguments))
    except SystemExit as error:
        return _normalise_argparse_exit(error)

    try:
        plan = _build_harness_plan(namespace)
    except (TypeError, ValueError) as error:
        stderr.write(f"Invalid acceptance input: {error}\n")
        return EXIT_USAGE_ERROR

    resolved = dependencies or ReleaseCandidateAcceptanceCliDependencies()

    try:
        result = resolved.harness_runner(plan)
    except Exception:
        stderr.write("The release-candidate acceptance harness failed unexpectedly.\n")
        return EXIT_INTERNAL_ERROR

    rendered = render_release_candidate_acceptance_result(result)

    if not result.success:
        stderr.write(rendered)
        return EXIT_INTERNAL_ERROR

    stdout.write(rendered)

    if result.accepted:
        return EXIT_SUCCESS

    return EXIT_ACCEPTANCE_FAILED


def render_release_candidate_acceptance_result(
    result: ReleaseCandidateAcceptanceHarnessResult,
) -> str:
    """Render one stable operator-facing acceptance result."""
    if not isinstance(result, ReleaseCandidateAcceptanceHarnessResult):
        raise TypeError(
            "result must be a ReleaseCandidateAcceptanceHarnessResult value."
        )

    if not result.success:
        outcome = "ERROR"
    elif result.accepted:
        outcome = "PASSED"
    else:
        outcome = "FAILED"

    lines = [
        "LEA release-candidate acceptance",
        "",
        f"Outcome: {outcome}",
    ]

    if result.record_write is None:
        lines.append("Acceptance record: not written")
    else:
        lines.extend(
            (
                f"Acceptance record: {result.record_write.path}",
                (
                    "Record changed: yes"
                    if result.record_write.changed
                    else "Record changed: no"
                ),
            )
        )

    if result.health is not None:
        lines.extend(("", "Health checks:"))
        lines.extend(_render_checks(result.health.checks))

    if result.acceptance is not None:
        lines.extend(("", "Functional acceptance checks:"))
        lines.extend(_render_checks(result.acceptance.checks))

    if result.issues:
        lines.extend(("", "Harness issues:"))
        for issue in result.issues:
            path = f" ({issue.path})" if issue.path is not None else ""
            lines.append(f"- {issue.code.value}: {issue.message}{path}")

    return "\n".join(lines) + "\n"


def _build_harness_plan(
    namespace: argparse.Namespace,
) -> ReleaseCandidateAcceptanceHarnessPlan:
    """Build one canonical installed-system acceptance plan."""
    configuration_root: Path = namespace.configuration_root
    state_root: Path = namespace.state_root
    systemctl: Path = namespace.systemctl
    record_file: Path | None = namespace.record_file

    for field_name, path in (
        ("configuration_root", configuration_root),
        ("state_root", state_root),
        ("systemctl", systemctl),
    ):
        _validate_absolute_path(path, field_name=field_name)

    if record_file is not None:
        _validate_absolute_path(
            record_file,
            field_name="record_file",
        )

    health = PostInstallHealthPlan(
        runtime_config_file=configuration_root / "lea.toml",
        telegram_config_file=(configuration_root / "telegram" / "telegram.toml"),
        installation_record_file=(state_root / "install" / "release-candidate.json"),
        taskwarrior_record_file=(state_root / "install" / "taskwarrior.json"),
        acceptance_work_directory=(state_root / "acceptance" / "taskwarrior"),
        systemctl=systemctl,
        telegram_service_name="lea-telegram.service",
        telegram_enabled=bool(namespace.telegram_enabled),
    )

    return create_release_candidate_acceptance_harness_plan(
        health,
        record_file=record_file,
    )


def _render_checks(
    checks: tuple[PostInstallCheck, ...],
) -> list[str]:
    """Render deterministic health or acceptance checks."""
    if not checks:
        return ["- No checks were recorded."]

    lines: list[str] = []

    for check in checks:
        path = f" ({check.path})" if check.path is not None else ""
        lines.append(f"- [{check.state.value}] {check.code}: {check.message}{path}")

    return lines


def _validate_absolute_path(
    path: Path,
    *,
    field_name: str,
) -> None:
    """Validate one absolute CLI path."""
    if not isinstance(path, Path):
        raise TypeError(f"{field_name} must be a pathlib.Path value.")
    if not path.is_absolute():
        raise ValueError(f"{field_name} must be absolute.")
    if "\x00" in str(path):
        raise ValueError(f"{field_name} must not contain a null byte.")


def _normalise_argparse_exit(
    error: SystemExit,
) -> int:
    """Return an integer argparse exit status."""
    code = error.code
    return code if isinstance(code, int) else EXIT_USAGE_ERROR
