"""Deterministic routing from parsed Telegram updates to channel requests."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from lea.adapters.telegram.parser import (
    TelegramParsedCallback,
    TelegramParsedMessage,
    TelegramUpdateKind,
    TelegramUpdateParseResult,
)
from lea.channels import (
    AuthorisedChannelUser,
    ChannelCapability,
    ChannelName,
    ChannelRequest,
    ChannelRequestType,
    authorise_channel_identity,
)


class TelegramRequestIdSource(Protocol):
    """Callable source of canonical request UUID strings."""

    def __call__(self) -> object:
        """Return one request identifier."""
        ...


class TelegramUtcClock(Protocol):
    """Callable source of timezone-aware UTC timestamps."""

    def __call__(self) -> object:
        """Return one UTC timestamp."""
        ...


@dataclass(frozen=True, slots=True)
class TelegramCommandDefinition:
    """One explicit Telegram command route definition."""

    telegram_command: str
    channel_command: str
    required_capability: ChannelCapability
    minimum_arguments: int = 0
    maximum_arguments: int | None = 0

    def __post_init__(self) -> None:
        """Validate one deterministic command definition."""
        if (
            not self.telegram_command.startswith("/")
            or len(self.telegram_command) == 1
            or not self.telegram_command[1:].replace("_", "").isalnum()
            or self.telegram_command.lower() != self.telegram_command
        ):
            raise ValueError("telegram_command must be a lower-case slash command.")

        if not self.channel_command.strip():
            raise ValueError("channel_command must be non-empty.")

        if self.minimum_arguments < 0:
            raise ValueError("minimum_arguments must not be negative.")

        if (
            self.maximum_arguments is not None
            and self.maximum_arguments < self.minimum_arguments
        ):
            raise ValueError(
                "maximum_arguments must not be less than minimum_arguments."
            )


@dataclass(frozen=True, slots=True)
class TelegramCommandRoute:
    """Resolved route metadata for one Telegram update."""

    telegram_command: str
    channel_command: str
    required_capability: ChannelCapability
    request_type: ChannelRequestType

    def __post_init__(self) -> None:
        """Validate stable route fields."""
        if not self.telegram_command.strip():
            raise ValueError("telegram_command must be non-empty.")

        if not self.channel_command.strip():
            raise ValueError("channel_command must be non-empty.")


@dataclass(frozen=True, slots=True)
class TelegramCommandRoutingIssue:
    """One deterministic Telegram routing failure."""

    code: str
    message: str
    field: str | None = None

    def __post_init__(self) -> None:
        """Validate safe routing issue fields."""
        if not self.code.strip():
            raise ValueError("Telegram routing issue code must be non-empty.")

        if not self.message.strip():
            raise ValueError("Telegram routing issue message must be non-empty.")

        if self.field is not None and not self.field.strip():
            raise ValueError(
                "Telegram routing issue field must be non-empty when provided."
            )


@dataclass(frozen=True, slots=True)
class TelegramCommandRoutingResult:
    """Immutable result of routing one parsed Telegram update."""

    success: bool
    request: ChannelRequest | None
    route: TelegramCommandRoute | None
    issues: tuple[TelegramCommandRoutingIssue, ...]

    def __post_init__(self) -> None:
        """Enforce routing-result consistency."""
        if self.success:
            if self.request is None or self.route is None:
                raise ValueError(
                    "A successful Telegram routing result must contain "
                    "a request and route."
                )

            if self.issues:
                raise ValueError(
                    "A successful Telegram routing result must not contain issues."
                )
            return

        if self.request is not None or self.route is not None:
            raise ValueError(
                "A failed Telegram routing result must not contain a request or route."
            )

        if not self.issues:
            raise ValueError(
                "A failed Telegram routing result must contain at least one issue."
            )


_DEFAULT_COMMAND_DEFINITIONS = (
    TelegramCommandDefinition(
        telegram_command="/start",
        channel_command="system.start",
        required_capability=ChannelCapability.RUNTIME_STATUS_READ,
    ),
    TelegramCommandDefinition(
        telegram_command="/help",
        channel_command="system.help",
        required_capability=ChannelCapability.RUNTIME_STATUS_READ,
    ),
    TelegramCommandDefinition(
        telegram_command="/status",
        channel_command="runtime.status",
        required_capability=ChannelCapability.RUNTIME_STATUS_READ,
    ),
    TelegramCommandDefinition(
        telegram_command="/tasks",
        channel_command="tasks.list",
        required_capability=ChannelCapability.TASKS_READ,
    ),
    TelegramCommandDefinition(
        telegram_command="/task_add",
        channel_command="tasks.create",
        required_capability=ChannelCapability.TASKS_WRITE,
        minimum_arguments=1,
        maximum_arguments=None,
    ),
    TelegramCommandDefinition(
        telegram_command="/task_show",
        channel_command="tasks.show",
        required_capability=ChannelCapability.TASKS_READ,
        minimum_arguments=1,
        maximum_arguments=1,
    ),
    TelegramCommandDefinition(
        telegram_command="/task_modify",
        channel_command="tasks.modify",
        required_capability=ChannelCapability.TASKS_WRITE,
        minimum_arguments=2,
        maximum_arguments=None,
    ),
    TelegramCommandDefinition(
        telegram_command="/task_complete",
        channel_command="tasks.complete",
        required_capability=ChannelCapability.TASKS_WRITE,
        minimum_arguments=1,
        maximum_arguments=1,
    ),
    TelegramCommandDefinition(
        telegram_command="/task_delete",
        channel_command="tasks.delete",
        required_capability=ChannelCapability.TASKS_DELETE,
        minimum_arguments=1,
        maximum_arguments=1,
    ),
    TelegramCommandDefinition(
        telegram_command="/proposals",
        channel_command="proposals.list",
        required_capability=ChannelCapability.PROPOSALS_READ,
    ),
    TelegramCommandDefinition(
        telegram_command="/proposal_show",
        channel_command="proposals.show",
        required_capability=ChannelCapability.PROPOSALS_READ,
        minimum_arguments=1,
        maximum_arguments=1,
    ),
    TelegramCommandDefinition(
        telegram_command="/proposal_approve",
        channel_command="proposals.approve",
        required_capability=ChannelCapability.PROPOSALS_CONFIRM,
        minimum_arguments=1,
        maximum_arguments=1,
    ),
    TelegramCommandDefinition(
        telegram_command="/proposal_reject",
        channel_command="proposals.reject",
        required_capability=ChannelCapability.PROPOSALS_CONFIRM,
        minimum_arguments=1,
        maximum_arguments=None,
    ),
    TelegramCommandDefinition(
        telegram_command="/proposal_cancel",
        channel_command="proposals.cancel",
        required_capability=ChannelCapability.PROPOSALS_CONFIRM,
        minimum_arguments=1,
        maximum_arguments=None,
    ),
    TelegramCommandDefinition(
        telegram_command="/proposal_revise",
        channel_command="proposals.revise",
        required_capability=ChannelCapability.PROPOSALS_CONFIRM,
        minimum_arguments=2,
        maximum_arguments=None,
    ),
    TelegramCommandDefinition(
        telegram_command="/proposal_execute",
        channel_command="proposals.execute",
        required_capability=ChannelCapability.PROPOSALS_EXECUTE_LOW_RISK,
        minimum_arguments=1,
        maximum_arguments=1,
    ),
    TelegramCommandDefinition(
        telegram_command="/knowledge_show",
        channel_command="knowledge.show",
        required_capability=ChannelCapability.KNOWLEDGE_READ_LOW,
        minimum_arguments=1,
        maximum_arguments=1,
    ),
    TelegramCommandDefinition(
        telegram_command="/knowledge_find",
        channel_command="knowledge.find",
        required_capability=ChannelCapability.KNOWLEDGE_READ_LOW,
        minimum_arguments=1,
        maximum_arguments=None,
    ),
)

_CALLBACK_DEFINITIONS = {
    "proposal.approve": (
        "proposals.approve",
        ChannelCapability.PROPOSALS_CONFIRM,
        ChannelRequestType.CONFIRMATION,
    ),
    "proposal.reject": (
        "proposals.reject",
        ChannelCapability.PROPOSALS_CONFIRM,
        ChannelRequestType.CONFIRMATION,
    ),
    "proposal.cancel": (
        "proposals.cancel",
        ChannelCapability.PROPOSALS_CONFIRM,
        ChannelRequestType.CONFIRMATION,
    ),
    "proposal.revise": (
        "proposals.revise",
        ChannelCapability.PROPOSALS_CONFIRM,
        ChannelRequestType.REVISION_REQUEST,
    ),
}


def default_telegram_command_definitions() -> tuple[TelegramCommandDefinition, ...]:
    """Return the immutable built-in Telegram command definitions."""
    return _DEFAULT_COMMAND_DEFINITIONS


def route_telegram_update(
    parsed: TelegramUpdateParseResult,
    *,
    users: tuple[AuthorisedChannelUser, ...],
    request_id_source: TelegramRequestIdSource,
    clock: TelegramUtcClock,
    bot_username: str | None = None,
    definitions: tuple[TelegramCommandDefinition, ...] | None = None,
) -> TelegramCommandRoutingResult:
    """Authorise and route one successfully parsed Telegram update."""
    if not parsed.success:
        return _failure(
            code="telegram_update_not_parsed",
            message="Only successfully parsed Telegram updates can be routed.",
        )

    if bot_username is not None:
        _validate_bot_username(bot_username)

    if parsed.kind is TelegramUpdateKind.PRIVATE_COMMAND:
        assert parsed.message is not None
        route_data = _route_message(
            parsed.message,
            bot_username=bot_username,
            definitions=definitions or _DEFAULT_COMMAND_DEFINITIONS,
        )
        user_id = parsed.message.user_id
        chat_id = parsed.message.chat_id
        update_id = parsed.message.update_id
    elif parsed.kind is TelegramUpdateKind.CALLBACK_QUERY:
        assert parsed.callback is not None
        route_data = _route_callback(parsed.callback)
        user_id = parsed.callback.user_id
        chat_id = parsed.callback.chat_id
        update_id = parsed.callback.update_id
    else:
        return _failure(
            code="telegram_update_kind_unsupported",
            message="The parsed Telegram update kind is unsupported.",
        )

    if isinstance(route_data, TelegramCommandRoutingResult):
        return route_data

    route, parameters = route_data
    authorisation = authorise_channel_identity(
        channel=ChannelName.TELEGRAM,
        user_id=user_id,
        conversation_id=chat_id,
        users=users,
    )

    if not authorisation.authorised or authorisation.identity is None:
        issue = authorisation.issues[0]
        return _failure(
            code=issue.code,
            message=issue.message,
        )

    if route.required_capability.value not in authorisation.identity.capabilities:
        return _failure(
            code="telegram_capability_required",
            message=(
                "The authorised channel identity does not have the capability "
                "required for this command."
            ),
            field="required_capability",
        )

    try:
        request_id = _next_request_id(request_id_source)
        received_at = _next_utc_timestamp(clock)
        request = ChannelRequest(
            request_id=request_id,
            source_update_id=f"telegram:{update_id}",
            identity=authorisation.identity,
            request_type=route.request_type,
            command=route.channel_command,
            parameters=parameters,
            received_at=received_at,
        )
    except (TypeError, ValueError):
        return _failure(
            code="telegram_routing_dependency_invalid",
            message=("A Telegram routing dependency returned an invalid value."),
        )

    return TelegramCommandRoutingResult(
        success=True,
        request=request,
        route=route,
        issues=(),
    )


def _route_message(
    message: TelegramParsedMessage,
    *,
    bot_username: str | None,
    definitions: tuple[TelegramCommandDefinition, ...],
) -> tuple[TelegramCommandRoute, dict[str, object]] | TelegramCommandRoutingResult:
    try:
        tokens = tuple(shlex.split(message.text))
    except ValueError:
        return _failure(
            code="telegram_command_syntax_invalid",
            message="The Telegram command contains invalid quoted text.",
            field="text",
        )

    if not tokens:
        return _failure(
            code="telegram_command_missing",
            message="The Telegram command is missing.",
            field="text",
        )

    command_token = tokens[0]
    command, suffix_issue = _normalise_command_token(
        command_token,
        bot_username=bot_username,
    )
    if suffix_issue is not None:
        return _issue_failure(suffix_issue)

    matches = tuple(
        definition
        for definition in definitions
        if definition.telegram_command == command
    )

    if len(matches) != 1:
        return _failure(
            code=(
                "telegram_command_unknown"
                if not matches
                else "telegram_command_ambiguous"
            ),
            message=(
                "The Telegram command is not supported."
                if not matches
                else "The Telegram command matches more than one route."
            ),
            field="command",
        )

    definition = matches[0]
    arguments = tokens[1:]
    argument_count = len(arguments)

    if argument_count < definition.minimum_arguments:
        return _failure(
            code="telegram_command_arguments_missing",
            message="The Telegram command requires more arguments.",
            field="arguments",
        )

    if (
        definition.maximum_arguments is not None
        and argument_count > definition.maximum_arguments
    ):
        return _failure(
            code="telegram_command_arguments_excessive",
            message="The Telegram command contains too many arguments.",
            field="arguments",
        )

    return (
        TelegramCommandRoute(
            telegram_command=definition.telegram_command,
            channel_command=definition.channel_command,
            required_capability=definition.required_capability,
            request_type=ChannelRequestType.COMMAND,
        ),
        {
            "arguments": list(arguments),
            "telegram_message_id": message.message_id,
        },
    )


def _route_callback(
    callback: TelegramParsedCallback,
) -> tuple[TelegramCommandRoute, dict[str, object]] | TelegramCommandRoutingResult:
    action, separator, proposal_id = callback.data.partition(":")

    if not separator or not proposal_id:
        return _failure(
            code="telegram_callback_route_invalid",
            message="Telegram callback data does not contain a supported route.",
            field="data",
        )

    definition = _CALLBACK_DEFINITIONS.get(action)

    if definition is None:
        return _failure(
            code="telegram_callback_route_unknown",
            message="The Telegram callback action is not supported.",
            field="data",
        )

    if not _is_canonical_uuid(proposal_id):
        return _failure(
            code="telegram_callback_proposal_id_invalid",
            message="Telegram callback proposal identifier is not canonical.",
            field="data",
        )

    channel_command, capability, request_type = definition
    return (
        TelegramCommandRoute(
            telegram_command=action,
            channel_command=channel_command,
            required_capability=capability,
            request_type=request_type,
        ),
        {
            "proposal_id": proposal_id,
            "callback_query_id": callback.callback_query_id,
            "telegram_message_id": callback.message_id,
        },
    )


def _normalise_command_token(
    token: str,
    *,
    bot_username: str | None,
) -> tuple[str, TelegramCommandRoutingIssue | None]:
    command, separator, suffix = token.partition("@")

    if not separator:
        return command.lower(), None

    if (
        not suffix
        or bot_username is None
        or suffix.casefold() != bot_username.casefold()
    ):
        return "", TelegramCommandRoutingIssue(
            code="telegram_command_bot_mismatch",
            message="The Telegram command targets a different bot.",
            field="command",
        )

    return command.lower(), None


def _validate_bot_username(value: str) -> None:
    if not value or value.startswith("@") or not value.replace("_", "").isalnum():
        raise ValueError(
            "bot_username must omit '@' and contain letters, digits or underscores."
        )


def _next_request_id(source: TelegramRequestIdSource) -> str:
    value = source()

    if not isinstance(value, str):
        raise ValueError("The Telegram request ID source must return a string.")

    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ValueError(
            "The Telegram request ID source must return a valid UUID."
        ) from error

    if str(parsed) != value:
        raise ValueError("The Telegram request ID source must return a canonical UUID.")

    return value


def _next_utc_timestamp(clock: TelegramUtcClock) -> datetime:
    value = clock()

    if not isinstance(value, datetime):
        raise ValueError("The Telegram clock must return a datetime.")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("The Telegram clock must return a timezone-aware datetime.")

    if value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("The Telegram clock must return a UTC datetime.")

    return value.astimezone(UTC)


def _is_canonical_uuid(value: str) -> bool:
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _issue_failure(
    issue: TelegramCommandRoutingIssue,
) -> TelegramCommandRoutingResult:
    return TelegramCommandRoutingResult(
        success=False,
        request=None,
        route=None,
        issues=(issue,),
    )


def _failure(
    *,
    code: str,
    message: str,
    field: str | None = None,
) -> TelegramCommandRoutingResult:
    return _issue_failure(
        TelegramCommandRoutingIssue(
            code=code,
            message=message,
            field=field,
        )
    )
