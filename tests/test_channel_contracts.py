"""Tests for immutable channel-neutral interaction contracts."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from types import MappingProxyType

import pytest

from lea.channels import (
    CHANNEL_SCHEMA_VERSION,
    ChannelControl,
    ChannelControlType,
    ChannelIdentity,
    ChannelIssue,
    ChannelName,
    ChannelRequest,
    ChannelRequestType,
    ChannelResponse,
    ChannelResponseOutcome,
)

REQUEST_ID = "11111111-1111-4111-8111-111111111111"
CONTROL_ID = "22222222-2222-4222-8222-222222222222"
CORRELATION_ID = "33333333-3333-4333-8333-333333333333"
NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


def _identity() -> ChannelIdentity:
    return ChannelIdentity(
        channel=ChannelName.TELEGRAM,
        user_id="123456789",
        conversation_id="123456789",
        display_name="Owner",
        role="owner",
        capabilities=("Tasks.Write", "Tasks.Read", "Tasks.Read"),
    )


def _request() -> ChannelRequest:
    return ChannelRequest(
        request_id=REQUEST_ID,
        source_update_id="42",
        identity=_identity(),
        request_type=ChannelRequestType.COMMAND,
        command="task.create",
        parameters={"description": "Test", "tags": ["lea"]},
        received_at=NOW,
        correlation_id=CORRELATION_ID,
    )


def _control() -> ChannelControl:
    return ChannelControl(
        control_id=CONTROL_ID,
        label="Approve",
        control_type=ChannelControlType.ACTION,
        action="proposal.approve",
        parameters={"proposal_id": REQUEST_ID},
        required_capability="Proposals.Confirm",
    )


def _issue() -> ChannelIssue:
    return ChannelIssue(
        code="not_authorised",
        message="This Telegram identity is not authorised.",
    )


def test_schema_and_enum_values_are_stable() -> None:
    assert CHANNEL_SCHEMA_VERSION == 1
    assert ChannelName.TELEGRAM.value == "telegram"
    assert ChannelRequestType.REVISION_REQUEST.value == "revision_request"
    assert ChannelResponseOutcome.NOT_AUTHORISED.value == "not_authorised"
    assert ChannelControlType.ACTION.value == "action"


def test_identity_canonicalises_capabilities() -> None:
    identity = _identity()

    assert identity.capabilities == ("Tasks.Read", "Tasks.Write")


@pytest.mark.parametrize("value", ["01", "-1", "abc", "\uff11\uff12\uff13"])
def test_telegram_user_id_must_be_canonical_decimal(value: str) -> None:
    with pytest.raises(ValueError, match="positive decimal"):
        ChannelIdentity(
            channel=ChannelName.TELEGRAM,
            user_id=value,
            conversation_id="123",
            role="owner",
            capabilities=(),
        )


@pytest.mark.parametrize("value", ["01", "-100", "chat"])
def test_telegram_conversation_id_must_be_canonical_decimal(value: str) -> None:
    with pytest.raises(ValueError, match="positive decimal"):
        ChannelIdentity(
            channel=ChannelName.TELEGRAM,
            user_id="123",
            conversation_id=value,
            role="owner",
            capabilities=(),
        )


@pytest.mark.parametrize("role", ["Owner", "read-only", "", " owner"])
def test_role_must_be_canonical(role: str) -> None:
    with pytest.raises(ValueError, match="role must use"):
        ChannelIdentity(
            channel=ChannelName.CLI,
            user_id="local",
            conversation_id="terminal",
            role=role,
            capabilities=(),
        )


@pytest.mark.parametrize(
    "capability",
    ["tasks.read", "Tasks", "Tasks.read", "Tasks-Read", ""],
)
def test_capability_must_be_namespaced(capability: str) -> None:
    with pytest.raises(ValueError, match="capabilities must use"):
        ChannelIdentity(
            channel=ChannelName.CLI,
            user_id="local",
            conversation_id="terminal",
            role="owner",
            capabilities=(capability,),
        )


def test_request_deeply_freezes_parameters() -> None:
    request = _request()

    assert isinstance(request.parameters, MappingProxyType)
    assert request.parameters["tags"] == ("lea",)

    with pytest.raises(TypeError):
        request.parameters["description"] = "Changed"  # type: ignore[index]


def test_request_rejects_non_json_parameters() -> None:
    with pytest.raises(ValueError, match="JSON-compatible"):
        ChannelRequest(
            request_id=REQUEST_ID,
            source_update_id="42",
            identity=_identity(),
            request_type=ChannelRequestType.COMMAND,
            command="task.create",
            parameters={"invalid": object()},
            received_at=NOW,
        )


@pytest.mark.parametrize("command", ["Task.Create", "/status", "task-create", ""])
def test_request_command_must_be_canonical(command: str) -> None:
    with pytest.raises(ValueError, match="command must use"):
        ChannelRequest(
            request_id=REQUEST_ID,
            source_update_id="42",
            identity=_identity(),
            request_type=ChannelRequestType.COMMAND,
            command=command,
            parameters={},
            received_at=NOW,
        )


@pytest.mark.parametrize(
    "request_id",
    [
        "not-a-uuid",
        "11111111111141118111111111111111",
        "11111111-1111-4111-8111-11111111111A",
    ],
)
def test_request_id_must_be_canonical_uuid(request_id: str) -> None:
    with pytest.raises(ValueError, match="request_id"):
        ChannelRequest(
            request_id=request_id,
            source_update_id="42",
            identity=_identity(),
            request_type=ChannelRequestType.COMMAND,
            command="status",
            parameters={},
            received_at=NOW,
        )


def test_request_timestamp_must_be_utc() -> None:
    with pytest.raises(ValueError, match="must use UTC"):
        ChannelRequest(
            request_id=REQUEST_ID,
            source_update_id="42",
            identity=_identity(),
            request_type=ChannelRequestType.COMMAND,
            command="status",
            parameters={},
            received_at=datetime(
                2026,
                7,
                24,
                14,
                0,
                tzinfo=timezone(timedelta(hours=2)),
            ),
        )


def test_control_deeply_freezes_parameters() -> None:
    control = _control()

    assert isinstance(control.parameters, MappingProxyType)

    with pytest.raises(TypeError):
        control.parameters["proposal_id"] = CONTROL_ID  # type: ignore[index]


def test_control_rejects_oversized_label() -> None:
    with pytest.raises(ValueError, match="must not exceed 80"):
        ChannelControl(
            control_id=CONTROL_ID,
            label="A" * 81,
            control_type=ChannelControlType.ACTION,
            action="proposal.approve",
            parameters={},
            required_capability="Proposals.Confirm",
        )


def test_successful_response_rejects_issue() -> None:
    with pytest.raises(ValueError, match="must not contain an issue"):
        ChannelResponse(
            request_id=REQUEST_ID,
            outcome=ChannelResponseOutcome.SUCCEEDED,
            message="Done.",
            responded_at=NOW,
            issue=_issue(),
        )


def test_failed_response_requires_issue() -> None:
    with pytest.raises(ValueError, match="must contain an issue"):
        ChannelResponse(
            request_id=REQUEST_ID,
            outcome=ChannelResponseOutcome.NOT_AUTHORISED,
            message="Access denied.",
            responded_at=NOW,
        )


def test_response_deeply_freezes_data_and_controls() -> None:
    response = ChannelResponse(
        request_id=REQUEST_ID,
        outcome=ChannelResponseOutcome.SUCCEEDED,
        message="Proposal awaiting confirmation.",
        responded_at=NOW,
        data={"proposal": {"id": REQUEST_ID}},
        controls=[_control()],  # type: ignore[arg-type]
        correlation_id=CORRELATION_ID,
    )

    assert isinstance(response.data, MappingProxyType)
    assert response.controls == (_control(),)

    with pytest.raises(TypeError):
        response.data["proposal"] = None  # type: ignore[index]


def test_non_successful_response_accepts_safe_issue() -> None:
    response = ChannelResponse(
        request_id=REQUEST_ID,
        outcome=ChannelResponseOutcome.NOT_AUTHORISED,
        message="Access denied.",
        responded_at=NOW,
        issue=_issue(),
    )

    assert response.issue == _issue()


def test_response_rejects_oversized_message() -> None:
    with pytest.raises(ValueError, match="must not exceed 4096"):
        ChannelResponse(
            request_id=REQUEST_ID,
            outcome=ChannelResponseOutcome.SUCCEEDED,
            message="A" * 4097,
            responded_at=NOW,
        )


def test_unsupported_schema_versions_are_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported channel"):
        ChannelRequest(
            request_id=REQUEST_ID,
            source_update_id="42",
            identity=_identity(),
            request_type=ChannelRequestType.COMMAND,
            command="status",
            parameters={},
            received_at=NOW,
            schema_version=2,
        )


@pytest.mark.parametrize(
    ("factory", "field_name"),
    [
        (_identity, "role"),
        (_request, "command"),
        (_control, "label"),
        (
            lambda: ChannelResponse(
                request_id=REQUEST_ID,
                outcome=ChannelResponseOutcome.SUCCEEDED,
                message="Done.",
                responded_at=NOW,
            ),
            "message",
        ),
        (_issue, "code"),
    ],
)
def test_public_contracts_are_immutable(
    factory: object,
    field_name: str,
) -> None:
    value = factory()  # type: ignore[operator]

    with pytest.raises(FrozenInstanceError):
        setattr(value, field_name, "changed")
