"""Tests for established channel command handlers."""

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from lea.actions import (
    ActionHandlerRegistry,
    ActionProposal,
    ActionStatus,
    ConfirmationPolicy,
    RiskLevel,
    proposal_to_dict,
)
from lea.audit import JsonlAuditStore, generate_event_id
from lea.channels import (
    ChannelCapability,
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
from lea.cli.contracts import JsonValue
from lea.orchestration import ActionOrchestrator
from lea.proposals import (
    MarkdownProposalRepository,
    ProposalSubmissionResult,
    ProposalSubmissionService,
)
from lea.runtime import RuntimeProfile
from lea.tasks import TaskListQuery

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
REQUEST_ID = "11111111-1111-4111-8111-111111111111"
TASK_ID = "22222222-2222-4222-8222-222222222222"
PROPOSAL_ID = "33333333-3333-4333-8333-333333333333"


DEFAULT_CAPABILITIES = (
    "Runtime.Status.Read",
    "Tasks.Read",
    "Tasks.Write",
    "Tasks.Delete",
    "Proposals.Read",
    "Proposals.Confirm",
    "Proposals.Execute.LowRisk",
)


def _request(
    command: str,
    parameters: dict[str, object],
    *,
    capabilities: tuple[str, ...] = DEFAULT_CAPABILITIES,
) -> ChannelRequest:
    return ChannelRequest(
        request_id=REQUEST_ID,
        source_update_id="telegram:42",
        identity=ChannelIdentity(
            channel=ChannelName.TELEGRAM,
            user_id="123456789",
            conversation_id="123456789",
            role="owner",
            display_name="Owner",
            capabilities=capabilities,
        ),
        request_type=ChannelRequestType.COMMAND,
        command=command,
        parameters=parameters,
        received_at=NOW,
    )


def _dependencies(
    tmp_path: Path,
    calls: list[tuple[str, dict[str, object]]],
    submitted: list[ActionProposal] | None = None,
) -> ChannelHandlerDependencies:
    def executor(name: str) -> Callable[..., CliResult]:
        def run(**kwargs: object) -> CliResult:
            calls.append((name, dict(kwargs)))
            return CliResult.succeeded(data={"command": name})

        return run

    proposal_root = tmp_path / "proposals"
    proposal_root.mkdir()
    service = ProposalSubmissionService(
        ActionOrchestrator(
            ActionHandlerRegistry(),
            JsonlAuditStore(tmp_path / "audit.jsonl"),
            lambda: NOW,
            generate_event_id,
        ),
        MarkdownProposalRepository(proposal_root),
    )

    def submit(
        proposal: ActionProposal,
    ) -> ProposalSubmissionResult:
        if submitted is not None:
            submitted.append(proposal)
        return service.submit(proposal)

    return ChannelHandlerDependencies(
        config_path=(tmp_path / "lea.toml").resolve(),
        expected_profile=RuntimeProfile.TEST,
        clock=lambda: NOW,
        proposal_submitter=submit,
        proposal_id_source=lambda: PROPOSAL_ID,
        control_id_source=lambda: str(uuid4()),
        status_executor=executor("status"),
        task_list_executor=executor("tasks.list"),
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


def test_task_create_submits_without_direct_execution(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    submitted: list[ActionProposal] = []
    application = build_default_channel_application(
        _dependencies(tmp_path, calls, submitted)
    )

    result = application.handle(
        _request(
            "tasks.create",
            {"arguments": ["Write", "Slice", "12"], "telegram_message_id": 9},
        )
    )

    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.SUCCEEDED
    assert result.response.message == "Proposal awaiting confirmation."
    assert tuple(control.action for control in result.response.controls) == (
        "proposal.approve",
        "proposal.reject",
        "proposal.cancel",
    )
    assert calls == []
    assert len(submitted) == 1
    assert submitted[0].action == "task.create"
    assert submitted[0].risk_level is RiskLevel.LOW
    assert submitted[0].confirmation_policy is ConfirmationPolicy.ALWAYS
    assert submitted[0].source == "telegram:owner"
    assert submitted[0].parameters["description"] == "Write Slice 12"


def test_task_modify_submits_confirmation_required_proposal(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    submitted: list[ActionProposal] = []
    application = build_default_channel_application(
        _dependencies(tmp_path, calls, submitted)
    )

    result = application.handle(
        _request("tasks.modify", {"arguments": [TASK_ID, "Updated", "task"]})
    )

    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.SUCCEEDED
    assert result.response.message == "Proposal awaiting confirmation."
    assert tuple(control.action for control in result.response.controls) == (
        "proposal.approve",
        "proposal.reject",
        "proposal.cancel",
    )
    assert calls == []
    assert len(submitted) == 1
    assert submitted[0].action == "task.modify"
    assert submitted[0].risk_level is RiskLevel.MEDIUM
    assert submitted[0].parameters["uuid"] == TASK_ID
    assert submitted[0].parameters["description"] == "Updated task"


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


@pytest.mark.parametrize(
    ("command", "action", "risk"),
    [
        ("tasks.complete", "task.complete", RiskLevel.MEDIUM),
        ("tasks.delete", "task.delete", RiskLevel.HIGH),
    ],
)
def test_exact_task_mutations_submit_without_provider_execution(
    tmp_path: Path,
    command: str,
    action: str,
    risk: RiskLevel,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    submitted: list[ActionProposal] = []
    application = build_default_channel_application(
        _dependencies(tmp_path, calls, submitted)
    )

    result = application.handle(_request(command, {"arguments": [TASK_ID]}))

    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.SUCCEEDED
    assert result.response.message == "Proposal awaiting confirmation."
    assert calls == []
    assert len(submitted) == 1
    assert submitted[0].action == action
    assert submitted[0].risk_level is risk
    assert submitted[0].parameters["uuid"] == TASK_ID


def _execution_dependencies(
    tmp_path: Path,
    calls: list[tuple[str, dict[str, object]]],
    *,
    risk_level: RiskLevel,
) -> ChannelHandlerDependencies:
    proposal = ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={"description": "Execute through channel"},
        status=ActionStatus.APPROVED,
        risk_level=risk_level,
        source="telegram:owner",
        created_at=NOW,
    )

    def show(**kwargs: object) -> CliResult:
        calls.append(("proposals.show", dict(kwargs)))
        return CliResult.succeeded(
            data=cast(
                JsonValue,
                {"proposal": proposal_to_dict(proposal)},
            )
        )

    def execute(**kwargs: object) -> CliResult:
        calls.append(("proposals.execute", dict(kwargs)))
        return CliResult.succeeded(data={"executed": True})

    return replace(
        _dependencies(tmp_path, calls),
        proposal_show_executor=show,
        proposal_execute_executor=execute,
    )


@pytest.mark.parametrize(
    ("risk_level", "capability"),
    [
        (
            RiskLevel.LOW,
            "Proposals.Execute.LowRisk",
        ),
        (
            RiskLevel.MEDIUM,
            "Proposals.Execute.MediumRisk",
        ),
        (
            RiskLevel.HIGH,
            "Proposals.Execute.HighRisk",
        ),
    ],
)
def test_proposal_execution_requires_exact_risk_capability(
    tmp_path: Path,
    risk_level: RiskLevel,
    capability: str,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    application = build_default_channel_application(
        _execution_dependencies(
            tmp_path,
            calls,
            risk_level=risk_level,
        )
    )

    first = application.handle(
        _request(
            "proposals.execute",
            {"arguments": [PROPOSAL_ID]},
            capabilities=(
                "Proposals.Read",
                "Proposals.Execute.LowRisk",
            ),
        )
    )

    if risk_level is RiskLevel.LOW:
        assert first.response is not None
        assert first.response.outcome is ChannelResponseOutcome.SUCCEEDED
        assert [name for name, _ in calls] == [
            "proposals.show",
            "proposals.execute",
        ]
    else:
        assert first.response is not None
        assert first.response.outcome is ChannelResponseOutcome.NOT_AUTHORISED
        assert first.response.issue is not None
        assert first.response.issue.code == ("proposal_execution_capability_required")
        assert [name for name, _ in calls] == ["proposals.show"]

    calls.clear()
    authorised = application.handle(
        _request(
            "proposals.execute",
            {"arguments": [PROPOSAL_ID]},
            capabilities=("Proposals.Read", capability),
        )
    )

    assert authorised.response is not None
    assert authorised.response.outcome is ChannelResponseOutcome.SUCCEEDED
    assert [name for name, _ in calls] == [
        "proposals.show",
        "proposals.execute",
    ]


def test_critical_proposal_execution_fails_before_executor(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    application = build_default_channel_application(
        _execution_dependencies(
            tmp_path,
            calls,
            risk_level=RiskLevel.CRITICAL,
        )
    )

    result = application.handle(
        _request(
            "proposals.execute",
            {"arguments": [PROPOSAL_ID]},
            capabilities=tuple(capability.value for capability in ChannelCapability),
        )
    )

    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.NOT_AUTHORISED
    assert result.response.issue is not None
    assert result.response.issue.code == ("proposal_execution_risk_unsupported")
    assert [name for name, _ in calls] == ["proposals.show"]


@pytest.mark.parametrize(
    ("command", "message"),
    [
        (
            "system.start",
            "LEA is ready. Use /help to review the supported commands.",
        ),
        (
            "system.help",
            "Supported commands.",
        ),
    ],
)
def test_system_commands_report_only_supported_commands(
    tmp_path: Path,
    command: str,
    message: str,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    application = build_default_channel_application(_dependencies(tmp_path, calls))

    result = application.handle(_request(command, {"arguments": []}))

    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.SUCCEEDED
    assert result.response.message == message
    assert result.response.data is not None
    commands = result.response.data["commands"]
    assert isinstance(commands, tuple)
    assert commands == (
        "/start",
        "/help",
        "/status",
        "/tasks",
        "/task_add <description>",
        "/task_show <task-uuid>",
        "/task_modify <task-uuid> <description>",
        "/task_complete <task-uuid>",
        "/task_delete <task-uuid>",
        "/proposals",
        "/proposal_show <proposal-id>",
        "/proposal_approve <proposal-id>",
        "/proposal_reject <proposal-id> [reason]",
        "/proposal_cancel <proposal-id> [reason]",
        "/proposal_execute <proposal-id>",
    )
    assert "/proposal_revise" not in commands
    assert "/knowledge_show" not in commands
    assert calls == []


def test_task_show_reads_exact_uuid_without_status_filter(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    queries: list[TaskListQuery] = []

    def task_list(**kwargs: object) -> CliResult:
        query = cast(TaskListQuery, kwargs["query"])
        queries.append(query)
        return CliResult.succeeded(
            data={
                "tasks": [
                    {
                        "uuid": TASK_ID,
                        "description": "Completed Telegram task",
                        "status": "completed",
                        "entry": NOW.isoformat(),
                        "modified": NOW.isoformat(),
                        "due": None,
                        "project": "lea",
                        "tags": [],
                        "priority": None,
                    }
                ]
            }
        )

    dependencies = replace(
        _dependencies(tmp_path, calls),
        task_list_executor=task_list,
    )
    result = build_default_channel_application(dependencies).handle(
        _request("tasks.show", {"arguments": [TASK_ID]})
    )

    assert result.response is not None
    assert result.response.outcome is ChannelResponseOutcome.SUCCEEDED
    assert result.response.message == "Task loaded."
    assert queries == [
        TaskListQuery(
            uuid=TASK_ID,
            status=None,
        )
    ]
    assert result.response.data is not None
    task = result.response.data["task"]
    assert isinstance(task, Mapping)
    assert task["uuid"] == TASK_ID
    assert task["status"] == "completed"
    assert calls == []


@pytest.mark.parametrize(
    ("tasks", "outcome", "issue_code"),
    [
        (
            [],
            ChannelResponseOutcome.NOT_FOUND,
            "task_not_found",
        ),
        (
            [
                {"uuid": TASK_ID},
                {"uuid": TASK_ID},
            ],
            ChannelResponseOutcome.APPLICATION_FAILED,
            "task_lookup_ambiguous",
        ),
    ],
)
def test_task_show_rejects_missing_or_ambiguous_results(
    tmp_path: Path,
    tasks: list[JsonValue],
    outcome: ChannelResponseOutcome,
    issue_code: str,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def task_list(**kwargs: object) -> CliResult:
        del kwargs
        return CliResult.succeeded(data={"tasks": tasks})

    dependencies = replace(
        _dependencies(tmp_path, calls),
        task_list_executor=task_list,
    )
    result = build_default_channel_application(dependencies).handle(
        _request("tasks.show", {"arguments": [TASK_ID]})
    )

    assert result.response is not None
    assert result.response.outcome is outcome
    assert result.response.issue is not None
    assert result.response.issue.code == issue_code
    assert calls == []
