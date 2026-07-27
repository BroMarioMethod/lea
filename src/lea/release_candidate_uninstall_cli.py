"""Guided command-line interface for release-candidate uninstallation."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from typing import Protocol, TextIO

from lea.installers.release_candidate import (
    ReleaseCandidateUninstallPlan,
    ReleaseCandidateUninstallRequest,
    ReleaseCandidateUninstallResult,
    create_release_candidate_uninstall_plan,
    execute_release_candidate_uninstall,
)

EXIT_SUCCESS = 0
EXIT_UNINSTALL_ERROR = 1
EXIT_USAGE_ERROR = 2
EXIT_CANCELLED = 3
EXIT_INTERNAL_ERROR = 70

TextInput = Callable[[str], str]


class UninstallRunner(Protocol):
    """Callable boundary for one resolved uninstall plan."""

    def __call__(
        self,
        plan: ReleaseCandidateUninstallPlan,
    ) -> ReleaseCandidateUninstallResult:
        """Execute one validated release-candidate uninstall plan."""
        ...


@dataclass(frozen=True, slots=True)
class ReleaseCandidateUninstallCliDependencies:
    """Injected terminal and uninstall execution boundaries."""

    text_input: TextInput = lambda prompt: input(prompt)
    uninstaller: UninstallRunner = execute_release_candidate_uninstall


def create_release_candidate_uninstall_parser() -> argparse.ArgumentParser:
    """Create the dedicated release-candidate uninstall parser."""
    parser = argparse.ArgumentParser(
        prog="lea uninstall-release-candidate",
        description=(
            "Permanently remove the managed LEA release-candidate installation."
        ),
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        required=True,
        help=(
            "Remove managed configuration, state, logs, Taskwarrior, "
            "service files, service user and service group."
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Approve the destructive purge without an interactive prompt.",
    )
    return parser


def execute_release_candidate_uninstall_cli(
    arguments: Sequence[str],
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    dependencies: ReleaseCandidateUninstallCliDependencies | None = None,
) -> int:
    """Execute the guided release-candidate uninstall command."""
    parser = create_release_candidate_uninstall_parser()

    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            namespace = parser.parse_args(list(arguments))
    except SystemExit as error:
        return _normalise_argparse_exit(error)

    resolved = dependencies or ReleaseCandidateUninstallCliDependencies()

    try:
        preview_request = ReleaseCandidateUninstallRequest(
            purge=bool(namespace.purge),
            confirmed=True,
        )
        plan = create_release_candidate_uninstall_plan(preview_request)
        stdout.write(render_release_candidate_uninstall_plan(plan))

        confirmed = bool(namespace.yes)
        if not confirmed:
            confirmed = _prompt_yes_no(
                (
                    "Permanently remove the managed LEA release-candidate "
                    "installation? [y/N]: "
                ),
                text_input=resolved.text_input,
                default=False,
            )

        if not confirmed:
            stdout.write("Uninstallation cancelled.\n")
            return EXIT_CANCELLED

        request = ReleaseCandidateUninstallRequest(
            purge=True,
            confirmed=True,
        )
        result = resolved.uninstaller(create_release_candidate_uninstall_plan(request))
    except (EOFError, KeyboardInterrupt):
        stdout.write("\nUninstallation cancelled.\n")
        return EXIT_CANCELLED
    except (TypeError, ValueError) as error:
        stderr.write(f"Invalid uninstall input: {error}\n")
        return EXIT_USAGE_ERROR
    except Exception:
        stderr.write("The release-candidate uninstaller failed unexpectedly.\n")
        return EXIT_INTERNAL_ERROR

    rendered = render_release_candidate_uninstall_result(result)
    target = stdout if result.success else stderr
    target.write(rendered)

    return EXIT_SUCCESS if result.success else EXIT_UNINSTALL_ERROR


def render_release_candidate_uninstall_plan(
    plan: ReleaseCandidateUninstallPlan,
) -> str:
    """Render one stable human-readable uninstall plan."""
    if not isinstance(plan, ReleaseCandidateUninstallPlan):
        raise TypeError("plan must be a ReleaseCandidateUninstallPlan value.")

    lines = [
        "LEA release-candidate uninstall plan",
        "",
        "This purge will permanently remove:",
    ]

    for step in plan.steps:
        lines.append(f"- {step.step.value}: {step.summary}")
        for mutation in step.mutations:
            target = f" ({mutation.target})" if mutation.target is not None else ""
            lines.append(f"  - {mutation.kind.value}: {mutation.summary}{target}")

    lines.extend(
        (
            "",
            f"Preserved source repository: {plan.request.installation_root}",
            "Preserved release assets: /opt/lea-release-assets",
            "",
        )
    )
    return "\n".join(lines)


def render_release_candidate_uninstall_result(
    result: ReleaseCandidateUninstallResult,
) -> str:
    """Render one stable human-readable uninstall result."""
    if not isinstance(result, ReleaseCandidateUninstallResult):
        raise TypeError("result must be a ReleaseCandidateUninstallResult value.")

    lines = [
        "LEA release-candidate uninstallation",
        "",
        f"State: {'succeeded' if result.success else 'failed'}",
        "",
        "Steps:",
    ]

    for step in result.steps:
        lines.append(f"- {step.step.value}: {step.state.value} — {step.message}")

    if result.issues:
        lines.extend(("", "Issues:"))
        for issue in result.issues:
            path = f" ({issue.path})" if issue.path is not None else ""
            step_context = f" [{issue.step.value}]" if issue.step is not None else ""
            lines.append(f"- {issue.code.value}{step_context}: {issue.message}{path}")

    return "\n".join(lines) + "\n"


def _prompt_yes_no(
    prompt: str,
    *,
    text_input: TextInput,
    default: bool,
) -> bool:
    """Prompt until one recognised yes-or-no response is supplied."""
    while True:
        answer = text_input(prompt).strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False


def _normalise_argparse_exit(error: SystemExit) -> int:
    """Return one stable integer argparse exit status."""
    code = error.code
    return code if isinstance(code, int) else EXIT_USAGE_ERROR
