"""Channel-neutral application dispatch for LEA interfaces."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from lea.channels.contracts import (
    ChannelIssue,
    ChannelRequest,
    ChannelResponse,
    ChannelResponseOutcome,
)

ChannelCommandHandler = Callable[[ChannelRequest], ChannelResponse]
"""One channel-neutral command handler."""


class ChannelUtcClock(Protocol):
    """Callable source of timezone-aware UTC timestamps."""

    def __call__(self) -> object:
        """Return one UTC timestamp."""
        ...


@dataclass(frozen=True, slots=True)
class ChannelCommandDefinition:
    """One exact channel command-to-handler binding."""

    command: str
    handler: ChannelCommandHandler

    def __post_init__(self) -> None:
        """Validate one command definition."""
        if not self.command.strip():
            raise ValueError("Channel command definition must be non-empty.")

        if self.command != self.command.strip():
            raise ValueError(
                "Channel command definition must not contain surrounding whitespace."
            )


@dataclass(frozen=True, slots=True)
class ChannelApplicationIssue:
    """One deterministic channel application failure."""

    code: str
    message: str
    field: str | None = None

    def __post_init__(self) -> None:
        """Validate safe issue fields."""
        if not self.code.strip():
            raise ValueError("Channel application issue code must be non-empty.")

        if not self.message.strip():
            raise ValueError("Channel application issue message must be non-empty.")

        if self.field is not None and not self.field.strip():
            raise ValueError(
                "Channel application issue field must be non-empty when provided."
            )


@dataclass(frozen=True, slots=True)
class ChannelApplicationResult:
    """Immutable result of handling one channel request."""

    success: bool
    response: ChannelResponse | None
    issues: tuple[ChannelApplicationIssue, ...]

    def __post_init__(self) -> None:
        """Enforce application-result consistency."""
        if self.success:
            if self.response is None:
                raise ValueError(
                    "A successful channel application result must contain a response."
                )

            if self.issues:
                raise ValueError(
                    "A successful channel application result must not contain issues."
                )
            return

        if self.response is not None:
            raise ValueError(
                "A failed channel application result must not contain a response."
            )

        if not self.issues:
            raise ValueError(
                "A failed channel application result must contain at least one issue."
            )


@runtime_checkable
class ChannelApplication(Protocol):
    """Application boundary shared by Telegram, Web/PWA and future channels."""

    def handle(self, request: ChannelRequest) -> ChannelApplicationResult:
        """Handle one validated channel request."""
        ...


class DispatchingChannelApplication(ChannelApplication):
    """Exact deterministic dispatcher for channel-neutral commands."""

    def __init__(
        self,
        definitions: tuple[ChannelCommandDefinition, ...],
        *,
        clock: ChannelUtcClock,
    ) -> None:
        """Construct an immutable command registry."""
        if not definitions:
            raise ValueError(
                "Channel application requires at least one command definition."
            )

        commands = tuple(definition.command for definition in definitions)

        if len(set(commands)) != len(commands):
            raise ValueError("Channel application command definitions must be unique.")

        self._handlers: Mapping[str, ChannelCommandHandler] = {
            definition.command: definition.handler for definition in definitions
        }
        self._clock = clock

    @property
    def commands(self) -> tuple[str, ...]:
        """Return supported commands in deterministic sorted order."""
        return tuple(sorted(self._handlers))

    def handle(self, request: ChannelRequest) -> ChannelApplicationResult:
        """Dispatch one exact command without transport-specific behaviour."""
        handler = self._handlers.get(request.command)

        if handler is None:
            return ChannelApplicationResult(
                success=True,
                response=self._unsupported_response(request),
                issues=(),
            )

        try:
            response = handler(request)
        except Exception:
            return ChannelApplicationResult(
                success=True,
                response=self._internal_failure_response(request),
                issues=(),
            )

        if response.request_id != request.request_id:
            return _failure(
                code="channel_response_request_mismatch",
                message=(
                    "The channel command handler returned a response for a "
                    "different request."
                ),
                field="request_id",
            )

        if response.correlation_id != request.correlation_id:
            return _failure(
                code="channel_response_correlation_mismatch",
                message=(
                    "The channel command handler returned a response with a "
                    "different correlation identifier."
                ),
                field="correlation_id",
            )

        return ChannelApplicationResult(
            success=True,
            response=response,
            issues=(),
        )

    def _unsupported_response(
        self,
        request: ChannelRequest,
    ) -> ChannelResponse:
        return ChannelResponse(
            request_id=request.request_id,
            outcome=ChannelResponseOutcome.NOT_FOUND,
            message="The requested LEA command is not supported.",
            responded_at=self._timestamp(),
            correlation_id=request.correlation_id,
            issue=ChannelIssue(
                code="channel_command_not_supported",
                message="The requested LEA command is not supported.",
                field="command",
            ),
            data={"command": request.command},
        )

    def _internal_failure_response(
        self,
        request: ChannelRequest,
    ) -> ChannelResponse:
        return ChannelResponse(
            request_id=request.request_id,
            outcome=ChannelResponseOutcome.APPLICATION_FAILED,
            message="LEA could not complete the requested command.",
            responded_at=self._timestamp(),
            correlation_id=request.correlation_id,
            issue=ChannelIssue(
                code="channel_command_failed",
                message="LEA could not complete the requested command.",
            ),
        )

    def _timestamp(self) -> datetime:
        value = self._clock()

        if not isinstance(value, datetime):
            raise ValueError("The channel application clock must return a datetime.")

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "The channel application clock must return a timezone-aware datetime."
            )

        if value.utcoffset() != UTC.utcoffset(value):
            raise ValueError(
                "The channel application clock must return a UTC datetime."
            )

        return value.astimezone(UTC)


def _failure(
    *,
    code: str,
    message: str,
    field: str | None = None,
) -> ChannelApplicationResult:
    return ChannelApplicationResult(
        success=False,
        response=None,
        issues=(
            ChannelApplicationIssue(
                code=code,
                message=message,
                field=field,
            ),
        ),
    )
