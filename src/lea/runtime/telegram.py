"""Deterministic construction of Telegram runtime dependencies."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lea.adapters.telegram import (
    TELEGRAM_MAX_FETCH_LIMIT,
    FileTelegramOffsetStore,
    TelegramOffsetStore,
    TelegramTransport,
)
from lea.channels import (
    AuthorisedChannelUser,
    load_authorised_channel_users,
)
from lea.runtime.contracts import RuntimeConfig

_MIN_POLL_TIMEOUT_SECONDS = 1
_MAX_POLL_TIMEOUT_SECONDS = 50
_TOKEN_PATTERN = re.compile(r"^[1-9][0-9]{5,15}:[A-Za-z0-9_-]{20,}$")
_BOT_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{5,32}$")


TelegramTransportFactory = Callable[[str], TelegramTransport]
"""Factory boundary for constructing a Telegram transport."""


@dataclass(frozen=True, slots=True)
class TelegramRuntimeConfig:
    """Validated Telegram-specific runtime configuration."""

    enabled: bool
    bot_username: str
    authorised_users_file: Path
    offset_file: Path
    poll_timeout_seconds: int = 30
    fetch_limit: int = 100

    def __post_init__(self) -> None:
        """Validate deterministic Telegram runtime settings."""
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean.")

        if not isinstance(self.bot_username, str):
            raise TypeError("bot_username must be a string.")

        if (
            not _BOT_USERNAME_PATTERN.fullmatch(self.bot_username)
            or not self.bot_username.casefold().endswith("bot")
            or self.bot_username.startswith("@")
        ):
            raise ValueError(
                "bot_username must be a 5-32 character Telegram bot username "
                "without a leading '@'."
            )

        _validate_absolute_path(
            self.authorised_users_file,
            field_name="authorised_users_file",
        )
        _validate_absolute_path(
            self.offset_file,
            field_name="offset_file",
        )
        _validate_integer(
            self.poll_timeout_seconds,
            field_name="poll_timeout_seconds",
        )
        _validate_integer(
            self.fetch_limit,
            field_name="fetch_limit",
        )

        if not (
            _MIN_POLL_TIMEOUT_SECONDS
            <= self.poll_timeout_seconds
            <= _MAX_POLL_TIMEOUT_SECONDS
        ):
            raise ValueError(
                "poll_timeout_seconds must be between "
                f"{_MIN_POLL_TIMEOUT_SECONDS} and "
                f"{_MAX_POLL_TIMEOUT_SECONDS}."
            )

        if not 1 <= self.fetch_limit <= TELEGRAM_MAX_FETCH_LIMIT:
            raise ValueError(
                f"fetch_limit must be between 1 and {TELEGRAM_MAX_FETCH_LIMIT}."
            )


@dataclass(frozen=True, slots=True)
class TelegramRuntimeDependencies:
    """Assembled dependencies for the foreground Telegram worker."""

    config: TelegramRuntimeConfig
    authorised_users: tuple[AuthorisedChannelUser, ...]
    offset_store: TelegramOffsetStore
    transport: TelegramTransport

    def __post_init__(self) -> None:
        """Validate dependency consistency."""
        if not self.config.enabled:
            raise ValueError(
                "Telegram runtime dependencies require enabled configuration."
            )

        if not self.authorised_users:
            raise ValueError("Telegram runtime dependencies require authorised users.")


@dataclass(frozen=True, slots=True)
class TelegramRuntimeIssue:
    """One deterministic Telegram runtime-construction problem."""

    code: str
    message: str
    field: str | None = None
    source_path: Path | None = None

    def __post_init__(self) -> None:
        """Validate safe issue fields."""
        if not self.code.strip():
            raise ValueError("Telegram runtime issue code must be non-empty.")

        if not self.message.strip():
            raise ValueError("Telegram runtime issue message must be non-empty.")

        if self.field is not None and not self.field.strip():
            raise ValueError(
                "Telegram runtime issue field must be non-empty when provided."
            )

        if self.source_path is not None and not self.source_path.is_absolute():
            raise ValueError("Telegram runtime issue source_path must be absolute.")


@dataclass(frozen=True, slots=True)
class TelegramRuntimeResult:
    """Immutable result of constructing Telegram runtime dependencies."""

    success: bool
    dependencies: TelegramRuntimeDependencies | None
    issues: tuple[TelegramRuntimeIssue, ...]

    def __post_init__(self) -> None:
        """Enforce runtime-construction result consistency."""
        if self.success:
            if self.dependencies is None:
                raise ValueError(
                    "A successful Telegram runtime result must contain dependencies."
                )

            if self.issues:
                raise ValueError(
                    "A successful Telegram runtime result must not contain issues."
                )
            return

        if self.dependencies is not None:
            raise ValueError(
                "A failed Telegram runtime result must not contain dependencies."
            )

        if not self.issues:
            raise ValueError(
                "A failed Telegram runtime result must contain at least one issue."
            )


def build_telegram_runtime(
    runtime: RuntimeConfig,
    telegram: TelegramRuntimeConfig,
    *,
    transport_factory: TelegramTransportFactory,
    offset_fsync: bool = True,
) -> TelegramRuntimeResult:
    """Construct Telegram dependencies without starting polling or networking."""
    if not telegram.enabled:
        return _failure(
            code="telegram_runtime_disabled",
            message="The Telegram runtime is not enabled.",
            field="enabled",
        )

    token_path = runtime.secrets.telegram_token_file

    if token_path is None:
        return _failure(
            code="telegram_token_not_configured",
            message="The Telegram bot token file is not configured.",
            field="secrets.telegram_token_file",
        )

    token_result = _load_bot_token(token_path)

    if isinstance(token_result, TelegramRuntimeIssue):
        return TelegramRuntimeResult(
            success=False,
            dependencies=None,
            issues=(token_result,),
        )

    users = load_authorised_channel_users(telegram.authorised_users_file)

    if not users.success:
        return TelegramRuntimeResult(
            success=False,
            dependencies=None,
            issues=tuple(
                TelegramRuntimeIssue(
                    code=issue.code,
                    message=issue.message,
                    field=issue.field,
                    source_path=issue.source_path,
                )
                for issue in users.issues
            ),
        )

    enabled_users = tuple(user for user in users.users if user.enabled)

    if not enabled_users:
        return _failure(
            code="telegram_authorised_users_empty",
            message="At least one enabled Telegram user must be configured.",
            field="authorised_users_file",
            source_path=telegram.authorised_users_file,
        )

    offset_store = FileTelegramOffsetStore(
        telegram.offset_file,
        create_parent=False,
        fsync=offset_fsync,
    )

    try:
        transport = transport_factory(token_result)
    except Exception:
        return _failure(
            code="telegram_transport_construction_failed",
            message="The Telegram transport could not be constructed.",
            field="transport_factory",
        )

    if not isinstance(transport, TelegramTransport):
        return _failure(
            code="telegram_transport_invalid",
            message=("The Telegram transport factory returned an incompatible value."),
            field="transport_factory",
        )

    return TelegramRuntimeResult(
        success=True,
        dependencies=TelegramRuntimeDependencies(
            config=telegram,
            authorised_users=enabled_users,
            offset_store=offset_store,
            transport=transport,
        ),
        issues=(),
    )


def _load_bot_token(
    source_path: Path,
) -> str | TelegramRuntimeIssue:
    if not source_path.is_absolute():
        return _token_issue(
            source_path=None,
            code="telegram_token_path_invalid",
            message="The Telegram token-file path must be absolute.",
            field="secrets.telegram_token_file",
        )

    if source_path.is_symlink():
        return _token_issue(
            source_path=source_path,
            code="telegram_token_symlink_rejected",
            message="Symbolic links are not permitted for Telegram token files.",
        )

    try:
        metadata = source_path.stat()
    except FileNotFoundError:
        return _token_issue(
            source_path=source_path,
            code="telegram_token_not_found",
            message="The Telegram token file was not found.",
        )
    except OSError:
        return _token_issue(
            source_path=source_path,
            code="telegram_token_stat_failed",
            message="Telegram token-file metadata could not be read.",
        )

    if not source_path.is_file():
        return _token_issue(
            source_path=source_path,
            code="telegram_token_not_regular_file",
            message="The Telegram token path is not a regular file.",
        )

    if metadata.st_mode & 0o077:
        return _token_issue(
            source_path=source_path,
            code="telegram_token_insecure_permissions",
            message=(
                "The Telegram token file must not be accessible by the group "
                "or other users."
            ),
        )

    try:
        contents = source_path.read_text(encoding="utf-8")
    except UnicodeError:
        return _token_issue(
            source_path=source_path,
            code="telegram_token_invalid_utf8",
            message="The Telegram token file is not valid UTF-8.",
        )
    except OSError:
        return _token_issue(
            source_path=source_path,
            code="telegram_token_read_failed",
            message="The Telegram token file could not be read.",
        )

    token = contents.removesuffix("\n")

    if "\n" in token or "\r" in token:
        return _token_issue(
            source_path=source_path,
            code="telegram_token_multiline",
            message="The Telegram token file must contain exactly one token line.",
        )

    if not token:
        return _token_issue(
            source_path=source_path,
            code="telegram_token_empty",
            message="The Telegram token file is empty.",
        )

    if _TOKEN_PATTERN.fullmatch(token) is None:
        return _token_issue(
            source_path=source_path,
            code="telegram_token_malformed",
            message="The Telegram token file contains a malformed bot token.",
        )

    return token


def _token_issue(
    *,
    source_path: Path | None,
    code: str,
    message: str,
    field: str | None = None,
) -> TelegramRuntimeIssue:
    return TelegramRuntimeIssue(
        code=code,
        message=message,
        field=field,
        source_path=source_path,
    )


def _failure(
    *,
    code: str,
    message: str,
    field: str | None = None,
    source_path: Path | None = None,
) -> TelegramRuntimeResult:
    return TelegramRuntimeResult(
        success=False,
        dependencies=None,
        issues=(
            TelegramRuntimeIssue(
                code=code,
                message=message,
                field=field,
                source_path=source_path,
            ),
        ),
    )


def _validate_absolute_path(
    value: Path,
    *,
    field_name: str,
) -> None:
    if not isinstance(value, Path):
        raise TypeError(f"{field_name} must be a pathlib.Path value.")

    if not value.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path.")

    if "\x00" in str(value):
        raise ValueError(f"{field_name} must not contain a null byte.")


def _validate_integer(
    value: int,
    *,
    field_name: str,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer.")
