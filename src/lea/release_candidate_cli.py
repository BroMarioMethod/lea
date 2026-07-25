"""Guided command-line interface for release-candidate installation."""

from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TextIO

from lea.channels import ChannelCapability
from lea.installers.release_candidate import (
    BotApiTelegramOnboardingClient,
    ReleaseCandidateInstallMode,
    ReleaseCandidateInstallRequest,
    ReleaseCandidateOrchestrationRequest,
    ReleaseCandidateOrchestrationResult,
    ReleaseCandidateOrchestrationState,
    ReleaseCandidateTaskwarriorInputs,
    TelegramBotValidationResult,
    TelegramOnboardingClient,
    TelegramOnboardingConfirmation,
    TelegramOnboardingIdentity,
    TelegramOnboardingRole,
    confirm_telegram_identity,
    create_release_candidate_install_plan,
    create_release_candidate_orchestration_dependencies,
    discover_telegram_start_identity,
    read_hidden_bot_token,
    render_release_candidate_install_plan,
    run_release_candidate_orchestration,
    validate_bot_with_telegram,
)
from lea.version import get_version

EXIT_SUCCESS = 0
EXIT_INSTALLATION_ERROR = 1
EXIT_USAGE_ERROR = 2
EXIT_CANCELLED = 3
EXIT_INTERNAL_ERROR = 70

TextInput = Callable[[str], str]
HiddenInput = Callable[[str], str]
VersionReader = Callable[[], str]
OnboardingClientFactory = Callable[[], TelegramOnboardingClient]


class OrchestrationRunner(Protocol):
    """Callable boundary for one resolved installer run."""

    def __call__(
        self,
        request: ReleaseCandidateOrchestrationRequest,
        *,
        telegram_token: str | None = None,
        telegram_confirmation: TelegramOnboardingConfirmation | None = None,
    ) -> ReleaseCandidateOrchestrationResult:
        """Execute one resolved installation attempt."""
        ...


def _run_production_orchestration(
    request: ReleaseCandidateOrchestrationRequest,
    *,
    telegram_token: str | None = None,
    telegram_confirmation: TelegramOnboardingConfirmation | None = None,
) -> ReleaseCandidateOrchestrationResult:
    """Compose production dependencies, including Telegram revalidation."""
    if telegram_token is None:
        dependencies = create_release_candidate_orchestration_dependencies()
    else:

        def validate_telegram() -> TelegramBotValidationResult:
            return validate_bot_with_telegram(
                telegram_token,
                BotApiTelegramOnboardingClient(),
            )

        dependencies = create_release_candidate_orchestration_dependencies(
            telegram_validation=validate_telegram,
        )
    return run_release_candidate_orchestration(
        request,
        telegram_token=telegram_token,
        telegram_confirmation=telegram_confirmation,
        dependencies=dependencies,
    )


@dataclass(frozen=True, slots=True)
class ReleaseCandidateCliDependencies:
    """Injected terminal, network and orchestration boundaries."""

    text_input: TextInput = lambda prompt: input(prompt)
    hidden_input: HiddenInput = lambda prompt: getpass.getpass(prompt)
    onboarding_client_factory: OnboardingClientFactory = lambda: (
        BotApiTelegramOnboardingClient()
    )
    version_reader: VersionReader = get_version
    orchestrator: OrchestrationRunner = _run_production_orchestration


class _UserCancelled(Exception):
    """Internal signal for an explicit guided cancellation."""


def create_release_candidate_parser() -> argparse.ArgumentParser:
    """Create the dedicated release-candidate installer parser."""
    parser = argparse.ArgumentParser(
        prog="lea install-release-candidate",
        description=("Plan and perform a guided LEA release-candidate installation."),
    )
    parser.add_argument(
        "--mode",
        choices=tuple(mode.value for mode in ReleaseCandidateInstallMode),
        help="Installation mode. Prompted when omitted.",
    )
    parser.add_argument(
        "--display-timezone",
        metavar="ZONE",
        help="IANA timezone used for human-readable presentation.",
    )

    telegram_group = parser.add_mutually_exclusive_group()
    telegram_group.add_argument(
        "--telegram",
        dest="enable_telegram",
        action="store_true",
        help="Enable guided Telegram onboarding.",
    )
    telegram_group.add_argument(
        "--no-telegram",
        dest="enable_telegram",
        action="store_false",
        help="Install without Telegram.",
    )
    parser.set_defaults(enable_telegram=None)

    parser.add_argument(
        "--taskwarrior-source-archive",
        required=True,
        type=Path,
        metavar="PATH",
        help="Absolute path to the pinned Taskwarrior source archive.",
    )
    parser.add_argument(
        "--taskwarrior-sha256",
        required=True,
        metavar="SHA256",
        help="Expected lower-case SHA-256 for the source archive.",
    )
    parser.add_argument(
        "--taskwarrior-version",
        default="3.4.2",
        help="Pinned Taskwarrior version.",
    )
    parser.add_argument(
        "--taskwarrior-platform",
        default="linux-aarch64",
        help="Pinned Taskwarrior platform identifier.",
    )
    parser.add_argument(
        "--taskwarrior-build-directory",
        type=Path,
        default=Path("/var/tmp/lea-taskwarrior-build"),
        metavar="PATH",
        help="Absolute disposable Taskwarrior source-build directory.",
    )
    parser.add_argument(
        "--taskwarrior-build-concurrency",
        type=int,
        default=1,
        metavar="COUNT",
        help="Taskwarrior build concurrency. Defaults to one.",
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="Approve the rendered plan without an interactive prompt.",
    )
    parser.add_argument(
        "--approve-replacement",
        action="store_true",
        help="Approve replacement of existing managed resources.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Reject any input that would require a prompt.",
    )
    return parser


def execute_release_candidate_cli(
    arguments: Sequence[str],
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    dependencies: ReleaseCandidateCliDependencies | None = None,
) -> int:
    """Execute the guided release-candidate installer command."""
    parser = create_release_candidate_parser()

    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            namespace = parser.parse_args(list(arguments))
    except SystemExit as error:
        return _normalise_argparse_exit(error)

    resolved = dependencies or ReleaseCandidateCliDependencies()

    try:
        mode = _resolve_mode(
            namespace.mode,
            non_interactive=bool(namespace.non_interactive),
            text_input=resolved.text_input,
        )
        display_timezone = _resolve_timezone(
            namespace.display_timezone,
            non_interactive=bool(namespace.non_interactive),
            text_input=resolved.text_input,
        )
        enable_telegram = _resolve_telegram_selection(
            namespace.enable_telegram,
            non_interactive=bool(namespace.non_interactive),
            text_input=resolved.text_input,
        )
        taskwarrior = _taskwarrior_inputs(namespace)
    except _UserCancelled:
        stdout.write("Installation cancelled.\n")
        return EXIT_CANCELLED
    except (TypeError, ValueError) as error:
        stderr.write(f"Invalid installer input: {error}\n")
        return EXIT_USAGE_ERROR
    except (EOFError, KeyboardInterrupt):
        stdout.write("\nInstallation cancelled.\n")
        return EXIT_CANCELLED

    if namespace.non_interactive and enable_telegram:
        stderr.write(
            "Invalid installer input: non-interactive Telegram onboarding "
            "is not supported by the guided command.\n"
        )
        return EXIT_USAGE_ERROR

    install_request = ReleaseCandidateInstallRequest(
        mode=mode,
        display_timezone=display_timezone,
        enable_telegram=enable_telegram,
        non_interactive=bool(namespace.non_interactive),
    )

    try:
        plan = create_release_candidate_install_plan(
            install_request,
            taskwarrior,
        )
        stdout.write(render_release_candidate_install_plan(plan))
        stdout.write("\n")

        plan_approved = bool(namespace.approve)
        if not plan_approved:
            if namespace.non_interactive:
                raise ValueError("--approve is required in non-interactive mode.")
            plan_approved = _prompt_yes_no(
                "Proceed with this installation plan? [y/N]: ",
                text_input=resolved.text_input,
                default=False,
            )

        if not plan_approved:
            raise _UserCancelled

        replacement_approved = bool(namespace.approve_replacement)
        if (
            mode is not ReleaseCandidateInstallMode.FRESH_INSTALL
            and not replacement_approved
        ):
            if namespace.non_interactive:
                raise ValueError(
                    "--approve-replacement is required for non-interactive "
                    "repair or upgrade."
                )
            replacement_approved = _prompt_yes_no(
                "Allow replacement of existing managed resources? [y/N]: ",
                text_input=resolved.text_input,
                default=False,
            )
            if not replacement_approved:
                raise _UserCancelled

        token: str | None = None
        confirmation: TelegramOnboardingConfirmation | None = None

        if enable_telegram:
            token, confirmation = _run_telegram_onboarding(
                stdout=stdout,
                stderr=stderr,
                text_input=resolved.text_input,
                hidden_input=resolved.hidden_input,
                client=resolved.onboarding_client_factory(),
            )

        orchestration_request = ReleaseCandidateOrchestrationRequest(
            installation=install_request,
            taskwarrior=taskwarrior,
            lea_version=resolved.version_reader(),
            plan_approved=True,
            replacement_approved=replacement_approved,
        )
        result = resolved.orchestrator(
            orchestration_request,
            telegram_token=token,
            telegram_confirmation=confirmation,
        )
    except _UserCancelled:
        stdout.write("Installation cancelled.\n")
        return EXIT_CANCELLED
    except (EOFError, KeyboardInterrupt):
        stdout.write("\nInstallation cancelled.\n")
        return EXIT_CANCELLED
    except (TypeError, ValueError) as error:
        stderr.write(f"Invalid installer input: {error}\n")
        return EXIT_USAGE_ERROR
    except Exception:
        stderr.write("The guided installer failed unexpectedly.\n")
        return EXIT_INTERNAL_ERROR

    rendered = render_release_candidate_orchestration_result(result)
    target = (
        stdout
        if result.state is not ReleaseCandidateOrchestrationState.FAILED
        else stderr
    )
    target.write(rendered)

    if result.state is ReleaseCandidateOrchestrationState.SUCCEEDED:
        return EXIT_SUCCESS
    if result.state is ReleaseCandidateOrchestrationState.CANCELLED:
        return EXIT_CANCELLED
    if result.state is ReleaseCandidateOrchestrationState.FAILED:
        return EXIT_INSTALLATION_ERROR

    stderr.write(
        "The installer stopped before reaching a terminal orchestration state.\n"
    )
    return EXIT_INTERNAL_ERROR


def render_release_candidate_orchestration_result(
    result: ReleaseCandidateOrchestrationResult,
) -> str:
    """Render one stable human-readable orchestration result."""
    if not isinstance(result, ReleaseCandidateOrchestrationResult):
        raise TypeError("result must be a ReleaseCandidateOrchestrationResult value.")

    lines = [
        "LEA release-candidate installation",
        "",
        f"State: {result.state.value}",
        f"Mode: {result.request.installation.mode.value}",
        ("Telegram: enabled" if result.telegram_selected else "Telegram: disabled"),
        "",
        "Steps:",
    ]

    if not result.step_results:
        lines.append("- No installer steps completed.")
    else:
        for step in result.step_results:
            message_lines = step.message.splitlines() or [step.message]
            lines.append(
                f"- {step.step.value}: {step.state.value} — {message_lines[0]}"
            )
            lines.extend(f"  {line}" for line in message_lines[1:])

    if result.issues:
        lines.extend(("", "Issues:"))
        for issue in result.issues:
            field = f" [{issue.field}]" if issue.field is not None else ""
            path = f" ({issue.path})" if issue.path is not None else ""
            lines.append(f"- {issue.code.value}{field}: {issue.message}{path}")

    if result.pending_interaction is not None:
        lines.extend(
            (
                "",
                "Pending interaction:",
                f"- {result.pending_interaction.kind.value}: "
                f"{result.pending_interaction.prompt}",
            )
        )

    return "\n".join(lines) + "\n"


def _run_telegram_onboarding(
    *,
    stdout: TextIO,
    stderr: TextIO,
    text_input: TextInput,
    hidden_input: HiddenInput,
    client: TelegramOnboardingClient,
) -> tuple[str, TelegramOnboardingConfirmation]:
    """Resolve token, bot identity, user identity and role before mutation."""
    try:
        token = read_hidden_bot_token(hidden_input)
    except (TypeError, ValueError):
        raise ValueError("Telegram bot token is invalid.") from None

    validation = validate_bot_with_telegram(token, client)
    if not validation.success or validation.bot is None:
        _write_onboarding_issues(validation.issues, stderr=stderr)
        raise ValueError("Telegram bot validation failed.")

    bot = validation.bot
    stdout.write(
        "Telegram bot validated:\n"
        f"- Name: {bot.display_name}\n"
        f"- Username: @{bot.username}\n"
        f"- Bot ID: {bot.bot_id}\n\n"
        "Send /start to this bot from the private Telegram account "
        "that LEA should authorise.\n"
    )

    discovery = discover_telegram_start_identity(
        token,
        client,
        poll_timeout_seconds=30,
        maximum_attempts=10,
    )
    if discovery.cancelled:
        raise _UserCancelled
    if not discovery.success or discovery.identity is None:
        _write_onboarding_issues(discovery.issues, stderr=stderr)
        raise ValueError("Telegram identity discovery failed.")

    identity = discovery.identity
    _write_identity(identity, stdout=stdout)

    confirmed = _prompt_yes_no(
        "Authorise this Telegram identity? [y/N]: ",
        text_input=text_input,
        default=False,
    )
    if not confirmed:
        raise _UserCancelled

    role, capabilities = _select_telegram_role(
        text_input=text_input,
        stdout=stdout,
    )
    confirmation = confirm_telegram_identity(
        bot=bot,
        identity=identity,
        confirmed=True,
        role=role,
        custom_capabilities=capabilities,
    )
    return token, confirmation


def _select_telegram_role(
    *,
    text_input: TextInput,
    stdout: TextIO,
) -> tuple[TelegramOnboardingRole, tuple[ChannelCapability, ...]]:
    stdout.write(
        "\nTelegram role:\n"
        "1. owner — all current capabilities\n"
        "2. tester — bounded testing capabilities\n"
        "3. custom — explicitly selected capabilities\n"
    )
    selected = _prompt_number(
        "Select role [1-3]: ",
        minimum=1,
        maximum=3,
        text_input=text_input,
    )

    if selected == 1:
        return TelegramOnboardingRole.OWNER, ()
    if selected == 2:
        return TelegramOnboardingRole.TESTER, ()

    capabilities = tuple(sorted(ChannelCapability, key=lambda item: item.value))
    stdout.write("\nAvailable capabilities:\n")
    for index, capability in enumerate(capabilities, start=1):
        stdout.write(f"{index}. {capability.value}\n")

    while True:
        raw = text_input(
            "Select one or more capability numbers, separated by commas: "
        ).strip()
        try:
            indexes = {int(item.strip()) for item in raw.split(",") if item.strip()}
        except ValueError:
            indexes = set()

        if indexes and min(indexes) >= 1 and max(indexes) <= len(capabilities):
            selected_capabilities = tuple(
                capabilities[index - 1] for index in sorted(indexes)
            )
            return TelegramOnboardingRole.CUSTOM, selected_capabilities

        stdout.write("Enter at least one valid capability number.\n")


def _resolve_mode(
    supplied: str | None,
    *,
    non_interactive: bool,
    text_input: TextInput,
) -> ReleaseCandidateInstallMode:
    if supplied is not None:
        return ReleaseCandidateInstallMode(supplied)

    if non_interactive:
        raise ValueError("--mode is required in non-interactive mode.")

    choices = tuple(ReleaseCandidateInstallMode)
    selected = _prompt_number(
        "Installation mode: 1=fresh install, 2=upgrade, 3=repair [1-3]: ",
        minimum=1,
        maximum=3,
        text_input=text_input,
    )
    return choices[selected - 1]


def _resolve_timezone(
    supplied: str | None,
    *,
    non_interactive: bool,
    text_input: TextInput,
) -> str:
    if supplied is not None:
        timezone = supplied.strip()
    elif non_interactive:
        raise ValueError("--display-timezone is required in non-interactive mode.")
    else:
        timezone = (
            text_input("Display timezone [Africa/Gaborone]: ").strip()
            or "Africa/Gaborone"
        )

    if not timezone:
        raise ValueError("display timezone must be non-empty.")
    return timezone


def _resolve_telegram_selection(
    supplied: bool | None,
    *,
    non_interactive: bool,
    text_input: TextInput,
) -> bool:
    if supplied is not None:
        return supplied

    if non_interactive:
        raise ValueError(
            "--telegram or --no-telegram is required in non-interactive mode."
        )

    return _prompt_yes_no(
        "Enable Telegram? [Y/n]: ",
        text_input=text_input,
        default=True,
    )


def _taskwarrior_inputs(
    namespace: argparse.Namespace,
) -> ReleaseCandidateTaskwarriorInputs:
    archive: Path = namespace.taskwarrior_source_archive
    build_directory: Path = namespace.taskwarrior_build_directory

    if not archive.is_absolute():
        raise ValueError("--taskwarrior-source-archive must be an absolute path.")
    if not archive.is_file() or archive.is_symlink():
        raise ValueError("--taskwarrior-source-archive must be a regular file.")
    if not build_directory.is_absolute():
        raise ValueError("--taskwarrior-build-directory must be an absolute path.")

    return ReleaseCandidateTaskwarriorInputs(
        version=namespace.taskwarrior_version,
        platform=namespace.taskwarrior_platform,
        source_archive=archive,
        expected_sha256=namespace.taskwarrior_sha256,
        build_directory=build_directory,
        build_concurrency=namespace.taskwarrior_build_concurrency,
    )


def _prompt_yes_no(
    prompt: str,
    *,
    text_input: TextInput,
    default: bool,
) -> bool:
    while True:
        answer = text_input(prompt).strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False


def _prompt_number(
    prompt: str,
    *,
    minimum: int,
    maximum: int,
    text_input: TextInput,
) -> int:
    while True:
        raw = text_input(prompt).strip()
        try:
            selected = int(raw)
        except ValueError:
            continue
        if minimum <= selected <= maximum:
            return selected


def _write_identity(
    identity: TelegramOnboardingIdentity,
    *,
    stdout: TextIO,
) -> None:
    username = (
        f"@{identity.username}" if identity.username is not None else "not supplied"
    )
    stdout.write(
        "\nTelegram identity discovered:\n"
        f"- Name: {identity.display_name}\n"
        f"- Username: {username}\n"
        f"- User ID: {identity.user_id}\n"
        f"- Chat ID: {identity.chat_id}\n"
    )


def _write_onboarding_issues(
    issues: tuple[object, ...],
    *,
    stderr: TextIO,
) -> None:
    for issue in issues:
        code = getattr(issue, "code", "telegram_onboarding_failed")
        message = getattr(
            issue,
            "message",
            "Telegram onboarding failed.",
        )
        stderr.write(f"{code}: {message}\n")


def _normalise_argparse_exit(error: SystemExit) -> int:
    code = error.code
    return code if isinstance(code, int) else EXIT_USAGE_ERROR
