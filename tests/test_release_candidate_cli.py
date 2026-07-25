"""Tests for the guided release-candidate installer CLI."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from lea.adapters.telegram import (
    TelegramFetchUpdatesResult,
    TelegramUpdate,
)
from lea.installers.release_candidate import (
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
    ) -> ReleaseCandidateOrchestrationResult:
        self.calls.append(
            (
                request,
                telegram_token,
                telegram_confirmation,
            )
        )
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
