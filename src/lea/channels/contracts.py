"""Immutable transport-neutral contracts for LEA interaction channels."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from lea.actions.errors import ActionContractError
from lea.actions.values import FrozenJsonValue, freeze_parameters

CHANNEL_SCHEMA_VERSION = 1

_COMMAND_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
_CAPABILITY_PATTERN = re.compile(r"^[A-Z][A-Za-z0-9]*(?:\.[A-Z][A-Za-z0-9]*)+$")
_ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_MAX_MESSAGE_LENGTH = 4096
_MAX_LABEL_LENGTH = 80


class ChannelName(StrEnum):
    """Supported interaction-channel identifiers."""

    TELEGRAM = "telegram"
    WEB = "web"
    CLI = "cli"


class ChannelRequestType(StrEnum):
    """Supported transport-neutral request categories."""

    COMMAND = "command"
    CONFIRMATION = "confirmation"
    REVISION_REQUEST = "revision_request"


class ChannelResponseOutcome(StrEnum):
    """Stable result categories returned to interaction channels."""

    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    NOT_AUTHORISED = "not_authorised"
    VALIDATION_FAILED = "validation_failed"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    APPLICATION_FAILED = "application_failed"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"


class ChannelControlType(StrEnum):
    """Supported channel-neutral interaction-control types."""

    ACTION = "action"


@dataclass(frozen=True, slots=True)
class ChannelIssue:
    """One safe user-facing channel failure."""

    code: str
    message: str
    field: str | None = None

    def __post_init__(self) -> None:
        """Validate stable issue fields."""
        _require_text(self.code, field_name="code")
        _require_text(self.message, field_name="message")

        if self.field is not None:
            _require_text(self.field, field_name="field")


@dataclass(frozen=True, slots=True)
class ChannelIdentity:
    """Authenticated channel identity with explicit capabilities."""

    channel: ChannelName
    user_id: str
    conversation_id: str
    role: str
    capabilities: tuple[str, ...]
    calendar_ids: tuple[str, ...] = ()
    display_name: str | None = None

    def __post_init__(self) -> None:
        """Validate and canonicalise one authenticated identity."""
        _require_text(self.user_id, field_name="user_id")
        _require_text(self.conversation_id, field_name="conversation_id")

        if self.channel is ChannelName.TELEGRAM:
            _validate_positive_decimal_identifier(
                self.user_id,
                field_name="user_id",
            )
            _validate_positive_decimal_identifier(
                self.conversation_id,
                field_name="conversation_id",
            )

        if _ROLE_PATTERN.fullmatch(self.role) is None:
            raise ValueError(
                "role must use lower-case letters, digits and underscores."
            )

        if self.display_name is not None:
            _require_text(self.display_name, field_name="display_name")

        canonical_capabilities = tuple(sorted(set(self.capabilities)))
        canonical_calendar_ids = tuple(sorted(set(self.calendar_ids)))

        for capability in canonical_capabilities:
            if _CAPABILITY_PATTERN.fullmatch(capability) is None:
                raise ValueError(
                    "capabilities must use namespaced identifiers such as 'Tasks.Read'."
                )

        object.__setattr__(self, "capabilities", canonical_capabilities)
        for calendar_id in canonical_calendar_ids:
            _require_text(calendar_id, field_name="calendar_ids")
            if calendar_id != calendar_id.strip():
                raise ValueError(
                    "calendar_ids must not contain surrounding whitespace."
                )
            if any(ord(character) < 32 for character in calendar_id):
                raise ValueError("calendar_ids must not contain control characters.")
        object.__setattr__(self, "calendar_ids", canonical_calendar_ids)


@dataclass(frozen=True, slots=True)
class ChannelRequest:
    """One validated request entering LEA from any interaction channel."""

    request_id: str
    source_update_id: str
    identity: ChannelIdentity
    request_type: ChannelRequestType
    command: str
    parameters: Mapping[str, object]
    received_at: datetime
    correlation_id: str | None = None
    schema_version: int = CHANNEL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Validate identifiers, timestamps and deeply frozen parameters."""
        _validate_schema_version(self.schema_version)
        _validate_uuid(self.request_id, field_name="request_id")
        _require_text(self.source_update_id, field_name="source_update_id")

        if _COMMAND_PATTERN.fullmatch(self.command) is None:
            raise ValueError("command must use a lower-case deterministic identifier.")

        if self.correlation_id is not None:
            _validate_uuid(self.correlation_id, field_name="correlation_id")

        _validate_utc_timestamp(self.received_at, field_name="received_at")
        object.__setattr__(
            self,
            "parameters",
            _freeze_mapping(self.parameters, field_name="parameters"),
        )


@dataclass(frozen=True, slots=True)
class ChannelControl:
    """One bounded channel-neutral user interaction control."""

    control_id: str
    label: str
    control_type: ChannelControlType
    action: str
    parameters: Mapping[str, object]
    required_capability: str

    def __post_init__(self) -> None:
        """Validate safe control metadata and deeply frozen parameters."""
        _validate_uuid(self.control_id, field_name="control_id")
        _require_text(self.label, field_name="label")

        if len(self.label) > _MAX_LABEL_LENGTH:
            raise ValueError(f"label must not exceed {_MAX_LABEL_LENGTH} characters.")

        if _COMMAND_PATTERN.fullmatch(self.action) is None:
            raise ValueError("action must use a lower-case deterministic identifier.")

        if _CAPABILITY_PATTERN.fullmatch(self.required_capability) is None:
            raise ValueError("required_capability must use a namespaced identifier.")

        object.__setattr__(
            self,
            "parameters",
            _freeze_mapping(self.parameters, field_name="parameters"),
        )


@dataclass(frozen=True, slots=True)
class ChannelResponse:
    """One safe transport-neutral response returned to a channel."""

    request_id: str
    outcome: ChannelResponseOutcome
    message: str
    responded_at: datetime
    data: Mapping[str, object] | None = None
    controls: tuple[ChannelControl, ...] = ()
    correlation_id: str | None = None
    issue: ChannelIssue | None = None
    schema_version: int = CHANNEL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Validate response consistency and deeply frozen structured data."""
        _validate_schema_version(self.schema_version)
        _validate_uuid(self.request_id, field_name="request_id")
        _require_text(self.message, field_name="message")

        if len(self.message) > _MAX_MESSAGE_LENGTH:
            raise ValueError(
                f"message must not exceed {_MAX_MESSAGE_LENGTH} characters."
            )

        _validate_utc_timestamp(self.responded_at, field_name="responded_at")

        if self.correlation_id is not None:
            _validate_uuid(self.correlation_id, field_name="correlation_id")

        if self.outcome is ChannelResponseOutcome.SUCCEEDED:
            if self.issue is not None:
                raise ValueError(
                    "A successful channel response must not contain an issue."
                )
        elif self.issue is None:
            raise ValueError("A non-success channel response must contain an issue.")

        if self.data is not None:
            object.__setattr__(
                self,
                "data",
                _freeze_mapping(self.data, field_name="data"),
            )

        object.__setattr__(self, "controls", tuple(self.controls))


def _validate_schema_version(value: int) -> None:
    if value != CHANNEL_SCHEMA_VERSION:
        raise ValueError("Unsupported channel contract schema version.")


def _validate_uuid(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")

    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a valid UUID.") from error

    if str(parsed) != value:
        raise ValueError(f"{field_name} must use canonical lower-case UUID format.")


def _validate_utc_timestamp(value: datetime, *, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime.")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")

    if value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{field_name} must use UTC.")


def _require_text(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")

    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


def _validate_positive_decimal_identifier(
    value: str,
    *,
    field_name: str,
) -> None:
    if not value.isascii() or not value.isdecimal() or value.startswith("0"):
        raise ValueError(f"{field_name} must use a canonical positive decimal string.")

    if int(value) < 1:
        raise ValueError(f"{field_name} must use a canonical positive decimal string.")


def _freeze_mapping(
    value: Mapping[str, object],
    *,
    field_name: str,
) -> Mapping[str, FrozenJsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping.")

    try:
        return freeze_parameters(value)
    except ActionContractError as error:
        raise ValueError(
            f"{field_name} must contain JSON-compatible values."
        ) from error
