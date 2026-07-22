"""Tests for the root Local CLI parser."""

from pathlib import Path

import pytest

from lea.cli import create_local_cli_parser


def test_root_parser_uses_public_program_name() -> None:
    """Root help should identify the installed command."""
    assert create_local_cli_parser().prog == "lea"


@pytest.mark.parametrize(
    ("arguments", "command", "nested_command"),
    [
        (["status"], "status", None),
        (["task", "list"], "task", "list"),
        (["task", "create", "--description", "Inspect boiler"], "task", "create"),
        (["task", "modify", "00000000-0000-0000-0000-000000000001"], "task", "modify"),
        (
            ["task", "complete", "00000000-0000-0000-0000-000000000001"],
            "task",
            "complete",
        ),
        (["task", "delete", "00000000-0000-0000-0000-000000000001"], "task", "delete"),
        (["proposal", "list"], "proposal", "list"),
        (["proposal", "show", "proposal-1"], "proposal", "show"),
        (["proposal", "approve", "proposal-1"], "proposal", "approve"),
        (["proposal", "reject", "proposal-1"], "proposal", "reject"),
    ],
)
def test_parser_accepts_initial_command_grammar(
    arguments: list[str], command: str, nested_command: str | None
) -> None:
    """Every accepted Milestone 2.3 command should parse."""
    namespace = create_local_cli_parser().parse_args(arguments)
    assert namespace.command == command
    if nested_command is not None:
        assert getattr(namespace, f"{command}_command") == nested_command


def test_parser_preserves_global_json_option() -> None:
    """JSON mode should be available before the command."""
    namespace = create_local_cli_parser().parse_args(["--json", "task", "list"])
    assert namespace.json is True
    assert namespace.no_colour is False


def test_parser_preserves_rejection_reason() -> None:
    """Proposal rejection should preserve an optional reason."""
    namespace = create_local_cli_parser().parse_args(
        [
            "proposal",
            "reject",
            "proposal-1",
            "--reason",
            "The action is no longer required.",
        ]
    )
    assert namespace.reason == "The action is no longer required."


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["task"],
        ["proposal"],
        ["task", "create"],
        ["task", "modify"],
        ["proposal", "show"],
    ],
)
def test_parser_rejects_incomplete_commands(arguments: list[str]) -> None:
    """Incomplete command paths should be usage errors."""
    with pytest.raises(SystemExit) as error:
        create_local_cli_parser().parse_args(arguments)
    assert error.value.code == 2


def test_parser_accepts_explicit_runtime_selection() -> None:
    """Global runtime selection should remain explicit and deterministic."""
    parser = create_local_cli_parser()
    namespace = parser.parse_args(
        [
            "--config",
            "/srv/lea/config/lea.toml",
            "--profile",
            "development",
            "status",
        ]
    )

    assert namespace.config == Path("/srv/lea/config/lea.toml")
    assert namespace.profile == "development"


def test_parser_rejects_relative_configuration_path() -> None:
    """Local CLI configuration paths must be absolute."""
    with pytest.raises(SystemExit) as error:
        create_local_cli_parser().parse_args(
            ["--config", "relative/lea.toml", "status"]
        )

    assert error.value.code == 2


def test_parser_preserves_task_list_filters() -> None:
    """Supported task-list filters should parse deterministically."""
    namespace = create_local_cli_parser().parse_args(
        [
            "task",
            "list",
            "--uuid",
            "11111111-1111-4111-8111-111111111111",
            "--status",
            "completed",
            "--project",
            "lea",
            "--tag",
            "cli",
        ]
    )

    assert namespace.uuid == "11111111-1111-4111-8111-111111111111"
    assert namespace.status == "completed"
    assert namespace.project == "lea"
    assert namespace.tag == "cli"


def test_parser_preserves_task_create_fields() -> None:
    """Supported task-creation fields should parse deterministically."""
    namespace = create_local_cli_parser().parse_args(
        [
            "task",
            "create",
            "--description",
            "Create CLI task",
            "--project",
            "lea",
            "--priority",
            "H",
            "--tag",
            "create",
            "--tag",
            "cli",
        ]
    )

    assert namespace.description == "Create CLI task"
    assert namespace.project == "lea"
    assert namespace.priority == "H"
    assert namespace.tag == ["create", "cli"]
