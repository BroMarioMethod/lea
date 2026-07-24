"""Tests for Local CLI to channel response mapping."""

from datetime import UTC, datetime

import pytest

from lea.channels import (
    ChannelIdentity,
    ChannelName,
    ChannelRequest,
    ChannelRequestType,
    ChannelResponseOutcome,
)
from lea.channels.result_mapping import channel_response_from_cli_result
from lea.cli import CliIssue, CliResult, LocalCliExitCode

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
REQUEST_ID = "11111111-1111-4111-8111-111111111111"


def _request() -> ChannelRequest:
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
        command="runtime.status",
        parameters={"arguments": []},
        received_at=NOW,
    )


def test_success_result_maps_to_succeeded_response() -> None:
    response = channel_response_from_cli_result(
        _request(),
        CliResult.succeeded(data={"healthy": True}),
        clock=lambda: NOW,
        success_message="Status loaded.",
    )

    assert response.outcome is ChannelResponseOutcome.SUCCEEDED
    assert response.message == "Status loaded."
    assert response.data == {"healthy": True}


@pytest.mark.parametrize(
    ("exit_code", "outcome"),
    [
        (LocalCliExitCode.VALIDATION_ERROR, ChannelResponseOutcome.VALIDATION_FAILED),
        (LocalCliExitCode.NOT_FOUND, ChannelResponseOutcome.NOT_FOUND),
        (LocalCliExitCode.PERMISSION_DENIED, ChannelResponseOutcome.NOT_AUTHORISED),
        (LocalCliExitCode.CONFLICT, ChannelResponseOutcome.CONFLICT),
        (
            LocalCliExitCode.PROVIDER_UNAVAILABLE,
            ChannelResponseOutcome.TEMPORARILY_UNAVAILABLE,
        ),
        (
            LocalCliExitCode.APPLICATION_ERROR,
            ChannelResponseOutcome.APPLICATION_FAILED,
        ),
    ],
)
def test_failure_exit_codes_map_deterministically(
    exit_code: LocalCliExitCode,
    outcome: ChannelResponseOutcome,
) -> None:
    response = channel_response_from_cli_result(
        _request(),
        CliResult.failed(
            exit_code=exit_code,
            issues=(CliIssue(code="failed", message="Failed safely."),),
        ),
        clock=lambda: NOW,
        success_message="unused",
    )

    assert response.outcome is outcome
    assert response.issue is not None
    assert response.issue.code == "failed"


def test_invalid_clock_is_rejected() -> None:
    with pytest.raises(ValueError, match="must return a datetime"):
        channel_response_from_cli_result(
            _request(),
            CliResult.succeeded(),
            clock=lambda: object(),
            success_message="Done.",
        )
