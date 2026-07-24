"""Tests for established channel command handlers."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from lea.channels import (
    ChannelIdentity,
    ChannelName,
    ChannelRequest,
    ChannelRequestType,
    ChannelResponseOutcome,
)
from lea.channels.handlers import (
    ChannelHandlerDependencies,
    build_default_channel_application,
)
from lea.cli import CliResult
from lea.runtime import RuntimeProfile
from lea.tasks import TaskCreateRequest, TaskModifyRequest

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
REQUEST_ID = "11111111-1111-4111-8111-111111111111"
TASK_ID = "22222222-2222-4222-8222-222222222222"
PROPOSAL_ID = "33333333-3333-4333-8333-333333333333"


def _request(command: str, parameters: dict[str, object]) -> ChannelRequest:
    return ChannelRequest(
        request_id=REQUEST_ID,
        source_update_id="telegram:42",
        identity=ChannelIdentity(
            channel=ChannelName.TELEGRAM,
            user_id="123456789",
            conversation_id="123456789",
            role="owner",
            display_name="Owner",
            capabilities=(
                "Runtime.Status.Read",
                "Tasks.Read",
                "Tasks.Write",
                "Tasks.Delete",
                "Proposals.Read",
                "Proposals.Confirm",
                "Proposals.Execute.LowRisk",
            ),
        ),
        request_type=ChannelRequestType.COMMAND,
        command=command,
        parameters=parameters,
        received_at=NOW,
    )


def _dependencies(
    tmp_path: Path,
    calls: list[tuple[str, dict[str, object]]],
) -> ChannelHandlerDependencies:
    def executor(name: str) -> Callable[..., CliResult]:
        def run(**kwargs: object) -> CliResult:
            calls.append((name, dict(kwargs)))
            return CliResult.succeeded(data={"command": name})

        return run

    return ChannelHandlerDependencies(
        config_path=(tmp_path / "lea.toml").resolve(),
        expected_profile=RuntimeProfile.TEST,
        clock=lambda: NOW,
        status_executor=executor("status"),
        task_list_executor=executor("tasks.list"),
        task_create_executor=executor("tasks.create"),
        task_modify_executor=executor("tasks.modify"),
        task_complete_executor=executor("tasks.complete"),
        task_delete_executor=executor("tasks.delete"),
        proposal_list_executor=executor("proposals.list"),
        proposal_show_executor=executor("proposals.show"),
        proposal_approve_executor=executor("proposals.approve"),
        proposal_reject_executor=executor("proposals.reject"),
        proposal_cancel_executor=executor("proposals.cancel"),
        proposal_execute_executor=executor("proposals.execute"),
    )


def test_runtime_status_calls_reusable_service(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    result = build_default_channel_application(_dependencies(tmp_path, calls)).handle(
        _request("runtime.status", {"arguments": []})
    )

    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.SUCCEEDED
    assert calls[0][0] == "status"


def test_task_create_joins_telegram_arguments(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    application = build_default_channel_application(_dependencies(tmp_path, calls))

    result = application.handle(
        _request(
            "tasks.create",
            {"arguments": ["Write", "Slice", "12"], "telegram_message_id": 9},
        )
    )

    assert result.response is not None
    request = cast(TaskCreateRequest, calls[0][1]["request"])
    assert request.description == "Write Slice 12"


def test_task_modify_uses_uuid_and_description_arguments(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    application = build_default_channel_application(_dependencies(tmp_path, calls))

    result = application.handle(
        _request("tasks.modify", {"arguments": [TASK_ID, "Updated", "task"]})
    )

    assert result.response is not None
    request = cast(TaskModifyRequest, calls[0][1]["request"])
    assert request.task_uuid == TASK_ID
    assert request.description == "Updated task"


def test_proposal_actor_is_derived_from_identity(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    application = build_default_channel_application(_dependencies(tmp_path, calls))

    result = application.handle(
        _request(
            "proposals.reject",
            {"arguments": [PROPOSAL_ID, "Needs", "revision"]},
        )
    )

    assert result.response is not None
    assert calls[0][1]["actor"] == "telegram:123456789"
    assert calls[0][1]["reason"] == "Needs revision"


def test_callback_parameters_are_supported(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    application = build_default_channel_application(_dependencies(tmp_path, calls))

    result = application.handle(
        _request(
            "proposals.approve",
            {
                "proposal_id": PROPOSAL_ID,
                "callback_query_id": "callback-1",
                "telegram_message_id": 7,
            },
        )
    )

    assert result.response is not None
    assert calls[0][1]["proposal_id"] == PROPOSAL_ID


def test_unknown_parameter_fails_before_service_call(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    application = build_default_channel_application(_dependencies(tmp_path, calls))

    result = application.handle(
        _request("tasks.create", {"arguments": ["Task"], "unexpected": True})
    )

    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.VALIDATION_FAILED
    assert calls == []


def test_deferred_command_remains_not_found(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    application = build_default_channel_application(_dependencies(tmp_path, calls))

    result = application.handle(_request("knowledge.find", {"arguments": ["steam"]}))

    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.NOT_FOUND
    assert calls == []
