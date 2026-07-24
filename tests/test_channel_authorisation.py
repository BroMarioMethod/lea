"""Tests for channel-user authorisation and capability resolution."""

from dataclasses import FrozenInstanceError

import pytest

from lea.channels import (
    AUTHORISATION_SCHEMA_VERSION,
    AuthorisedChannelUser,
    ChannelAuthorisationIssue,
    ChannelAuthorisationResult,
    ChannelCapability,
    ChannelName,
    ChannelRole,
    ChannelRolePolicy,
    authorise_channel_identity,
    default_channel_role_policies,
    resolve_channel_capabilities,
)


def _user(
    *,
    name: str = "Owner",
    channel: ChannelName = ChannelName.TELEGRAM,
    user_id: str = "123456789",
    conversation_id: str = "123456789",
    role: ChannelRole = ChannelRole.OWNER,
    enabled: bool = True,
    add_capabilities: tuple[ChannelCapability, ...] = (),
    remove_capabilities: tuple[ChannelCapability, ...] = (),
) -> AuthorisedChannelUser:
    return AuthorisedChannelUser(
        name=name,
        channel=channel,
        user_id=user_id,
        conversation_id=conversation_id,
        role=role,
        enabled=enabled,
        add_capabilities=add_capabilities,
        remove_capabilities=remove_capabilities,
    )


def test_schema_and_role_values_are_stable() -> None:
    assert AUTHORISATION_SCHEMA_VERSION == 1
    assert ChannelRole.OWNER.value == "owner"
    assert ChannelRole.TESTER.value == "tester"
    assert ChannelRole.READ_ONLY.value == "read_only"


def test_capability_values_are_stable() -> None:
    assert ChannelCapability.RUNTIME_STATUS_READ.value == "Runtime.Status.Read"
    assert ChannelCapability.TASKS_READ.value == "Tasks.Read"
    assert ChannelCapability.PROPOSALS_CONFIRM.value == "Proposals.Confirm"
    assert ChannelCapability.KNOWLEDGE_READ_CRITICAL.value == "Knowledge.Read.Critical"


def test_default_role_policies_cover_each_role_once() -> None:
    policies = default_channel_role_policies()

    assert tuple(policy.role for policy in policies) == (
        ChannelRole.OWNER,
        ChannelRole.TESTER,
        ChannelRole.READ_ONLY,
    )


def test_owner_receives_all_built_in_capabilities() -> None:
    capabilities = resolve_channel_capabilities(_user())

    assert capabilities == tuple(
        sorted(capability.value for capability in ChannelCapability)
    )


def test_tester_has_more_access_than_read_only() -> None:
    tester = set(resolve_channel_capabilities(_user(role=ChannelRole.TESTER)))
    read_only = set(resolve_channel_capabilities(_user(role=ChannelRole.READ_ONLY)))

    assert read_only < tester
    assert ChannelCapability.TASKS_WRITE.value in tester
    assert ChannelCapability.PROPOSALS_CONFIRM.value in tester


def test_tester_excludes_high_risk_and_critical_access() -> None:
    capabilities = resolve_channel_capabilities(_user(role=ChannelRole.TESTER))

    assert ChannelCapability.PROPOSALS_EXECUTE_HIGH_RISK.value not in capabilities
    assert ChannelCapability.KNOWLEDGE_READ_CRITICAL.value not in capabilities


def test_read_only_has_no_write_or_confirmation_capabilities() -> None:
    capabilities = resolve_channel_capabilities(_user(role=ChannelRole.READ_ONLY))

    assert ChannelCapability.TASKS_WRITE.value not in capabilities
    assert ChannelCapability.TASKS_DELETE.value not in capabilities
    assert ChannelCapability.PROPOSALS_CONFIRM.value not in capabilities


def test_explicit_additions_extend_role_defaults() -> None:
    capabilities = resolve_channel_capabilities(
        _user(
            role=ChannelRole.TESTER,
            add_capabilities=(ChannelCapability.KNOWLEDGE_READ_MEDIUM,),
        )
    )

    assert ChannelCapability.KNOWLEDGE_READ_MEDIUM.value in capabilities


def test_explicit_removals_override_defaults_and_additions() -> None:
    capabilities = resolve_channel_capabilities(
        _user(
            role=ChannelRole.TESTER,
            add_capabilities=(ChannelCapability.TASKS_WRITE,),
            remove_capabilities=(ChannelCapability.TASKS_WRITE,),
        )
    )

    assert ChannelCapability.TASKS_WRITE.value not in capabilities


def test_user_capability_overrides_are_canonicalised() -> None:
    user = _user(
        add_capabilities=(
            ChannelCapability.TASKS_WRITE,
            ChannelCapability.TASKS_READ,
            ChannelCapability.TASKS_WRITE,
        ),
        remove_capabilities=(
            ChannelCapability.KNOWLEDGE_READ_CRITICAL,
            ChannelCapability.KNOWLEDGE_READ_CRITICAL,
        ),
    )

    assert user.add_capabilities == (
        ChannelCapability.TASKS_READ,
        ChannelCapability.TASKS_WRITE,
    )
    assert user.remove_capabilities == (ChannelCapability.KNOWLEDGE_READ_CRITICAL,)


def test_exact_user_and_conversation_pair_is_authorised() -> None:
    result = authorise_channel_identity(
        channel=ChannelName.TELEGRAM,
        user_id="123456789",
        conversation_id="123456789",
        users=(_user(),),
    )

    assert result.authorised is True
    assert result.identity is not None
    assert result.identity.display_name == "Owner"
    assert result.identity.role == "owner"


@pytest.mark.parametrize(
    ("user_id", "conversation_id"),
    [
        ("999999999", "123456789"),
        ("123456789", "999999999"),
        ("999999999", "999999999"),
    ],
)
def test_partial_or_unknown_identity_is_rejected(
    user_id: str,
    conversation_id: str,
) -> None:
    result = authorise_channel_identity(
        channel=ChannelName.TELEGRAM,
        user_id=user_id,
        conversation_id=conversation_id,
        users=(_user(),),
    )

    assert result.authorised is False
    assert result.identity is None
    assert result.issues[0].code == "channel_identity_not_authorised"


def test_display_name_never_authenticates() -> None:
    result = authorise_channel_identity(
        channel=ChannelName.TELEGRAM,
        user_id="999999999",
        conversation_id="999999999",
        users=(_user(name="Matching display name"),),
    )

    assert result.authorised is False


def test_disabled_user_fails_closed() -> None:
    result = authorise_channel_identity(
        channel=ChannelName.TELEGRAM,
        user_id="123456789",
        conversation_id="123456789",
        users=(_user(enabled=False),),
    )

    assert result.authorised is False
    assert result.issues[0].code == "channel_identity_disabled"


def test_duplicate_exact_records_fail_closed() -> None:
    result = authorise_channel_identity(
        channel=ChannelName.TELEGRAM,
        user_id="123456789",
        conversation_id="123456789",
        users=(_user(), _user(name="Duplicate")),
    )

    assert result.authorised is False
    assert result.issues[0].code == "channel_identity_ambiguous"


def test_missing_role_policy_fails_closed() -> None:
    result = authorise_channel_identity(
        channel=ChannelName.TELEGRAM,
        user_id="123456789",
        conversation_id="123456789",
        users=(_user(),),
        policies=(
            ChannelRolePolicy(
                role=ChannelRole.TESTER,
                capabilities=(),
            ),
        ),
    )

    assert result.authorised is False
    assert result.issues[0].code == "channel_authorisation_policy_invalid"


def test_duplicate_role_policy_fails_closed() -> None:
    owner_policy = ChannelRolePolicy(
        role=ChannelRole.OWNER,
        capabilities=(),
    )
    result = authorise_channel_identity(
        channel=ChannelName.TELEGRAM,
        user_id="123456789",
        conversation_id="123456789",
        users=(_user(),),
        policies=(owner_policy, owner_policy),
    )

    assert result.authorised is False
    assert result.issues[0].code == "channel_authorisation_policy_invalid"


@pytest.mark.parametrize("value", ["01", "-1", "user"])
def test_telegram_user_identifier_must_be_canonical(value: str) -> None:
    with pytest.raises(ValueError, match="positive decimal"):
        _user(user_id=value)


@pytest.mark.parametrize("value", ["01", "-100", "chat"])
def test_telegram_conversation_identifier_must_be_canonical(
    value: str,
) -> None:
    with pytest.raises(ValueError, match="positive decimal"):
        _user(conversation_id=value)


def test_authorised_user_rejects_unsupported_schema() -> None:
    with pytest.raises(ValueError, match="Unsupported channel"):
        AuthorisedChannelUser(
            name="Owner",
            channel=ChannelName.TELEGRAM,
            user_id="123456789",
            conversation_id="123456789",
            role=ChannelRole.OWNER,
            schema_version=2,
        )


def test_authorisation_result_consistency() -> None:
    issue = ChannelAuthorisationIssue(
        code="denied",
        message="Access denied.",
    )

    with pytest.raises(ValueError, match="must contain a channel identity"):
        ChannelAuthorisationResult(
            authorised=True,
            identity=None,
            issues=(),
        )

    with pytest.raises(ValueError, match="must not contain an identity"):
        ChannelAuthorisationResult(
            authorised=False,
            identity=authorise_channel_identity(
                channel=ChannelName.TELEGRAM,
                user_id="123456789",
                conversation_id="123456789",
                users=(_user(),),
            ).identity,
            issues=(issue,),
        )


@pytest.mark.parametrize(
    ("factory", "field_name"),
    [
        (_user, "name"),
        (
            lambda: ChannelRolePolicy(
                role=ChannelRole.READ_ONLY,
                capabilities=(),
            ),
            "role",
        ),
        (
            lambda: ChannelAuthorisationIssue(
                code="denied",
                message="Access denied.",
            ),
            "code",
        ),
        (
            lambda: authorise_channel_identity(
                channel=ChannelName.TELEGRAM,
                user_id="123456789",
                conversation_id="123456789",
                users=(_user(),),
            ),
            "authorised",
        ),
    ],
)
def test_authorisation_contracts_are_immutable(
    factory: object,
    field_name: str,
) -> None:
    value = factory()  # type: ignore[operator]

    with pytest.raises(FrozenInstanceError):
        setattr(value, field_name, "changed")
