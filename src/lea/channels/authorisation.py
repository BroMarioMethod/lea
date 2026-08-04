"""Deterministic channel-user authorisation and capability resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from lea.channels.contracts import ChannelIdentity, ChannelName

AUTHORISATION_SCHEMA_VERSION = 1


class ChannelRole(StrEnum):
    """Stable built-in channel roles."""

    OWNER = "owner"
    TESTER = "tester"
    READ_ONLY = "read_only"


class ChannelCapability(StrEnum):
    """Stable built-in channel capabilities."""

    RUNTIME_STATUS_READ = "Runtime.Status.Read"

    CALENDAR_READ = "Calendar.Read"
    CALENDAR_WRITE = "Calendar.Write"
    CALENDAR_DELETE = "Calendar.Delete"
    CALENDAR_SYNC = "Calendar.Sync"

    TASKS_READ = "Tasks.Read"
    TASKS_WRITE = "Tasks.Write"
    TASKS_DELETE = "Tasks.Delete"

    PROPOSALS_READ = "Proposals.Read"
    PROPOSALS_CONFIRM = "Proposals.Confirm"
    PROPOSALS_EXECUTE_LOW_RISK = "Proposals.Execute.LowRisk"
    PROPOSALS_EXECUTE_MEDIUM_RISK = "Proposals.Execute.MediumRisk"
    PROPOSALS_EXECUTE_HIGH_RISK = "Proposals.Execute.HighRisk"

    KNOWLEDGE_READ_LOW = "Knowledge.Read.Low"
    KNOWLEDGE_READ_MEDIUM = "Knowledge.Read.Medium"
    KNOWLEDGE_READ_CRITICAL = "Knowledge.Read.Critical"


@dataclass(frozen=True, slots=True)
class ChannelRolePolicy:
    """One immutable role-to-capability policy."""

    role: ChannelRole
    capabilities: tuple[ChannelCapability, ...]

    def __post_init__(self) -> None:
        """Canonicalise role capabilities."""
        object.__setattr__(
            self,
            "capabilities",
            tuple(sorted(set(self.capabilities), key=str)),
        )


@dataclass(frozen=True, slots=True)
class AuthorisedChannelUser:
    """One configured channel identity permitted to request access."""

    name: str
    channel: ChannelName
    user_id: str
    conversation_id: str
    role: ChannelRole
    enabled: bool = True
    add_capabilities: tuple[ChannelCapability, ...] = ()
    remove_capabilities: tuple[ChannelCapability, ...] = ()
    calendar_ids: tuple[str, ...] = ()
    schema_version: int = AUTHORISATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Validate and canonicalise one authorised-user record."""
        if self.schema_version != AUTHORISATION_SCHEMA_VERSION:
            raise ValueError("Unsupported channel authorisation schema version.")

        if not self.name.strip():
            raise ValueError("name must be a non-empty string.")

        if not self.user_id.strip():
            raise ValueError("user_id must be a non-empty string.")

        if not self.conversation_id.strip():
            raise ValueError("conversation_id must be a non-empty string.")

        if self.channel is ChannelName.TELEGRAM:
            _validate_positive_decimal_identifier(
                self.user_id,
                field_name="user_id",
            )
            _validate_positive_decimal_identifier(
                self.conversation_id,
                field_name="conversation_id",
            )

        additions = tuple(sorted(set(self.add_capabilities), key=str))
        removals = tuple(sorted(set(self.remove_capabilities), key=str))

        object.__setattr__(self, "add_capabilities", additions)
        object.__setattr__(self, "remove_capabilities", removals)
        calendar_ids = tuple(sorted(set(self.calendar_ids)))
        for calendar_id in calendar_ids:
            if not isinstance(calendar_id, str) or not calendar_id.strip():
                raise ValueError("calendar_ids must contain non-empty strings.")
            if calendar_id != calendar_id.strip():
                raise ValueError(
                    "calendar_ids must not contain surrounding whitespace."
                )
        object.__setattr__(self, "calendar_ids", calendar_ids)


@dataclass(frozen=True, slots=True)
class ChannelAuthorisationIssue:
    """One deterministic authorisation failure."""

    code: str
    message: str

    def __post_init__(self) -> None:
        """Validate safe issue fields."""
        if not self.code.strip():
            raise ValueError("Authorisation issue code must be non-empty.")

        if not self.message.strip():
            raise ValueError("Authorisation issue message must be non-empty.")


@dataclass(frozen=True, slots=True)
class ChannelAuthorisationResult:
    """Result of authorising one channel user and conversation pair."""

    authorised: bool
    identity: ChannelIdentity | None
    issues: tuple[ChannelAuthorisationIssue, ...]

    def __post_init__(self) -> None:
        """Enforce result consistency."""
        if self.authorised:
            if self.identity is None:
                raise ValueError(
                    "An authorised result must contain a channel identity."
                )
            if self.issues:
                raise ValueError("An authorised result must not contain issues.")
            return

        if self.identity is not None:
            raise ValueError(
                "A rejected authorisation result must not contain an identity."
            )

        if not self.issues:
            raise ValueError(
                "A rejected authorisation result must contain at least one issue."
            )


_DEFAULT_ROLE_POLICIES = (
    ChannelRolePolicy(
        role=ChannelRole.OWNER,
        capabilities=tuple(ChannelCapability),
    ),
    ChannelRolePolicy(
        role=ChannelRole.TESTER,
        capabilities=(
            ChannelCapability.RUNTIME_STATUS_READ,
            ChannelCapability.CALENDAR_READ,
            ChannelCapability.CALENDAR_WRITE,
            ChannelCapability.TASKS_READ,
            ChannelCapability.TASKS_WRITE,
            ChannelCapability.PROPOSALS_READ,
            ChannelCapability.PROPOSALS_CONFIRM,
            ChannelCapability.PROPOSALS_EXECUTE_LOW_RISK,
            ChannelCapability.KNOWLEDGE_READ_LOW,
        ),
    ),
    ChannelRolePolicy(
        role=ChannelRole.READ_ONLY,
        capabilities=(
            ChannelCapability.RUNTIME_STATUS_READ,
            ChannelCapability.CALENDAR_READ,
            ChannelCapability.TASKS_READ,
            ChannelCapability.PROPOSALS_READ,
            ChannelCapability.KNOWLEDGE_READ_LOW,
        ),
    ),
)


def default_channel_role_policies() -> tuple[ChannelRolePolicy, ...]:
    """Return the immutable built-in role policy set."""
    return _DEFAULT_ROLE_POLICIES


def resolve_channel_capabilities(
    user: AuthorisedChannelUser,
    *,
    policies: tuple[ChannelRolePolicy, ...] | None = None,
) -> tuple[str, ...]:
    """Resolve deterministic capabilities for one configured user."""
    resolved_policies = policies or _DEFAULT_ROLE_POLICIES
    matching = tuple(policy for policy in resolved_policies if policy.role is user.role)

    if len(matching) != 1:
        raise ValueError(
            "Exactly one channel role policy must match the configured role."
        )

    capabilities = set(matching[0].capabilities)
    capabilities.update(user.add_capabilities)
    capabilities.difference_update(user.remove_capabilities)

    return tuple(sorted(capability.value for capability in capabilities))


def authorise_channel_identity(
    *,
    channel: ChannelName,
    user_id: str,
    conversation_id: str,
    users: tuple[AuthorisedChannelUser, ...],
    policies: tuple[ChannelRolePolicy, ...] | None = None,
) -> ChannelAuthorisationResult:
    """Authorise one exact channel user and conversation pair."""
    exact_matches = tuple(
        user
        for user in users
        if user.channel is channel
        and user.user_id == user_id
        and user.conversation_id == conversation_id
    )

    if not exact_matches:
        return ChannelAuthorisationResult(
            authorised=False,
            identity=None,
            issues=(
                ChannelAuthorisationIssue(
                    code="channel_identity_not_authorised",
                    message=(
                        "The supplied channel user and conversation are not authorised."
                    ),
                ),
            ),
        )

    if len(exact_matches) != 1:
        return ChannelAuthorisationResult(
            authorised=False,
            identity=None,
            issues=(
                ChannelAuthorisationIssue(
                    code="channel_identity_ambiguous",
                    message=(
                        "The supplied channel identity matches more than one "
                        "authorisation record."
                    ),
                ),
            ),
        )

    user = exact_matches[0]

    if not user.enabled:
        return ChannelAuthorisationResult(
            authorised=False,
            identity=None,
            issues=(
                ChannelAuthorisationIssue(
                    code="channel_identity_disabled",
                    message="The supplied channel identity is disabled.",
                ),
            ),
        )

    try:
        capabilities = resolve_channel_capabilities(
            user,
            policies=policies,
        )
        identity = ChannelIdentity(
            channel=channel,
            user_id=user.user_id,
            conversation_id=user.conversation_id,
            display_name=user.name,
            role=user.role.value,
            capabilities=capabilities,
            calendar_ids=user.calendar_ids,
        )
    except (TypeError, ValueError):
        return ChannelAuthorisationResult(
            authorised=False,
            identity=None,
            issues=(
                ChannelAuthorisationIssue(
                    code="channel_authorisation_policy_invalid",
                    message=("The configured channel authorisation policy is invalid."),
                ),
            ),
        )

    return ChannelAuthorisationResult(
        authorised=True,
        identity=identity,
        issues=(),
    )


def _validate_positive_decimal_identifier(
    value: str,
    *,
    field_name: str,
) -> None:
    if not value.isascii() or not value.isdecimal() or value.startswith("0"):
        raise ValueError(f"{field_name} must use a canonical positive decimal string.")

    if int(value) < 1:
        raise ValueError(f"{field_name} must use a canonical positive decimal string.")
