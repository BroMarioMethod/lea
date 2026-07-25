"""Safe guided Telegram onboarding contracts and identity discovery."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from lea.adapters.telegram import TelegramFetchUpdatesResult, TelegramUpdate
from lea.channels import ChannelCapability

_TOKEN_PATTERN = re.compile(r"^[1-9][0-9]{5,15}:[A-Za-z0-9_-]{20,}$")


class TelegramOnboardingRole(StrEnum):
    """Roles selectable during guided Telegram onboarding."""

    CUSTOM = "custom"
    OWNER = "owner"
    TESTER = "tester"


@dataclass(frozen=True, slots=True)
class TelegramBotIdentity:
    """Validated non-secret identity returned by Telegram getMe."""

    bot_id: str
    username: str
    display_name: str

    def __post_init__(self) -> None:
        """Validate the bot identity."""
        _validate_identifier(self.bot_id, field_name="bot_id")

        if not self.username.strip() or self.username.startswith("@"):
            raise ValueError("username must be non-empty and omit the leading '@'.")

        if not self.display_name.strip():
            raise ValueError("display_name must be non-empty.")


@dataclass(frozen=True, slots=True)
class TelegramOnboardingIdentity:
    """One private Telegram identity discovered through a real /start."""

    update_id: int
    user_id: str
    chat_id: str
    username: str | None
    display_name: str

    def __post_init__(self) -> None:
        """Validate discovered identity fields."""
        if isinstance(self.update_id, bool) or self.update_id < 1:
            raise ValueError("update_id must be a positive integer.")

        _validate_identifier(self.user_id, field_name="user_id")
        _validate_identifier(self.chat_id, field_name="chat_id")

        if self.username is not None and (
            not self.username.strip() or self.username.startswith("@")
        ):
            raise ValueError("username must be non-empty and omit the leading '@'.")

        if not self.display_name.strip():
            raise ValueError("display_name must be non-empty.")


@dataclass(frozen=True, slots=True)
class TelegramOnboardingIssue:
    """One safe issue that never contains the bot token."""

    code: str
    message: str
    operation: str

    def __post_init__(self) -> None:
        """Validate safe issue fields."""
        for field_name, value in (
            ("code", self.code),
            ("message", self.message),
            ("operation", self.operation),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty.")


@dataclass(frozen=True, slots=True)
class TelegramBotValidationResult:
    """Result of validating one token through Telegram getMe."""

    success: bool
    bot: TelegramBotIdentity | None
    issues: tuple[TelegramOnboardingIssue, ...]

    def __post_init__(self) -> None:
        """Validate result consistency."""
        _validate_optional_result(
            success=self.success,
            value=self.bot,
            issues=self.issues,
            operation="get_me",
        )


@dataclass(frozen=True, slots=True)
class TelegramIdentityDiscoveryResult:
    """Result of waiting for a private /start update."""

    success: bool
    cancelled: bool
    identity: TelegramOnboardingIdentity | None
    next_offset: int | None
    issues: tuple[TelegramOnboardingIssue, ...]

    def __post_init__(self) -> None:
        """Validate discovery-result consistency."""
        if self.next_offset is not None and self.next_offset < 1:
            raise ValueError("next_offset must be positive when provided.")

        if self.success:
            if self.cancelled:
                raise ValueError("A successful discovery must not be cancelled.")
            if self.identity is None:
                raise ValueError("A successful discovery must contain an identity.")
            if self.issues:
                raise ValueError("A successful discovery must not contain issues.")
            return

        if self.identity is not None:
            raise ValueError("A failed discovery must not contain an identity.")

        if self.cancelled:
            if self.issues:
                raise ValueError("A cancelled discovery must not contain issues.")
            return

        if not self.issues:
            raise ValueError("A failed discovery must contain at least one issue.")


@dataclass(frozen=True, slots=True)
class TelegramOnboardingConfirmation:
    """Confirmed identity and selected authorisation role."""

    bot: TelegramBotIdentity
    identity: TelegramOnboardingIdentity
    confirmed: bool
    role: TelegramOnboardingRole | None
    custom_capabilities: tuple[ChannelCapability, ...] = ()

    def __post_init__(self) -> None:
        """Validate role and capability consistency."""
        capabilities = tuple(sorted(set(self.custom_capabilities), key=str))
        object.__setattr__(self, "custom_capabilities", capabilities)

        if not self.confirmed:
            if self.role is not None or capabilities:
                raise ValueError("A rejected confirmation must not contain a role.")
            return

        if self.role is None:
            raise ValueError("A confirmed identity must contain a selected role.")

        if self.role is TelegramOnboardingRole.CUSTOM:
            if not capabilities:
                raise ValueError("A custom role must contain at least one capability.")
        elif capabilities:
            raise ValueError("Built-in roles must not contain custom capabilities.")


@runtime_checkable
class TelegramOnboardingClient(Protocol):
    """Network boundary used by guided Telegram onboarding."""

    def validate_bot_token(
        self,
        token: str,
    ) -> TelegramBotValidationResult:
        """Validate a token using Telegram getMe."""
        ...

    def fetch_updates(
        self,
        token: str,
        *,
        offset: int | None,
        limit: int,
        timeout_seconds: int,
    ) -> TelegramFetchUpdatesResult:
        """Fetch Telegram updates using the supplied token."""
        ...


HiddenInput = Callable[[str], str]
CancellationSignal = Callable[[], bool]


def read_hidden_bot_token(
    hidden_input: HiddenInput,
    *,
    prompt: str = "Telegram bot token: ",
) -> str:
    """Read and validate a token through an injected hidden-input boundary."""
    token = hidden_input(prompt)
    validate_bot_token_shape(token)
    return token


def validate_bot_token_shape(token: str) -> None:
    """Validate the BotFather token shape without exposing its value."""
    if not isinstance(token, str):
        raise TypeError("token must be a string.")

    if _TOKEN_PATTERN.fullmatch(token) is None:
        raise ValueError("Telegram bot token has an invalid shape.")


def validate_bot_with_telegram(
    token: str,
    client: TelegramOnboardingClient,
) -> TelegramBotValidationResult:
    """Validate one token through the injected getMe boundary."""
    validate_bot_token_shape(token)

    try:
        result = client.validate_bot_token(token)
    except Exception:
        return TelegramBotValidationResult(
            success=False,
            bot=None,
            issues=(
                TelegramOnboardingIssue(
                    code="telegram_get_me_failed",
                    message=("Telegram could not validate the supplied bot token."),
                    operation="get_me",
                ),
            ),
        )

    if result.success:
        return result

    return TelegramBotValidationResult(
        success=False,
        bot=None,
        issues=(
            TelegramOnboardingIssue(
                code="telegram_get_me_rejected",
                message="Telegram rejected the supplied bot token.",
                operation="get_me",
            ),
        ),
    )


def discover_telegram_start_identity(
    token: str,
    client: TelegramOnboardingClient,
    *,
    offset: int | None = None,
    poll_timeout_seconds: int = 30,
    maximum_attempts: int = 10,
    cancelled: CancellationSignal = lambda: False,
) -> TelegramIdentityDiscoveryResult:
    """Wait for a real private /start update using bounded polling."""
    validate_bot_token_shape(token)

    if poll_timeout_seconds < 1 or poll_timeout_seconds > 50:
        raise ValueError("poll_timeout_seconds must be between 1 and 50.")

    if maximum_attempts < 1:
        raise ValueError("maximum_attempts must be greater than zero.")

    next_offset = offset
    successful_fetch_observed = False
    fetch_failure_observed = False

    for _attempt in range(maximum_attempts):
        if cancelled():
            return TelegramIdentityDiscoveryResult(
                success=False,
                cancelled=True,
                identity=None,
                next_offset=next_offset,
                issues=(),
            )

        try:
            fetched = client.fetch_updates(
                token,
                offset=next_offset,
                limit=100,
                timeout_seconds=poll_timeout_seconds,
            )
        except Exception:
            fetched = None

        if fetched is None or not fetched.success:
            fetch_failure_observed = True
            continue

        successful_fetch_observed = True

        for update in fetched.updates:
            next_offset = update.update_id + 1
            identity = extract_start_identity(update)
            if identity is not None:
                return TelegramIdentityDiscoveryResult(
                    success=True,
                    cancelled=False,
                    identity=identity,
                    next_offset=next_offset,
                    issues=(),
                )

    if fetch_failure_observed and not successful_fetch_observed:
        issue = TelegramOnboardingIssue(
            code="telegram_onboarding_fetch_failed",
            message=("Telegram updates could not be fetched during onboarding."),
            operation="get_updates",
        )
    else:
        issue = TelegramOnboardingIssue(
            code="telegram_start_timeout",
            message=(
                "No private /start message was received within the "
                "configured onboarding attempts."
            ),
            operation="get_updates",
        )

    return TelegramIdentityDiscoveryResult(
        success=False,
        cancelled=False,
        identity=None,
        next_offset=next_offset,
        issues=(issue,),
    )


def extract_start_identity(
    update: TelegramUpdate,
) -> TelegramOnboardingIdentity | None:
    """Extract one private /start identity from a raw Telegram update."""
    message = _mapping(update.payload.get("message"))
    if message is None:
        return None

    text = message.get("text")
    if not isinstance(text, str):
        return None

    command = text.strip().split(maxsplit=1)[0]
    if command != "/start" and not command.startswith("/start@"):
        return None

    sender = _mapping(message.get("from"))
    chat = _mapping(message.get("chat"))
    if sender is None or chat is None or chat.get("type") != "private":
        return None

    user_id = _identifier(sender.get("id"))
    chat_id = _identifier(chat.get("id"))
    if user_id is None or chat_id is None:
        return None

    first_name = sender.get("first_name")
    last_name = sender.get("last_name")
    if not isinstance(first_name, str) or not first_name.strip():
        return None

    display_parts = [first_name.strip()]
    if isinstance(last_name, str) and last_name.strip():
        display_parts.append(last_name.strip())

    username_value = sender.get("username")
    username = (
        username_value
        if isinstance(username_value, str) and username_value.strip()
        else None
    )

    try:
        return TelegramOnboardingIdentity(
            update_id=update.update_id,
            user_id=user_id,
            chat_id=chat_id,
            username=username,
            display_name=" ".join(display_parts),
        )
    except (TypeError, ValueError):
        return None


def confirm_telegram_identity(
    *,
    bot: TelegramBotIdentity,
    identity: TelegramOnboardingIdentity,
    confirmed: bool,
    role: TelegramOnboardingRole | None = None,
    custom_capabilities: tuple[ChannelCapability, ...] = (),
) -> TelegramOnboardingConfirmation:
    """Create an explicit onboarding confirmation decision."""
    return TelegramOnboardingConfirmation(
        bot=bot,
        identity=identity,
        confirmed=confirmed,
        role=role,
        custom_capabilities=custom_capabilities,
    )


def _mapping(value: object) -> Mapping[str, object] | None:
    """Return a string-keyed mapping or None."""
    if not isinstance(value, Mapping):
        return None

    if not all(isinstance(key, str) for key in value):
        return None

    return value


def _identifier(value: object) -> str | None:
    """Return a canonical positive Telegram identifier."""
    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        return None

    try:
        _validate_identifier(text, field_name="identifier")
    except ValueError:
        return None

    return text


def _validate_identifier(value: str, *, field_name: str) -> None:
    """Validate one canonical positive Telegram identifier."""
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isdecimal()
        or value.startswith("0")
        or int(value) < 1
    ):
        raise ValueError(f"{field_name} must use a canonical positive decimal string.")


def _validate_optional_result(
    *,
    success: bool,
    value: object | None,
    issues: tuple[TelegramOnboardingIssue, ...],
    operation: str,
) -> None:
    """Validate one optional-value result."""
    if success:
        if value is None:
            raise ValueError(f"A successful {operation} result must contain a value.")
        if issues:
            raise ValueError(
                f"A successful {operation} result must not contain issues."
            )
        return

    if value is not None:
        raise ValueError(f"A failed {operation} result must not contain a value.")

    if not issues:
        raise ValueError(
            f"A failed {operation} result must contain at least one issue."
        )
