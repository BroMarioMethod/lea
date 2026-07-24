"""Map stable Local CLI service results to channel responses."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from lea.channels.contracts import (
    ChannelIssue,
    ChannelRequest,
    ChannelResponse,
    ChannelResponseOutcome,
)
from lea.cli.contracts import CliResult, LocalCliExitCode


class ChannelResponseClock(Protocol):
    """Callable source of timezone-aware UTC response timestamps."""

    def __call__(self) -> object:
        """Return one UTC timestamp."""
        ...


_OUTCOMES = {
    LocalCliExitCode.SUCCESS: ChannelResponseOutcome.SUCCEEDED,
    LocalCliExitCode.APPLICATION_ERROR: ChannelResponseOutcome.APPLICATION_FAILED,
    LocalCliExitCode.USAGE_ERROR: ChannelResponseOutcome.VALIDATION_FAILED,
    LocalCliExitCode.CONFIGURATION_ERROR: ChannelResponseOutcome.APPLICATION_FAILED,
    LocalCliExitCode.NOT_FOUND: ChannelResponseOutcome.NOT_FOUND,
    LocalCliExitCode.CONFIRMATION_REQUIRED: ChannelResponseOutcome.REJECTED,
    LocalCliExitCode.PERMISSION_DENIED: ChannelResponseOutcome.NOT_AUTHORISED,
    LocalCliExitCode.CONFLICT: ChannelResponseOutcome.CONFLICT,
    LocalCliExitCode.PROVIDER_UNAVAILABLE: (
        ChannelResponseOutcome.TEMPORARILY_UNAVAILABLE
    ),
    LocalCliExitCode.VALIDATION_ERROR: ChannelResponseOutcome.VALIDATION_FAILED,
    LocalCliExitCode.INTERNAL_ERROR: ChannelResponseOutcome.APPLICATION_FAILED,
}


def channel_response_from_cli_result(
    request: ChannelRequest,
    result: CliResult,
    *,
    clock: ChannelResponseClock,
    success_message: str,
) -> ChannelResponse:
    """Map one reusable CLI service result to a channel-neutral response."""
    responded_at = _timestamp(clock)
    outcome = _OUTCOMES[result.exit_code]
    data = _response_data(result.data)

    if result.success:
        return ChannelResponse(
            request_id=request.request_id,
            outcome=outcome,
            message=success_message,
            responded_at=responded_at,
            correlation_id=request.correlation_id,
            data=data,
        )

    first = result.issues[0]
    return ChannelResponse(
        request_id=request.request_id,
        outcome=outcome,
        message=first.message,
        responded_at=responded_at,
        correlation_id=request.correlation_id,
        issue=ChannelIssue(
            code=first.code,
            message=first.message,
            field=first.field,
        ),
        data=data,
    )


def _response_data(value: object) -> dict[str, object] | None:
    if value is None:
        return None

    if isinstance(value, dict):
        return dict(value)

    return {"result": value}


def _timestamp(clock: ChannelResponseClock) -> datetime:
    value = clock()

    if not isinstance(value, datetime):
        raise ValueError("The channel response clock must return a datetime.")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            "The channel response clock must return a timezone-aware datetime."
        )

    if value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("The channel response clock must return a UTC datetime.")

    return value.astimezone(UTC)
