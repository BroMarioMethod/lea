"""Tests for Local CLI root dispatch."""

import json
from io import StringIO

from lea.cli import LocalCliExitCode, execute_local_cli


def test_root_help_returns_success() -> None:
    """Help should be written to stdout and return zero."""
    stdout = StringIO()
    stderr = StringIO()

    exit_code = execute_local_cli(
        ["--help"],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == LocalCliExitCode.SUCCESS
    assert stdout.getvalue().startswith("usage: lea ")
    assert "status" in stdout.getvalue()
    assert "task" in stdout.getvalue()
    assert "proposal" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_missing_command_returns_usage_error() -> None:
    """A Local CLI invocation requires one command."""
    stderr = StringIO()

    exit_code = execute_local_cli(
        [],
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == LocalCliExitCode.USAGE_ERROR
    assert "usage: lea " in stderr.getvalue()


def test_recognised_command_returns_structured_placeholder() -> None:
    """Accepted unimplemented grammar should fail clearly."""
    stdout = StringIO()
    stderr = StringIO()

    exit_code = execute_local_cli(
        [
            "proposal",
            "reject",
            "11111111-1111-4111-8111-111111111111",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == LocalCliExitCode.APPLICATION_ERROR
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == (
        "The 'lea proposal reject' command is recognised but is not implemented yet.\n"
    )


def test_json_placeholder_is_one_stdout_document() -> None:
    """JSON mode should remain machine-readable for placeholder failures."""
    stdout = StringIO()
    stderr = StringIO()

    exit_code = execute_local_cli(
        [
            "--json",
            "proposal",
            "reject",
            "11111111-1111-4111-8111-111111111111",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    payload = json.loads(stdout.getvalue())

    assert exit_code == LocalCliExitCode.APPLICATION_ERROR
    assert payload["success"] is False
    assert payload["exit_code"] == 1
    assert payload["data"] == {"command": "lea proposal reject"}
    assert payload["issues"][0]["code"] == "cli_command_not_implemented"
    assert stderr.getvalue() == ""


def test_non_system_profile_requires_explicit_configuration() -> None:
    """Development and test status checks require an explicit path."""
    stdout = StringIO()
    stderr = StringIO()

    exit_code = execute_local_cli(
        ["--profile", "development", "status"],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == LocalCliExitCode.USAGE_ERROR
    assert stdout.getvalue() == ""
    assert "--config is required" in stderr.getvalue()


def test_empty_task_modification_returns_validation_error() -> None:
    """A modification with no changes should fail before provider loading."""
    stdout = StringIO()
    stderr = StringIO()

    exit_code = execute_local_cli(
        [
            "task",
            "modify",
            "11111111-1111-4111-8111-111111111111",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == LocalCliExitCode.VALIDATION_ERROR
    assert stdout.getvalue() == ""
    assert "at least one change" in stderr.getvalue()


def test_invalid_task_completion_uuid_returns_validation_error() -> None:
    """Invalid completion UUIDs should fail before provider loading."""
    stdout = StringIO()
    stderr = StringIO()

    exit_code = execute_local_cli(
        ["task", "complete", "not-a-uuid"],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == LocalCliExitCode.VALIDATION_ERROR
    assert stdout.getvalue() == ""
    assert "not canonical" in stderr.getvalue()


def test_invalid_task_deletion_uuid_returns_validation_error() -> None:
    """Invalid deletion UUIDs should fail before provider loading."""
    stdout = StringIO()
    stderr = StringIO()

    exit_code = execute_local_cli(
        ["task", "delete", "not-a-uuid"],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == LocalCliExitCode.VALIDATION_ERROR
    assert stdout.getvalue() == ""
    assert "not canonical" in stderr.getvalue()


def test_invalid_task_tag_returns_validation_error() -> None:
    """Unsupported tags should fail before provider loading."""
    stdout = StringIO()
    stderr = StringIO()

    exit_code = execute_local_cli(
        [
            "task",
            "create",
            "--description",
            "Test",
            "--tag",
            "client/work",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == LocalCliExitCode.VALIDATION_ERROR
    assert stdout.getvalue() == ""
    assert "only letters, digits and underscores" in stderr.getvalue()
