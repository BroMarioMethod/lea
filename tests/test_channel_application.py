"""Tests for channel-neutral application dispatch."""

from datetime import UTC, datetime

import pytest

from lea.channels import (
    ChannelApplication,
    ChannelCommandDefinition,
    ChannelIdentity,
    ChannelIssue,
    ChannelName,
    ChannelRequest,
    ChannelRequestType,
    ChannelResponse,
    ChannelResponseOutcome,
    DispatchingChannelApplication,
)

REQUEST_ID = "11111111-1111-4111-8111-111111111111"
CORRELATION_ID = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


def _request(
    *,
    command: str = "runtime.status",
) -> ChannelRequest:
    return ChannelRequest(
        request_id=REQUEST_ID,
        source_update_id="telegram:42",
        identity=ChannelIdentity(
            channel=ChannelName.TELEGRAM,
            user_id="123456789",
            conversation_id="123456789",
            role="owner",
            capabilities=("Runtime.Status.Read",),
        ),
        request_type=ChannelRequestType.COMMAND,
        command=command,
        parameters={},
        received_at=NOW,
        correlation_id=CORRELATION_ID,
    )


def _success(request: ChannelRequest) -> ChannelResponse:
    return ChannelResponse(
        request_id=request.request_id,
        outcome=ChannelResponseOutcome.SUCCEEDED,
        message="Runtime is healthy.",
        responded_at=NOW,
        correlation_id=request.correlation_id,
        data={"healthy": True},
    )


def _application() -> DispatchingChannelApplication:
    return DispatchingChannelApplication(
        (
            ChannelCommandDefinition(
                command="runtime.status",
                handler=_success,
            ),
        ),
        clock=lambda: NOW,
    )


def test_dispatches_exact_channel_command() -> None:
    result = _application().handle(_request())

    assert result.success is True
    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.SUCCEEDED
    assert result.response.data == {"healthy": True}


def test_application_satisfies_shared_protocol() -> None:
    assert isinstance(_application(), ChannelApplication)


def test_supported_commands_are_sorted() -> None:
    application = DispatchingChannelApplication(
        (
            ChannelCommandDefinition("tasks.list", _success),
            ChannelCommandDefinition("runtime.status", _success),
        ),
        clock=lambda: NOW,
    )

    assert application.commands == ("runtime.status", "tasks.list")


def test_unsupported_command_returns_safe_not_found_response() -> None:
    result = _application().handle(_request(command="knowledge.find"))

    assert result.success is True
    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.NOT_FOUND
    assert result.response.issue is not None
    assert result.response.issue.code == "channel_command_not_supported"
    assert result.response.data == {"command": "knowledge.find"}


def test_handler_exception_is_redacted() -> None:
    def handler(_request: ChannelRequest) -> ChannelResponse:
        raise RuntimeError("/etc/lea/secrets/private-token")

    application = DispatchingChannelApplication(
        (ChannelCommandDefinition("runtime.status", handler),),
        clock=lambda: NOW,
    )

    result = application.handle(_request())

    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.APPLICATION_FAILED
    assert "/etc/lea" not in result.response.message
    assert result.response.issue is not None
    assert "/etc/lea" not in result.response.issue.message


def test_mismatched_request_id_fails_closed() -> None:
    def handler(request: ChannelRequest) -> ChannelResponse:
        return ChannelResponse(
            request_id="33333333-3333-4333-8333-333333333333",
            outcome=ChannelResponseOutcome.SUCCEEDED,
            message="Done.",
            responded_at=NOW,
            correlation_id=request.correlation_id,
        )

    application = DispatchingChannelApplication(
        (ChannelCommandDefinition("runtime.status", handler),),
        clock=lambda: NOW,
    )

    result = application.handle(_request())

    assert result.success is False
    assert result.response is None
    assert result.issues[0].code == "channel_response_request_mismatch"


def test_mismatched_correlation_id_fails_closed() -> None:
    def handler(request: ChannelRequest) -> ChannelResponse:
        return ChannelResponse(
            request_id=request.request_id,
            outcome=ChannelResponseOutcome.SUCCEEDED,
            message="Done.",
            responded_at=NOW,
            correlation_id=None,
        )

    application = DispatchingChannelApplication(
        (ChannelCommandDefinition("runtime.status", handler),),
        clock=lambda: NOW,
    )

    result = application.handle(_request())

    assert result.success is False
    assert result.issues[0].code == "channel_response_correlation_mismatch"


def test_duplicate_command_definitions_are_rejected() -> None:
    with pytest.raises(ValueError, match="must be unique"):
        DispatchingChannelApplication(
            (
                ChannelCommandDefinition("runtime.status", _success),
                ChannelCommandDefinition("runtime.status", _success),
            ),
            clock=lambda: NOW,
        )


def test_empty_definition_collection_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one"):
        DispatchingChannelApplication((), clock=lambda: NOW)


def test_invalid_clock_is_redacted_as_handler_failure() -> None:
    def handler(_request: ChannelRequest) -> ChannelResponse:
        raise RuntimeError("failure")

    application = DispatchingChannelApplication(
        (ChannelCommandDefinition("runtime.status", handler),),
        clock=lambda: object(),
    )

    with pytest.raises(ValueError, match="must return a datetime"):
        application.handle(_request())


def test_result_contracts_enforce_consistency() -> None:
    from lea.channels import ChannelApplicationIssue, ChannelApplicationResult

    issue = ChannelApplicationIssue(
        code="failed",
        message="Application failed.",
    )

    with pytest.raises(ValueError, match="must contain a response"):
        ChannelApplicationResult(
            success=True,
            response=None,
            issues=(),
        )

    with pytest.raises(ValueError, match="at least one issue"):
        ChannelApplicationResult(
            success=False,
            response=None,
            issues=(),
        )

    assert issue.code == "failed"


def test_handler_may_return_safe_failure_response() -> None:
    def handler(request: ChannelRequest) -> ChannelResponse:
        return ChannelResponse(
            request_id=request.request_id,
            outcome=ChannelResponseOutcome.VALIDATION_FAILED,
            message="The request is invalid.",
            responded_at=NOW,
            correlation_id=request.correlation_id,
            issue=ChannelIssue(
                code="invalid_request",
                message="The request is invalid.",
            ),
        )

    application = DispatchingChannelApplication(
        (ChannelCommandDefinition("runtime.status", handler),),
        clock=lambda: NOW,
    )

    result = application.handle(_request())

    assert result.success is True
    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.VALIDATION_FAILED
