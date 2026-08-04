"""Strict TOML loading for authorised interaction-channel users."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from lea.channels.authorisation import (
    AUTHORISATION_SCHEMA_VERSION,
    AuthorisedChannelUser,
    ChannelCapability,
    ChannelRole,
)
from lea.channels.contracts import ChannelName

_TOP_LEVEL_FIELDS = frozenset({"schema_version", "users"})
_REQUIRED_TOP_LEVEL_FIELDS = _TOP_LEVEL_FIELDS
_USER_FIELDS = frozenset(
    {
        "name",
        "channel",
        "user_id",
        "conversation_id",
        "role",
        "enabled",
        "add_capabilities",
        "remove_capabilities",
        "calendar_ids",
    }
)
_REQUIRED_USER_FIELDS = frozenset(
    {
        "name",
        "channel",
        "user_id",
        "conversation_id",
        "role",
        "enabled",
    }
)


@dataclass(frozen=True, slots=True)
class AuthorisedUserConfigIssue:
    """One deterministic authorised-user configuration problem."""

    code: str
    message: str
    field: str | None = None
    source_path: Path | None = None

    def __post_init__(self) -> None:
        """Validate safe issue fields."""
        if not self.code.strip():
            raise ValueError("Authorised-user issue code must be non-empty.")

        if not self.message.strip():
            raise ValueError("Authorised-user issue message must be non-empty.")

        if self.field is not None and not self.field.strip():
            raise ValueError(
                "Authorised-user issue field must be non-empty when provided."
            )

        if self.source_path is not None and not self.source_path.is_absolute():
            raise ValueError("Authorised-user issue source_path must be absolute.")


@dataclass(frozen=True, slots=True)
class AuthorisedUserConfigResult:
    """Immutable result of parsing or loading authorised users."""

    success: bool
    users: tuple[AuthorisedChannelUser, ...]
    issues: tuple[AuthorisedUserConfigIssue, ...]

    def __post_init__(self) -> None:
        """Enforce result consistency."""
        if self.success:
            if self.issues:
                raise ValueError(
                    "A successful authorised-user result must not contain issues."
                )
            return

        if self.users:
            raise ValueError("A failed authorised-user result must not contain users.")

        if not self.issues:
            raise ValueError(
                "A failed authorised-user result must contain at least one issue."
            )


def load_authorised_channel_users(
    source_path: Path,
) -> AuthorisedUserConfigResult:
    """Load one strict authorised-user TOML file without side effects."""
    if not source_path.is_absolute():
        raise ValueError("source_path must be absolute.")

    if source_path.is_symlink():
        return _failure(
            code="authorised_users_symlink_rejected",
            message="Symbolic links are not permitted for authorised-user files.",
            source_path=source_path,
        )

    try:
        metadata = source_path.stat()
    except FileNotFoundError:
        return _failure(
            code="authorised_users_not_found",
            message="The authorised-user file was not found.",
            source_path=source_path,
        )
    except OSError:
        return _failure(
            code="authorised_users_stat_failed",
            message="The authorised-user file metadata could not be read.",
            source_path=source_path,
        )

    if not source_path.is_file():
        return _failure(
            code="authorised_users_not_regular_file",
            message="The authorised-user path is not a regular file.",
            source_path=source_path,
        )

    if metadata.st_mode & 0o022:
        return _failure(
            code="authorised_users_insecure_permissions",
            message=(
                "The authorised-user file must not be writable by the group "
                "or other users."
            ),
            source_path=source_path,
        )

    try:
        contents = source_path.read_text(encoding="utf-8")
    except UnicodeError:
        return _failure(
            code="authorised_users_invalid_utf8",
            message="The authorised-user file is not valid UTF-8.",
            source_path=source_path,
        )
    except OSError:
        return _failure(
            code="authorised_users_read_failed",
            message="The authorised-user file could not be read.",
            source_path=source_path,
        )

    return parse_authorised_channel_users(
        contents,
        source_path=source_path,
    )


def parse_authorised_channel_users(
    contents: str,
    *,
    source_path: Path | None = None,
) -> AuthorisedUserConfigResult:
    """Parse strict authorised-user TOML text."""
    if source_path is not None and not source_path.is_absolute():
        raise ValueError("source_path must be absolute when supplied.")

    try:
        parsed = tomllib.loads(contents)
    except tomllib.TOMLDecodeError:
        return _failure(
            code="authorised_users_invalid_toml",
            message="The authorised-user file contains invalid TOML.",
            source_path=source_path,
        )

    issues: list[AuthorisedUserConfigIssue] = []

    _validate_fields(
        parsed,
        required=_REQUIRED_TOP_LEVEL_FIELDS,
        known=_TOP_LEVEL_FIELDS,
        path="",
        issues=issues,
        source_path=source_path,
    )

    schema_version = parsed.get("schema_version")

    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != AUTHORISATION_SCHEMA_VERSION
    ):
        issues.append(
            AuthorisedUserConfigIssue(
                code="unsupported_schema_version",
                message=(
                    "schema_version must equal the supported authorised-user "
                    f"schema version {AUTHORISATION_SCHEMA_VERSION}."
                ),
                field="schema_version",
                source_path=source_path,
            )
        )

    raw_users = parsed.get("users")

    if not isinstance(raw_users, list):
        issues.append(
            AuthorisedUserConfigIssue(
                code="invalid_users",
                message="users must be an array of tables.",
                field="users",
                source_path=source_path,
            )
        )
        raw_users = []

    users: list[AuthorisedChannelUser] = []

    for index, raw_user in enumerate(raw_users):
        field_prefix = f"users[{index}]"

        if not isinstance(raw_user, Mapping):
            issues.append(
                AuthorisedUserConfigIssue(
                    code="invalid_user",
                    message="Each users entry must be a table.",
                    field=field_prefix,
                    source_path=source_path,
                )
            )
            continue

        before = len(issues)
        _validate_fields(
            raw_user,
            required=_REQUIRED_USER_FIELDS,
            known=_USER_FIELDS,
            path=field_prefix,
            issues=issues,
            source_path=source_path,
        )

        name = _require_string(
            raw_user.get("name"),
            field=f"{field_prefix}.name",
            issues=issues,
            source_path=source_path,
        )
        channel = _parse_enum(
            raw_user.get("channel"),
            enum_type=ChannelName,
            field=f"{field_prefix}.channel",
            issues=issues,
            source_path=source_path,
        )
        user_id = _parse_identifier(
            raw_user.get("user_id"),
            field=f"{field_prefix}.user_id",
            issues=issues,
            source_path=source_path,
        )
        conversation_id = _parse_identifier(
            raw_user.get("conversation_id"),
            field=f"{field_prefix}.conversation_id",
            issues=issues,
            source_path=source_path,
        )
        role = _parse_enum(
            raw_user.get("role"),
            enum_type=ChannelRole,
            field=f"{field_prefix}.role",
            issues=issues,
            source_path=source_path,
        )
        enabled = _require_boolean(
            raw_user.get("enabled"),
            field=f"{field_prefix}.enabled",
            issues=issues,
            source_path=source_path,
        )
        additions = _parse_capabilities(
            raw_user.get("add_capabilities", []),
            field=f"{field_prefix}.add_capabilities",
            issues=issues,
            source_path=source_path,
        )
        removals = _parse_capabilities(
            raw_user.get("remove_capabilities", []),
            field=f"{field_prefix}.remove_capabilities",
            issues=issues,
            source_path=source_path,
        )
        calendar_ids = _parse_calendar_ids(
            raw_user.get("calendar_ids", []),
            field=f"{field_prefix}.calendar_ids",
            issues=issues,
            source_path=source_path,
        )

        if len(issues) != before:
            continue

        assert name is not None
        assert channel is not None
        assert user_id is not None
        assert conversation_id is not None
        assert role is not None
        assert enabled is not None
        assert additions is not None
        assert removals is not None
        assert calendar_ids is not None

        try:
            users.append(
                AuthorisedChannelUser(
                    name=name,
                    channel=channel,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    role=role,
                    enabled=enabled,
                    add_capabilities=additions,
                    remove_capabilities=removals,
                    calendar_ids=calendar_ids,
                )
            )
        except (TypeError, ValueError) as error:
            issues.append(
                AuthorisedUserConfigIssue(
                    code="invalid_user",
                    message=str(error),
                    field=field_prefix,
                    source_path=source_path,
                )
            )

    duplicates = _duplicate_identity_indexes(tuple(users))

    for _first, duplicate in duplicates:
        issues.append(
            AuthorisedUserConfigIssue(
                code="duplicate_authorised_identity",
                message=(
                    "Authorised users must not contain duplicate channel, "
                    "user_id and conversation_id combinations."
                ),
                field=f"users[{duplicate}]",
                source_path=source_path,
            )
        )

    if issues:
        return AuthorisedUserConfigResult(
            success=False,
            users=(),
            issues=tuple(issues),
        )

    return AuthorisedUserConfigResult(
        success=True,
        users=tuple(users),
        issues=(),
    )


def _validate_fields(
    data: Mapping[str, object],
    *,
    required: frozenset[str],
    known: frozenset[str],
    path: str,
    issues: list[AuthorisedUserConfigIssue],
    source_path: Path | None,
) -> None:
    missing = sorted(required - data.keys())
    unknown = sorted(data.keys() - known)

    for field_name in missing:
        full_field = f"{path}.{field_name}" if path else field_name
        issues.append(
            AuthorisedUserConfigIssue(
                code="missing_field",
                message=f"Required field '{full_field}' is missing.",
                field=full_field,
                source_path=source_path,
            )
        )

    for field_name in unknown:
        full_field = f"{path}.{field_name}" if path else field_name
        issues.append(
            AuthorisedUserConfigIssue(
                code="unknown_field",
                message=f"Unknown field '{full_field}' is not permitted.",
                field=full_field,
                source_path=source_path,
            )
        )


def _require_string(
    value: object,
    *,
    field: str,
    issues: list[AuthorisedUserConfigIssue],
    source_path: Path | None,
) -> str | None:
    if not isinstance(value, str) or not value.strip():
        issues.append(
            AuthorisedUserConfigIssue(
                code="invalid_string",
                message=f"{field} must be a non-empty string.",
                field=field,
                source_path=source_path,
            )
        )
        return None

    return value


def _require_boolean(
    value: object,
    *,
    field: str,
    issues: list[AuthorisedUserConfigIssue],
    source_path: Path | None,
) -> bool | None:
    if not isinstance(value, bool):
        issues.append(
            AuthorisedUserConfigIssue(
                code="invalid_boolean",
                message=f"{field} must be a boolean.",
                field=field,
                source_path=source_path,
            )
        )
        return None

    return value


def _parse_identifier(
    value: object,
    *,
    field: str,
    issues: list[AuthorisedUserConfigIssue],
    source_path: Path | None,
) -> str | None:
    if isinstance(value, bool):
        valid = False
    elif isinstance(value, int):
        valid = value > 0
    elif isinstance(value, str):
        valid = (
            value.isascii()
            and value.isdecimal()
            and not value.startswith("0")
            and int(value) > 0
        )
    else:
        valid = False

    if not valid:
        issues.append(
            AuthorisedUserConfigIssue(
                code="invalid_identifier",
                message=(
                    f"{field} must be a canonical positive decimal integer or string."
                ),
                field=field,
                source_path=source_path,
            )
        )
        return None

    return str(value)


def _parse_calendar_ids(
    value: object,
    *,
    field: str,
    issues: list[AuthorisedUserConfigIssue],
    source_path: Path | None,
) -> tuple[str, ...] | None:
    if not isinstance(value, list) or any(
        not isinstance(item, str)
        or not item.strip()
        or item != item.strip()
        or any(ord(character) < 32 for character in item)
        for item in value
    ):
        issues.append(
            AuthorisedUserConfigIssue(
                code="invalid_calendar_ids",
                message=f"{field} must be an array of exact non-empty strings.",
                field=field,
                source_path=source_path,
            )
        )
        return None
    return tuple(sorted(set(value)))


def _parse_enum[ChannelEnum: (ChannelName, ChannelRole)](
    value: object,
    *,
    enum_type: type[ChannelEnum],
    field: str,
    issues: list[AuthorisedUserConfigIssue],
    source_path: Path | None,
) -> ChannelEnum | None:
    if not isinstance(value, str):
        issues.append(
            AuthorisedUserConfigIssue(
                code="invalid_enum",
                message=f"{field} must be a string.",
                field=field,
                source_path=source_path,
            )
        )
        return None

    try:
        return enum_type(value)
    except ValueError:
        supported = ", ".join(item.value for item in enum_type)
        issues.append(
            AuthorisedUserConfigIssue(
                code="invalid_enum",
                message=f"{field} must be one of: {supported}.",
                field=field,
                source_path=source_path,
            )
        )
        return None


def _parse_capabilities(
    value: object,
    *,
    field: str,
    issues: list[AuthorisedUserConfigIssue],
    source_path: Path | None,
) -> tuple[ChannelCapability, ...] | None:
    if not isinstance(value, list):
        issues.append(
            AuthorisedUserConfigIssue(
                code="invalid_capabilities",
                message=f"{field} must be an array of capability strings.",
                field=field,
                source_path=source_path,
            )
        )
        return None

    parsed: list[ChannelCapability] = []

    for index, item in enumerate(value):
        item_field = f"{field}[{index}]"

        if not isinstance(item, str):
            issues.append(
                AuthorisedUserConfigIssue(
                    code="invalid_capability",
                    message=f"{item_field} must be a capability string.",
                    field=item_field,
                    source_path=source_path,
                )
            )
            continue

        try:
            parsed.append(ChannelCapability(item))
        except ValueError:
            issues.append(
                AuthorisedUserConfigIssue(
                    code="unknown_capability",
                    message=f"{item_field} contains an unknown capability.",
                    field=item_field,
                    source_path=source_path,
                )
            )

    return tuple(sorted(set(parsed), key=str))


def _duplicate_identity_indexes(
    users: tuple[AuthorisedChannelUser, ...],
) -> tuple[tuple[int, int], ...]:
    seen: dict[tuple[ChannelName, str, str], int] = {}
    duplicates: list[tuple[int, int]] = []

    for index, user in enumerate(users):
        key = (user.channel, user.user_id, user.conversation_id)

        if key in seen:
            duplicates.append((seen[key], index))
        else:
            seen[key] = index

    return tuple(duplicates)


def _failure(
    *,
    code: str,
    message: str,
    source_path: Path | None,
) -> AuthorisedUserConfigResult:
    return AuthorisedUserConfigResult(
        success=False,
        users=(),
        issues=(
            AuthorisedUserConfigIssue(
                code=code,
                message=message,
                source_path=source_path,
            ),
        ),
    )
