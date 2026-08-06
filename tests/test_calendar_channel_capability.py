"""Tests for the built-in Calendar.Read channel capability policy."""

from lea.channels import (
    AuthorisedChannelUser,
    ChannelCapability,
    ChannelName,
    ChannelRole,
    resolve_channel_capabilities,
)


def _user(role: ChannelRole) -> AuthorisedChannelUser:
    """Return one deterministic Telegram authorisation record."""
    return AuthorisedChannelUser(
        name="Calendar user",
        channel=ChannelName.TELEGRAM,
        user_id="123456789",
        conversation_id="123456789",
        role=role,
    )


def test_calendar_read_capability_value_is_stable() -> None:
    """Calendar reads should use one explicit singular namespace."""
    assert ChannelCapability.CALENDAR_READ.value == "Calendar.Read"


def test_calendar_mutation_capability_values_are_stable() -> None:
    assert ChannelCapability.CALENDAR_WRITE.value == "Calendar.Write"
    assert ChannelCapability.CALENDAR_DELETE.value == "Calendar.Delete"
    assert ChannelCapability.CALENDAR_SYNC.value == "Calendar.Sync"


def test_owner_receives_calendar_read_through_all_capabilities() -> None:
    """Owner access should continue to cover every built-in capability."""
    capabilities = resolve_channel_capabilities(_user(ChannelRole.OWNER))

    assert ChannelCapability.CALENDAR_READ.value in capabilities


def test_tester_receives_calendar_read_by_default() -> None:
    """A tester may exercise low-risk read-only calendar workflows."""
    capabilities = resolve_channel_capabilities(_user(ChannelRole.TESTER))

    assert ChannelCapability.CALENDAR_READ.value in capabilities
    assert ChannelCapability.CALENDAR_WRITE.value in capabilities
    assert ChannelCapability.CALENDAR_DELETE.value not in capabilities
    assert ChannelCapability.CALENDAR_SYNC.value not in capabilities


def test_read_only_role_receives_calendar_read_without_write_access() -> None:
    """The read-only role should gain calendar reads but no task mutation."""
    capabilities = resolve_channel_capabilities(_user(ChannelRole.READ_ONLY))

    assert ChannelCapability.CALENDAR_READ.value in capabilities
    assert ChannelCapability.CALENDAR_WRITE.value not in capabilities
    assert ChannelCapability.CALENDAR_DELETE.value not in capabilities
    assert ChannelCapability.CALENDAR_SYNC.value not in capabilities
    assert ChannelCapability.TASKS_WRITE.value not in capabilities
    assert ChannelCapability.TASKS_DELETE.value not in capabilities
