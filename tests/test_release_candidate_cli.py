"""Tests for the guided release-candidate installer CLI."""

from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from lea.adapters.telegram import (
    TelegramFetchUpdatesResult,
    TelegramUpdate,
)
from lea.installers.release_candidate import (
    InstallerProgressReporter,
    InstallerStepId,
    InstallerStepResult,
    InstallerStepState,
    ReleaseCandidateOrchestrationRequest,
    ReleaseCandidateOrchestrationResult,
    ReleaseCandidateOrchestrationState,
    TelegramBotIdentity,
    TelegramBotValidationResult,
    TelegramOnboardingConfirmation,
)
from lea.release_candidate_cli import (
    EXIT_CANCELLED,
    EXIT_SUCCESS,
    EXIT_USAGE_ERROR,
    ReleaseCandidateCliDependencies,
    create_release_candidate_parser,
    execute_release_candidate_cli,
)


class Inputs:
    """Deterministic guided text input."""

    def __init__(self, values: tuple[str, ...]) -> None:
        self.values = list(values)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.values:
            raise AssertionError(f"Unexpected prompt: {prompt}")
        return self.values.pop(0)


class FakeOnboardingClient:
    """Deterministic successful Telegram onboarding client."""

    def validate_bot_token(
        self,
        token: str,
    ) -> TelegramBotValidationResult:
        assert token == "123456789:abcdefghijklmnopqrstuvwxyz_ABCDEFG"
        return TelegramBotValidationResult(
            success=True,
            bot=TelegramBotIdentity(
                bot_id="987654321",
                username="lea_test_bot",
                display_name="LEA Test Bot",
            ),
            issues=(),
        )

    def fetch_updates(
        self,
        token: str,
        *,
        offset: int | None,
        limit: int,
        timeout_seconds: int,
    ) -> TelegramFetchUpdatesResult:
        assert token == "123456789:abcdefghijklmnopqrstuvwxyz_ABCDEFG"
        assert offset is None
        assert limit == 100
        assert timeout_seconds == 30
        return TelegramFetchUpdatesResult(
            success=True,
            updates=(
                TelegramUpdate(
                    update_id=42,
                    payload={
                        "message": {
                            "message_id": 7,
                            "from": {
                                "id": 123456789,
                                "first_name": "Marius",
                                "username": "marius_example",
                            },
                            "chat": {
                                "id": 123456789,
                                "type": "private",
                            },
                            "text": "/start",
                        }
                    },
                ),
            ),
            issues=(),
        )


class RecordingOrchestrator:
    """Return success while recording secret and resolved request."""

    def __init__(self) -> None:
        self.calls: list[
            tuple[
                ReleaseCandidateOrchestrationRequest,
                str | None,
                TelegramOnboardingConfirmation | None,
            ]
        ] = []

    def __call__(
        self,
        request: ReleaseCandidateOrchestrationRequest,
        *,
        telegram_token: str | None = None,
        telegram_confirmation: TelegramOnboardingConfirmation | None = None,
        progress: InstallerProgressReporter | None = None,
    ) -> ReleaseCandidateOrchestrationResult:
        self.calls.append(
            (
                request,
                telegram_token,
                telegram_confirmation,
            )
        )

        if progress is not None:
            progress.detail("Recording orchestrator invoked.")
        return ReleaseCandidateOrchestrationResult(
            state=ReleaseCandidateOrchestrationState.SUCCEEDED,
            request=request,
            current_step=None,
            step_results=(
                InstallerStepResult(
                    step=InstallerStepId.ACCEPTANCE,
                    state=InstallerStepState.COMPLETED,
                    message=(
                        "LEA release-candidate acceptance: PASSED\n"
                        "- taskwarrior_lifecycle: passed"
                    ),
                ),
            ),
            telegram_selected=request.installation.enable_telegram,
            pending_interaction=None,
            issues=(),
        )


def _archive(tmp_path: Path) -> Path:
    archive = tmp_path / "task-3.4.2.tar.gz"
    archive.write_bytes(b"source")
    return archive


def _base_arguments(
    tmp_path: Path,
    *,
    telegram: bool,
) -> list[str]:
    return [
        "--mode",
        "fresh-install",
        "--display-timezone",
        "Africa/Gaborone",
        "--telegram" if telegram else "--no-telegram",
        "--taskwarrior-source-archive",
        str(_archive(tmp_path)),
        "--taskwarrior-sha256",
        "a" * 64,
        "--taskwarrior-build-directory",
        str(tmp_path / "build"),
        "--approve",
    ]


def test_non_telegram_guided_run_succeeds(tmp_path: Path) -> None:
    orchestrator = RecordingOrchestrator()
    stdout = StringIO()
    stderr = StringIO()

    exit_code = execute_release_candidate_cli(
        _base_arguments(tmp_path, telegram=False),
        stdout=stdout,
        stderr=stderr,
        dependencies=ReleaseCandidateCliDependencies(
            text_input=Inputs(()),
            hidden_input=lambda _prompt: "",
            onboarding_client_factory=FakeOnboardingClient,
            version_reader=lambda: "0.1.0",
            orchestrator=orchestrator,
        ),
    )

    assert exit_code == EXIT_SUCCESS
    assert len(orchestrator.calls) == 1
    assert orchestrator.calls[0][1] is None
    assert "LEA release-candidate installation plan" in stdout.getvalue()
    assert "acceptance: PASSED" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_telegram_run_uses_hidden_token_and_confirmed_owner(
    tmp_path: Path,
) -> None:
    orchestrator = RecordingOrchestrator()
    stdout = StringIO()
    stderr = StringIO()
    token = "123456789:abcdefghijklmnopqrstuvwxyz_ABCDEFG"

    exit_code = execute_release_candidate_cli(
        _base_arguments(tmp_path, telegram=True),
        stdout=stdout,
        stderr=stderr,
        dependencies=ReleaseCandidateCliDependencies(
            text_input=Inputs(("yes", "1")),
            hidden_input=lambda prompt: token,
            onboarding_client_factory=FakeOnboardingClient,
            version_reader=lambda: "0.1.0",
            orchestrator=orchestrator,
        ),
    )

    assert exit_code == EXIT_SUCCESS
    assert orchestrator.calls[0][1] == token
    confirmation = orchestrator.calls[0][2]
    assert confirmation is not None
    assert confirmation.confirmed is True
    assert confirmation.role is not None
    assert confirmation.role.value == "owner"
    assert token not in stdout.getvalue()
    assert token not in stderr.getvalue()


def test_declining_rendered_plan_cancels_before_orchestration(
    tmp_path: Path,
) -> None:
    orchestrator = RecordingOrchestrator()
    stdout = StringIO()

    arguments = _base_arguments(tmp_path, telegram=False)
    arguments.remove("--approve")

    exit_code = execute_release_candidate_cli(
        arguments,
        stdout=stdout,
        stderr=StringIO(),
        dependencies=ReleaseCandidateCliDependencies(
            text_input=Inputs(("no",)),
            hidden_input=lambda _prompt: "",
            onboarding_client_factory=FakeOnboardingClient,
            version_reader=lambda: "0.1.0",
            orchestrator=orchestrator,
        ),
    )

    assert exit_code == EXIT_CANCELLED
    assert orchestrator.calls == []
    assert "Installation cancelled." in stdout.getvalue()


def test_relative_source_archive_is_usage_error(tmp_path: Path) -> None:
    stderr = StringIO()
    arguments = _base_arguments(tmp_path, telegram=False)
    archive_index = arguments.index("--taskwarrior-source-archive") + 1
    arguments[archive_index] = "task-3.4.2.tar.gz"

    exit_code = execute_release_candidate_cli(
        arguments,
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == EXIT_USAGE_ERROR
    assert "must be an absolute path" in stderr.getvalue()


def test_non_interactive_telegram_is_rejected(tmp_path: Path) -> None:
    stderr = StringIO()
    arguments = [
        *_base_arguments(tmp_path, telegram=True),
        "--non-interactive",
    ]

    exit_code = execute_release_candidate_cli(
        arguments,
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == EXIT_USAGE_ERROR
    assert "non-interactive Telegram onboarding" in stderr.getvalue()


def test_output_mode_defaults_to_normal() -> None:
    """Installer output should default to normal mode."""
    parser = create_release_candidate_parser()

    namespace = parser.parse_args(
        [
            "--taskwarrior-source-archive",
            "/tmp/task-3.4.2.tar.gz",
            "--taskwarrior-sha256",
            "a" * 64,
        ]
    )

    assert namespace.output_mode == "normal"


def test_output_modes_are_mutually_exclusive() -> None:
    """Only one installer output mode may be selected."""
    parser = create_release_candidate_parser()
    stderr = StringIO()

    try:
        with redirect_stderr(stderr):
            parser.parse_args(
                [
                    "--quiet",
                    "--verbose",
                    "--taskwarrior-source-archive",
                    "/tmp/task-3.4.2.tar.gz",
                    "--taskwarrior-sha256",
                    "a" * 64,
                ]
            )
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError("Expected mutually exclusive output-mode rejection.")

    assert "not allowed with argument" in stderr.getvalue()


def test_quiet_mode_suppresses_plan_but_keeps_final_result(
    tmp_path: Path,
) -> None:
    """Quiet mode should omit the plan and retain the final result."""
    orchestrator = RecordingOrchestrator()
    stdout = StringIO()
    stderr = StringIO()

    exit_code = execute_release_candidate_cli(
        [
            *_base_arguments(tmp_path, telegram=False),
            "--quiet",
        ],
        stdout=stdout,
        stderr=stderr,
        dependencies=ReleaseCandidateCliDependencies(
            text_input=Inputs(()),
            hidden_input=lambda _prompt: "",
            onboarding_client_factory=FakeOnboardingClient,
            version_reader=lambda: "0.1.0",
            orchestrator=orchestrator,
        ),
    )

    assert exit_code == EXIT_SUCCESS
    assert "LEA release-candidate installation plan" not in stdout.getvalue()
    assert "LEA release-candidate installation" in stdout.getvalue()
    assert "State: succeeded" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_verbose_mode_retains_current_normal_output(
    tmp_path: Path,
) -> None:
    """Verbose mode should retain ordinary output before streaming is added."""
    stdout = StringIO()

    exit_code = execute_release_candidate_cli(
        [
            *_base_arguments(tmp_path, telegram=False),
            "--verbose",
        ],
        stdout=stdout,
        stderr=StringIO(),
        dependencies=ReleaseCandidateCliDependencies(
            text_input=Inputs(()),
            hidden_input=lambda _prompt: "",
            onboarding_client_factory=FakeOnboardingClient,
            version_reader=lambda: "0.1.0",
            orchestrator=RecordingOrchestrator(),
        ),
    )

    assert exit_code == EXIT_SUCCESS
    assert "LEA release-candidate installation plan" in stdout.getvalue()
    assert "State: succeeded" in stdout.getvalue()


def test_normal_mode_suppresses_verbose_details(
    tmp_path: Path,
) -> None:
    """Normal output should omit reporter detail events."""
    stdout = StringIO()

    exit_code = execute_release_candidate_cli(
        _base_arguments(tmp_path, telegram=False),
        stdout=stdout,
        stderr=StringIO(),
        dependencies=ReleaseCandidateCliDependencies(
            text_input=Inputs(()),
            hidden_input=lambda _prompt: "",
            onboarding_client_factory=FakeOnboardingClient,
            version_reader=lambda: "0.1.0",
            orchestrator=RecordingOrchestrator(),
        ),
    )

    assert exit_code == EXIT_SUCCESS
    assert "Recording orchestrator invoked." not in stdout.getvalue()


def test_verbose_mode_renders_reporter_details(
    tmp_path: Path,
) -> None:
    """Verbose output should render operational detail events."""
    stdout = StringIO()

    exit_code = execute_release_candidate_cli(
        [
            *_base_arguments(tmp_path, telegram=False),
            "--verbose",
        ],
        stdout=stdout,
        stderr=StringIO(),
        dependencies=ReleaseCandidateCliDependencies(
            text_input=Inputs(()),
            hidden_input=lambda _prompt: "",
            onboarding_client_factory=FakeOnboardingClient,
            version_reader=lambda: "0.1.0",
            orchestrator=RecordingOrchestrator(),
        ),
    )

    assert exit_code == EXIT_SUCCESS
    assert "[detail] Recording orchestrator invoked." in stdout.getvalue()


def test_quiet_mode_suppresses_reporter_details(
    tmp_path: Path,
) -> None:
    """Quiet output should suppress operational detail events."""
    stdout = StringIO()

    exit_code = execute_release_candidate_cli(
        [
            *_base_arguments(tmp_path, telegram=False),
            "--quiet",
        ],
        stdout=stdout,
        stderr=StringIO(),
        dependencies=ReleaseCandidateCliDependencies(
            text_input=Inputs(()),
            hidden_input=lambda _prompt: "",
            onboarding_client_factory=FakeOnboardingClient,
            version_reader=lambda: "0.1.0",
            orchestrator=RecordingOrchestrator(),
        ),
    )

    assert exit_code == EXIT_SUCCESS
    assert "Recording orchestrator invoked." not in stdout.getvalue()
