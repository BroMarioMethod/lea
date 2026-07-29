"""Supervisor-neutral foreground Telegram polling worker."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from lea.adapters.telegram.contracts import TelegramTransport, TelegramUpdate
from lea.adapters.telegram.formatting import (
    TelegramFormattedResponse,
    format_telegram_response,
)
from lea.adapters.telegram.offsets import TelegramOffsetStore
from lea.adapters.telegram.parser import (
    TelegramParsedCallback,
    TelegramParsedMessage,
    TelegramUpdateKind,
    TelegramUpdateParseResult,
    parse_telegram_update,
)
from lea.adapters.telegram.routing import (
    TelegramRequestIdSource,
    TelegramUtcClock,
    route_telegram_update,
)
from lea.channels.application import ChannelApplication
from lea.channels.authorisation import AuthorisedChannelUser

TelegramWorkerSleeper = Callable[[float], None]
"""Injected retry-delay boundary."""

_MAX_RETRY_DELAY_SECONDS = 60.0
_MAX_CONSECUTIVE_FETCH_FAILURES = 100

_LOGGER = logging.getLogger(__name__)


class TelegramWorkerStopSignal(Protocol):
    """Callable cooperative stop signal."""

    def __call__(self) -> object:
        """Return whether the worker should stop."""
        ...


@dataclass(frozen=True, slots=True)
class TelegramWorkerConfig:
    """Validated deterministic polling-worker settings."""

    bot_username: str
    poll_timeout_seconds: int
    fetch_limit: int
    retry_delay_seconds: float = 1.0
    max_consecutive_fetch_failures: int = 3

    def __post_init__(self) -> None:
        """Validate bounded worker settings."""
        if not self.bot_username.strip() or self.bot_username.startswith("@"):
            raise ValueError("bot_username must be non-empty and omit the leading '@'.")

        _positive_integer(
            self.poll_timeout_seconds,
            field_name="poll_timeout_seconds",
        )
        _positive_integer(self.fetch_limit, field_name="fetch_limit")
        _positive_integer(
            self.max_consecutive_fetch_failures,
            field_name="max_consecutive_fetch_failures",
        )

        if self.max_consecutive_fetch_failures > _MAX_CONSECUTIVE_FETCH_FAILURES:
            raise ValueError(
                "max_consecutive_fetch_failures exceeds the supported bound."
            )

        if (
            isinstance(self.retry_delay_seconds, bool)
            or not isinstance(self.retry_delay_seconds, (int, float))
            or self.retry_delay_seconds < 0
            or self.retry_delay_seconds > _MAX_RETRY_DELAY_SECONDS
        ):
            raise ValueError(
                "retry_delay_seconds must be between 0 and "
                f"{_MAX_RETRY_DELAY_SECONDS:g}."
            )


@dataclass(frozen=True, slots=True)
class TelegramWorkerDependencies:
    """Injected dependencies for one foreground Telegram worker."""

    transport: TelegramTransport
    offset_store: TelegramOffsetStore
    application: ChannelApplication
    authorised_users: tuple[AuthorisedChannelUser, ...]
    request_id_source: TelegramRequestIdSource
    clock: TelegramUtcClock
    stop_signal: TelegramWorkerStopSignal
    sleeper: TelegramWorkerSleeper
    warning_sink: Callable[[TelegramWorkerIssue], object] | None = None

    def __post_init__(self) -> None:
        """Reject empty authorisation configuration."""
        if not self.authorised_users:
            raise ValueError("Telegram worker requires at least one authorised user.")


@dataclass(frozen=True, slots=True)
class TelegramWorkerIssue:
    """One deterministic redacted worker failure."""

    code: str
    message: str
    operation: str
    update_id: int | None = None

    def __post_init__(self) -> None:
        """Validate safe worker issue fields."""
        for field_name, value in (
            ("code", self.code),
            ("message", self.message),
            ("operation", self.operation),
        ):
            if not value.strip():
                raise ValueError(
                    f"Telegram worker issue {field_name} must be non-empty."
                )

        if self.update_id is not None:
            _positive_integer(self.update_id, field_name="update_id")


@dataclass(frozen=True, slots=True)
class TelegramWorkerResult:
    """Immutable terminal result of one foreground worker run."""

    success: bool
    stopped: bool
    processed_updates: int
    skipped_updates: int
    issues: tuple[TelegramWorkerIssue, ...]

    def __post_init__(self) -> None:
        """Enforce worker-result consistency."""
        _non_negative_integer(
            self.processed_updates,
            field_name="processed_updates",
        )
        _non_negative_integer(
            self.skipped_updates,
            field_name="skipped_updates",
        )

        if self.success and self.issues:
            raise ValueError(
                "A successful Telegram worker result must not contain issues."
            )

        if not self.success and not self.issues:
            raise ValueError(
                "A failed Telegram worker result must contain at least one issue."
            )


@dataclass(frozen=True, slots=True)
class _PreparedUpdate:
    """One checkpointable update with optional response delivery."""

    destination: TelegramParsedMessage | TelegramParsedCallback | None = None
    formatted: TelegramFormattedResponse | None = None
    warning: TelegramWorkerIssue | None = None


def run_telegram_worker(
    config: TelegramWorkerConfig,
    dependencies: TelegramWorkerDependencies,
) -> TelegramWorkerResult:
    """Run a cooperative foreground polling loop until stopped or failed."""
    loaded = dependencies.offset_store.load()

    if not loaded.success:
        first = loaded.issues[0]
        return _failure(
            code=first.code,
            message=first.message,
            operation="load_offset",
        )

    state = loaded.state
    processed = 0
    skipped = 0
    consecutive_fetch_failures = 0

    while not _stop_requested(dependencies.stop_signal):
        try:
            fetched = dependencies.transport.fetch_updates(
                offset=state.next_update_id if state is not None else None,
                limit=config.fetch_limit,
                timeout_seconds=config.poll_timeout_seconds,
            )
        except KeyboardInterrupt:
            return _stopped(processed=processed, skipped=skipped)
        except Exception:
            fetched = None

        if fetched is None or not fetched.success:
            consecutive_fetch_failures += 1

            if consecutive_fetch_failures >= config.max_consecutive_fetch_failures:
                return _failure(
                    code="telegram_fetch_retry_exhausted",
                    message=(
                        "Telegram update fetching remained unavailable after "
                        "the configured retry limit."
                    ),
                    operation="fetch_updates",
                    processed=processed,
                    skipped=skipped,
                )

            try:
                dependencies.sleeper(float(config.retry_delay_seconds))
            except KeyboardInterrupt:
                return _stopped(processed=processed, skipped=skipped)
            except Exception:
                return _failure(
                    code="telegram_retry_delay_failed",
                    message="The Telegram retry delay could not complete.",
                    operation="retry_delay",
                    processed=processed,
                    skipped=skipped,
                )
            continue

        consecutive_fetch_failures = 0

        for update in fetched.updates:
            if _stop_requested(dependencies.stop_signal):
                return _stopped(processed=processed, skipped=skipped)

            if state is not None and state.is_stale(update):
                skipped += 1
                continue

            prepared = _prepare_update(config, dependencies, update)

            if isinstance(prepared, TelegramWorkerIssue):
                return TelegramWorkerResult(
                    success=False,
                    stopped=False,
                    processed_updates=processed,
                    skipped_updates=skipped,
                    issues=(prepared,),
                )

            advanced = dependencies.offset_store.advance(update.update_id)

            if not advanced.success or advanced.state is None:
                first = advanced.issues[0]
                return _failure(
                    code=first.code,
                    message=first.message,
                    operation="advance_offset",
                    update_id=update.update_id,
                    processed=processed,
                    skipped=skipped,
                )

            state = advanced.state
            processed += 1

            if prepared.warning is not None:
                _report_warning(dependencies, prepared.warning)

            _deliver_response(
                dependencies,
                update_id=update.update_id,
                prepared=prepared,
            )

    return _stopped(processed=processed, skipped=skipped)


def _prepare_update(
    config: TelegramWorkerConfig,
    dependencies: TelegramWorkerDependencies,
    update: TelegramUpdate,
) -> _PreparedUpdate | TelegramWorkerIssue:
    """Apply one update and prepare any best-effort Telegram response."""
    parsed = parse_telegram_update(update)

    if not parsed.success:
        return _PreparedUpdate()

    routed = route_telegram_update(
        parsed,
        users=dependencies.authorised_users,
        request_id_source=dependencies.request_id_source,
        clock=dependencies.clock,
        bot_username=config.bot_username,
    )

    if not routed.success or routed.request is None:
        return _PreparedUpdate()

    applied = dependencies.application.handle(routed.request)

    if not applied.success or applied.response is None:
        return TelegramWorkerIssue(
            code="telegram_application_failed",
            message="The channel application could not handle the Telegram update.",
            operation="application",
            update_id=update.update_id,
        )

    formatted = format_telegram_response(applied.response)

    if not formatted.success or formatted.formatted is None:
        return _PreparedUpdate(
            warning=TelegramWorkerIssue(
                code="telegram_response_formatting_failed",
                message="The channel response could not be formatted for Telegram.",
                operation="format_response",
                update_id=update.update_id,
            )
        )

    return _PreparedUpdate(
        destination=_destination(parsed),
        formatted=formatted.formatted,
    )


def _deliver_response(
    dependencies: TelegramWorkerDependencies,
    *,
    update_id: int,
    prepared: _PreparedUpdate,
) -> None:
    """Deliver one checkpointed response without terminating the worker."""
    destination = prepared.destination
    formatted = prepared.formatted

    if destination is None or formatted is None:
        return

    if isinstance(destination, TelegramParsedMessage):
        try:
            sent = dependencies.transport.send_message(
                chat_id=destination.chat_id,
                text=formatted.text,
                keyboard=formatted.keyboard,
            )
        except Exception:
            sent = None

        if sent is None or not sent.success:
            _report_warning(
                dependencies,
                TelegramWorkerIssue(
                    code="telegram_send_failed",
                    message="The Telegram response could not be sent.",
                    operation="send_message",
                    update_id=update_id,
                ),
            )

        return

    try:
        answered = dependencies.transport.answer_callback_query(
            callback_query_id=destination.callback_query_id,
        )
    except Exception:
        answered = None

    if answered is None or not answered.success:
        _report_warning(
            dependencies,
            TelegramWorkerIssue(
                code="telegram_callback_answer_failed",
                message="The Telegram callback query could not be answered.",
                operation="answer_callback_query",
                update_id=update_id,
            ),
        )

    try:
        edited = dependencies.transport.edit_message(
            chat_id=destination.chat_id,
            message_id=destination.message_id,
            text=formatted.text,
            keyboard=formatted.keyboard,
        )
    except Exception:
        edited = None

    if edited is None or not edited.success:
        _report_warning(
            dependencies,
            TelegramWorkerIssue(
                code="telegram_edit_failed",
                message="The Telegram callback message could not be updated.",
                operation="edit_message",
                update_id=update_id,
            ),
        )


def _report_warning(
    dependencies: TelegramWorkerDependencies,
    issue: TelegramWorkerIssue,
) -> None:
    """Report one redacted non-fatal worker warning."""
    if dependencies.warning_sink is not None:
        try:
            dependencies.warning_sink(issue)
            return
        except Exception:
            pass

    _LOGGER.warning(
        "Telegram worker warning: %s: %s operation=%s update_id=%s",
        issue.code,
        issue.message,
        issue.operation,
        issue.update_id,
    )


def _destination(
    parsed: TelegramUpdateParseResult,
) -> TelegramParsedMessage | TelegramParsedCallback:
    if parsed.kind is TelegramUpdateKind.PRIVATE_COMMAND:
        assert parsed.message is not None
        return parsed.message

    assert parsed.callback is not None
    return parsed.callback


def _stop_requested(signal: TelegramWorkerStopSignal) -> bool:
    try:
        value = signal()
    except Exception:
        return True

    return value is True


def _stopped(*, processed: int, skipped: int) -> TelegramWorkerResult:
    return TelegramWorkerResult(
        success=True,
        stopped=True,
        processed_updates=processed,
        skipped_updates=skipped,
        issues=(),
    )


def _failure(
    *,
    code: str,
    message: str,
    operation: str,
    update_id: int | None = None,
    processed: int = 0,
    skipped: int = 0,
) -> TelegramWorkerResult:
    return TelegramWorkerResult(
        success=False,
        stopped=False,
        processed_updates=processed,
        skipped_updates=skipped,
        issues=(
            TelegramWorkerIssue(
                code=code,
                message=message,
                operation=operation,
                update_id=update_id,
            ),
        ),
    )


def _positive_integer(value: int, *, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer.")


def _non_negative_integer(value: int, *, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer.")
