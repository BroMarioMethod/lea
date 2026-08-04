"""Tests for deterministic Telegram command routing."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from lea.adapters.telegram import (
    TelegramCommandDefinition,
    TelegramCommandRoutingResult,
    TelegramParsedCallback,
    TelegramParsedMessage,
    TelegramUpdateKind,
    TelegramUpdateParseIssue,
    TelegramUpdateParseResult,
    default_telegram_command_definitions,
    route_telegram_update,
)
from lea.channels import (
    AuthorisedChannelUser,
    ChannelCapability,
    ChannelName,
    ChannelRequestType,
    ChannelRole,
)

REQUEST_ID = "11111111-1111-4111-8111-111111111111"
PROPOSAL_ID = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


def _owner(
    *,
    role: ChannelRole = ChannelRole.OWNER,
    remove_capabilities: tuple[ChannelCapability, ...] = (),
) -> AuthorisedChannelUser:
    return AuthorisedChannelUser(
        name="Owner",
        channel=ChannelName.TELEGRAM,
        user_id="123456789",
        conversation_id="123456789",
        role=role,
        remove_capabilities=remove_capabilities,
    )


def _message(text: str = "/status") -> TelegramUpdateParseResult:
    return TelegramUpdateParseResult(
        success=True,
        kind=TelegramUpdateKind.PRIVATE_COMMAND,
        message=TelegramParsedMessage(
            update_id=10,
            message_id=7,
            user_id="123456789",
            chat_id="123456789",
            text=text,
        ),
        callback=None,
        issues=(),
    )


def _callback(
    data: str = f"proposal.approve:{PROPOSAL_ID}",
) -> TelegramUpdateParseResult:
    return TelegramUpdateParseResult(
        success=True,
        kind=TelegramUpdateKind.CALLBACK_QUERY,
        message=None,
        callback=TelegramParsedCallback(
            update_id=11,
            callback_query_id="callback-1",
            user_id="123456789",
            chat_id="123456789",
            message_id=8,
            data=data,
        ),
        issues=(),
    )


def _route(
    parsed: TelegramUpdateParseResult,
    *,
    users: tuple[AuthorisedChannelUser, ...] | None = None,
    bot_username: str | None = None,
) -> TelegramCommandRoutingResult:
    return route_telegram_update(
        parsed,
        users=users or (_owner(),),
        request_id_source=lambda: REQUEST_ID,
        clock=lambda: NOW,
        bot_username=bot_username,
    )


def test_default_definitions_cover_active_command_set() -> None:
    commands = tuple(
        definition.telegram_command
        for definition in default_telegram_command_definitions()
    )

    assert commands == (
        "/start",
        "/help",
        "/status",
        "/tasks",
        "/calendars",
        "/calendar_events",
        "/calendar_show",
        "/calendar_sync",
        "/task_add",
        "/task_show",
        "/task_modify",
        "/task_complete",
        "/task_delete",
        "/proposals",
        "/proposal_show",
        "/proposal_approve",
        "/proposal_reject",
        "/proposal_cancel",
        "/proposal_execute",
    )


def test_status_routes_to_channel_request() -> None:
    result = _route(_message())

    assert result.success is True
    assert result.request is not None
    assert result.route is not None
    assert result.request.command == "runtime.status"
    assert result.request.request_type is ChannelRequestType.COMMAND
    assert result.request.source_update_id == "telegram:10"
    assert result.request.request_id == REQUEST_ID
    assert result.request.received_at == NOW
    assert result.request.parameters["arguments"] == ()
    assert result.request.parameters["telegram_message_id"] == 7


def test_command_arguments_use_deterministic_shell_tokenisation() -> None:
    result = _route(_message('/task_add "Inspect steam system" urgent'))

    assert result.success is True
    assert result.request is not None
    assert result.request.parameters["arguments"] == (
        "Inspect steam system",
        "urgent",
    )


def test_matching_bot_suffix_is_removed_case_insensitively() -> None:
    result = _route(
        _message("/status@Lea_Test_Bot"),
        bot_username="lea_test_bot",
    )

    assert result.success is True
    assert result.request is not None
    assert result.request.command == "runtime.status"


def test_wrong_bot_suffix_is_rejected() -> None:
    result = _route(
        _message("/status@other_bot"),
        bot_username="lea_test_bot",
    )

    assert result.success is False
    assert result.issues[0].code == "telegram_command_bot_mismatch"


def test_unknown_command_is_rejected() -> None:
    result = _route(_message("/unknown"))

    assert result.success is False
    assert result.issues[0].code == "telegram_command_unknown"


def test_invalid_quoted_command_is_rejected() -> None:
    result = _route(_message('/task_add "unfinished'))

    assert result.success is False
    assert result.issues[0].code == "telegram_command_syntax_invalid"


def test_argument_bounds_are_enforced() -> None:
    missing = _route(_message("/task_show"))
    excessive = _route(_message("/task_show one two"))

    assert missing.issues[0].code == "telegram_command_arguments_missing"
    assert excessive.issues[0].code == "telegram_command_arguments_excessive"


def test_authorisation_occurs_before_request_construction() -> None:
    called = False

    def request_id_source() -> str:
        nonlocal called
        called = True
        return REQUEST_ID

    result = route_telegram_update(
        _message(),
        users=(),
        request_id_source=request_id_source,
        clock=lambda: NOW,
    )

    assert result.success is False
    assert result.issues[0].code == "channel_identity_not_authorised"
    assert called is False


def test_explicit_capability_is_required() -> None:
    result = _route(
        _message("/task_delete 11111111-1111-4111-8111-111111111111"),
        users=(_owner(remove_capabilities=(ChannelCapability.TASKS_DELETE,)),),
    )

    assert result.success is False
    assert result.issues[0].code == "telegram_capability_required"


def test_read_only_can_read_but_cannot_write() -> None:
    read_result = _route(
        _message("/tasks"),
        users=(_owner(role=ChannelRole.READ_ONLY),),
    )
    write_result = _route(
        _message("/task_add Test"),
        users=(_owner(role=ChannelRole.READ_ONLY),),
    )

    assert read_result.success is True
    assert write_result.success is False
    assert write_result.issues[0].code == "telegram_capability_required"


@pytest.mark.parametrize(
    ("action", "request_type", "command"),
    [
        (
            "proposal.approve",
            ChannelRequestType.CONFIRMATION,
            "proposals.approve",
        ),
        (
            "proposal.reject",
            ChannelRequestType.CONFIRMATION,
            "proposals.reject",
        ),
        (
            "proposal.cancel",
            ChannelRequestType.CONFIRMATION,
            "proposals.cancel",
        ),
        (
            "proposal.execute",
            ChannelRequestType.COMMAND,
            "proposals.execute",
        ),
    ],
)
def test_callback_routes(
    action: str,
    request_type: ChannelRequestType,
    command: str,
) -> None:
    result = _route(_callback(f"{action}:{PROPOSAL_ID}"))

    assert result.success is True
    assert result.request is not None
    assert result.request.request_type is request_type
    assert result.request.command == command
    assert result.request.parameters["proposal_id"] == PROPOSAL_ID
    assert result.request.parameters["callback_query_id"] == "callback-1"


def test_callback_rejects_unknown_action() -> None:
    result = _route(_callback(f"proposal.archive:{PROPOSAL_ID}"))

    assert result.success is False
    assert result.issues[0].code == "telegram_callback_route_unknown"


def test_callback_rejects_invalid_proposal_id() -> None:
    result = _route(_callback("proposal.approve:not-a-uuid"))

    assert result.success is False
    assert result.issues[0].code == "telegram_callback_proposal_id_invalid"


def test_failed_parse_result_cannot_be_routed() -> None:
    parsed = TelegramUpdateParseResult(
        success=False,
        kind=None,
        message=None,
        callback=None,
        issues=(
            TelegramUpdateParseIssue(
                code="placeholder",
                message="Placeholder.",
            ),
        ),
    )

    result = _route(parsed)

    assert result.success is False
    assert result.issues[0].code == "telegram_update_not_parsed"


@pytest.mark.parametrize(
    ("request_id", "clock_value"),
    [
        ("not-a-uuid", NOW),
        ("AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA", NOW),
        (REQUEST_ID, datetime(2026, 7, 24, 12, 0)),
        (
            REQUEST_ID,
            datetime(
                2026,
                7,
                24,
                14,
                0,
                tzinfo=timezone(timedelta(hours=2)),
            ),
        ),
    ],
)
def test_invalid_injected_dependencies_fail_closed(
    request_id: str,
    clock_value: datetime,
) -> None:
    result = route_telegram_update(
        _message(),
        users=(_owner(),),
        request_id_source=lambda: request_id,
        clock=lambda: clock_value,
    )

    assert result.success is False
    assert result.issues[0].code == "telegram_routing_dependency_invalid"


def test_duplicate_command_definitions_fail_closed() -> None:
    definition = TelegramCommandDefinition(
        telegram_command="/status",
        channel_command="runtime.status",
        required_capability=ChannelCapability.RUNTIME_STATUS_READ,
    )
    result = route_telegram_update(
        _message(),
        users=(_owner(),),
        request_id_source=lambda: REQUEST_ID,
        clock=lambda: NOW,
        definitions=(definition, definition),
    )

    assert result.success is False
    assert result.issues[0].code == "telegram_command_ambiguous"


def test_proposal_execute_route_requires_read_not_low_risk_execution() -> None:
    command = f"/proposal_execute {PROPOSAL_ID}"

    without_low_risk = _route(
        _message(command),
        users=(
            _owner(
                remove_capabilities=(ChannelCapability.PROPOSALS_EXECUTE_LOW_RISK,),
            ),
        ),
    )
    without_read = _route(
        _message(command),
        users=(
            _owner(
                remove_capabilities=(ChannelCapability.PROPOSALS_READ,),
            ),
        ),
    )

    assert without_low_risk.success is True
    assert without_low_risk.request is not None
    assert without_low_risk.request.command == "proposals.execute"
    assert without_read.success is False
    assert without_read.issues[0].code == "telegram_capability_required"


@pytest.mark.parametrize(
    "command",
    [
        f"/proposal_revise {PROPOSAL_ID} description=Revised",
        f"/knowledge_show {PROPOSAL_ID}",
        "/knowledge_find boiler",
    ],
)
def test_deferred_commands_are_not_active(command: str) -> None:
    result = _route(_message(command))

    assert result.success is False
    assert result.request is None


def test_deferred_revision_callback_is_not_routed() -> None:
    result = _route(_callback(f"proposal.revise:{PROPOSAL_ID}"))

    assert result.success is False
    assert result.request is None
