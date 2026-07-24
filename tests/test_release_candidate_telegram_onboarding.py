"""Tests for safe guided Telegram onboarding and discovery."""

import pytest

from lea.adapters.telegram import (
    TelegramFetchUpdatesResult,
    TelegramTransportIssue,
    TelegramUpdate,
)
from lea.channels import ChannelCapability
from lea.installers.release_candidate import (
    TelegramBotIdentity,
    TelegramBotValidationResult,
    TelegramOnboardingRole,
    confirm_telegram_identity,
    discover_telegram_start_identity,
    extract_start_identity,
    read_hidden_bot_token,
    validate_bot_with_telegram,
)
from lea.installers.release_candidate.telegram_onboarding import (
    TelegramOnboardingIssue,
)

TOKEN = "123456789:abcdefghijklmnopqrstuvwxyz_ABCDEFG"


class FakeOnboardingClient:
    """Deterministic onboarding client test double."""

    def __init__(self) -> None:
        self.validation_results: list[TelegramBotValidationResult] = []
        self.fetch_results: list[TelegramFetchUpdatesResult] = []
        self.tokens: list[str] = []

    def validate_bot_token(
        self,
        token: str,
    ) -> TelegramBotValidationResult:
        self.tokens.append(token)
        return self.validation_results.pop(0)

    def fetch_updates(
        self,
        token: str,
        *,
        offset: int | None,
        limit: int,
        timeout_seconds: int,
    ) -> TelegramFetchUpdatesResult:
        self.tokens.append(token)
        return self.fetch_results.pop(0)


def _bot() -> TelegramBotIdentity:
    return TelegramBotIdentity(
        bot_id="987654321",
        username="lea_test_bot",
        display_name="LEA Test Bot",
    )


def _start(
    update_id: int = 42,
    *,
    text: str = "/start",
) -> TelegramUpdate:
    return TelegramUpdate(
        update_id=update_id,
        payload={
            "message": {
                "message_id": 7,
                "from": {
                    "id": 123456789,
                    "first_name": "Marius",
                    "last_name": "Example",
                    "username": "marius_example",
                },
                "chat": {
                    "id": 123456789,
                    "type": "private",
                },
                "text": text,
            }
        },
    )


def test_hidden_token_reader_never_transforms_token() -> None:
    """Hidden input should return the validated token exactly."""
    prompts: list[str] = []

    def hidden(prompt: str) -> str:
        prompts.append(prompt)
        return TOKEN

    assert read_hidden_bot_token(hidden) == TOKEN
    assert prompts == ["Telegram bot token: "]


def test_invalid_token_shape_is_rejected_without_echo() -> None:
    """Invalid tokens should fail with a generic message."""
    with pytest.raises(
        ValueError,
        match="invalid shape",
    ) as captured:
        read_hidden_bot_token(lambda _prompt: "secret")

    assert "secret" not in str(captured.value)


def test_get_me_validation_uses_injected_client() -> None:
    """Token validation should use the injected getMe boundary."""
    client = FakeOnboardingClient()
    client.validation_results.append(TelegramBotValidationResult(True, _bot(), ()))

    result = validate_bot_with_telegram(TOKEN, client)

    assert result.success is True
    assert result.bot == _bot()
    assert client.tokens == [TOKEN]


def test_get_me_failure_result_is_redacted() -> None:
    """Returned client issues must not expose token-derived fields."""
    client = FakeOnboardingClient()
    client.validation_results.append(
        TelegramBotValidationResult(
            success=False,
            bot=None,
            issues=(
                TelegramOnboardingIssue(
                    code=f"token-{TOKEN}",
                    message=f"token={TOKEN}",
                    operation=f"get_me_{TOKEN}",
                ),
            ),
        )
    )

    result = validate_bot_with_telegram(TOKEN, client)

    assert result.success is False
    assert result.issues[0].code == "telegram_get_me_rejected"
    assert TOKEN not in result.issues[0].code
    assert TOKEN not in result.issues[0].message
    assert TOKEN not in result.issues[0].operation


def test_get_me_exception_is_redacted() -> None:
    """Client exceptions must not expose token or exception details."""

    class FailingClient(FakeOnboardingClient):
        def validate_bot_token(
            self,
            token: str,
        ) -> TelegramBotValidationResult:
            raise RuntimeError(f"failed token={token}")

    result = validate_bot_with_telegram(TOKEN, FailingClient())

    assert result.success is False
    assert TOKEN not in result.issues[0].message


def test_extracts_private_start_identity() -> None:
    """A real private /start update should produce exact identity fields."""
    identity = extract_start_identity(_start())

    assert identity is not None
    assert identity.user_id == "123456789"
    assert identity.chat_id == "123456789"
    assert identity.username == "marius_example"
    assert identity.display_name == "Marius Example"


@pytest.mark.parametrize(
    "update",
    (
        _start(text="/status"),
        TelegramUpdate(
            update_id=43,
            payload={
                "message": {
                    "from": {"id": 1, "first_name": "Group User"},
                    "chat": {"id": 2, "type": "group"},
                    "text": "/start",
                }
            },
        ),
        TelegramUpdate(update_id=44, payload={"edited_message": {}}),
    ),
)
def test_non_private_start_updates_are_ignored(
    update: TelegramUpdate,
) -> None:
    """Only private /start messages may establish an identity."""
    assert extract_start_identity(update) is None


def test_discovery_skips_unrelated_updates_then_succeeds() -> None:
    """Bounded polling should advance offsets and find a later /start."""
    client = FakeOnboardingClient()
    client.fetch_results.extend(
        (
            TelegramFetchUpdatesResult(
                True,
                (_start(40, text="/status"),),
                (),
            ),
            TelegramFetchUpdatesResult(True, (_start(42),), ()),
        )
    )

    result = discover_telegram_start_identity(
        TOKEN,
        client,
        maximum_attempts=2,
    )

    assert result.success is True
    assert result.identity is not None
    assert result.identity.update_id == 42
    assert result.next_offset == 43


def test_discovery_can_be_cancelled_before_networking() -> None:
    """Cancellation should return cleanly without fetching updates."""
    client = FakeOnboardingClient()

    result = discover_telegram_start_identity(
        TOKEN,
        client,
        cancelled=lambda: True,
    )

    assert result.success is False
    assert result.cancelled is True
    assert client.tokens == []


def test_discovery_timeout_is_structured() -> None:
    """Exhausted bounded polling should return a timeout issue."""
    client = FakeOnboardingClient()
    client.fetch_results.extend(
        (
            TelegramFetchUpdatesResult(True, (), ()),
            TelegramFetchUpdatesResult(True, (), ()),
        )
    )

    result = discover_telegram_start_identity(
        TOKEN,
        client,
        maximum_attempts=2,
    )

    assert result.success is False
    assert result.issues[0].code == "telegram_start_timeout"


def test_discovery_fetch_failure_is_redacted() -> None:
    """Transport failures should become safe onboarding issues."""
    client = FakeOnboardingClient()
    client.fetch_results.append(
        TelegramFetchUpdatesResult(
            False,
            (),
            (
                TelegramTransportIssue(
                    code="network",
                    message=f"token={TOKEN}",
                    operation="fetch_updates",
                ),
            ),
        )
    )

    result = discover_telegram_start_identity(TOKEN, client)

    assert result.success is False
    assert TOKEN not in result.issues[0].message


def test_owner_confirmation_uses_no_custom_capabilities() -> None:
    """Built-in owner selection should create a consistent decision."""
    identity = extract_start_identity(_start())
    assert identity is not None

    confirmation = confirm_telegram_identity(
        bot=_bot(),
        identity=identity,
        confirmed=True,
        role=TelegramOnboardingRole.OWNER,
    )

    assert confirmation.confirmed is True
    assert confirmation.custom_capabilities == ()


def test_custom_confirmation_requires_capabilities() -> None:
    """Custom roles must declare at least one explicit capability."""
    identity = extract_start_identity(_start())
    assert identity is not None

    with pytest.raises(
        ValueError,
        match="at least one capability",
    ):
        confirm_telegram_identity(
            bot=_bot(),
            identity=identity,
            confirmed=True,
            role=TelegramOnboardingRole.CUSTOM,
        )

    confirmation = confirm_telegram_identity(
        bot=_bot(),
        identity=identity,
        confirmed=True,
        role=TelegramOnboardingRole.CUSTOM,
        custom_capabilities=(ChannelCapability.TASKS_READ,),
    )

    assert confirmation.custom_capabilities == (ChannelCapability.TASKS_READ,)


def test_rejected_confirmation_has_no_role() -> None:
    """A rejected identity must not retain authorisation choices."""
    identity = extract_start_identity(_start())
    assert identity is not None

    confirmation = confirm_telegram_identity(
        bot=_bot(),
        identity=identity,
        confirmed=False,
    )

    assert confirmation.role is None
