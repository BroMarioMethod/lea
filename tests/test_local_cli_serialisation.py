"""Tests for deterministic Local CLI JSON serialisation."""

import json

import pytest

from lea.cli import (
    CliIssue,
    CliResult,
    LocalCliExitCode,
    cli_issue_to_dict,
    cli_result_to_dict,
    render_cli_result_json,
)


def test_issue_serialisation_omits_missing_field() -> None:
    """Optional issue fields should not become JSON null values."""
    issue = CliIssue(
        code="provider_unavailable",
        message="The task provider is unavailable.",
    )

    assert cli_issue_to_dict(issue) == {
        "code": "provider_unavailable",
        "message": "The task provider is unavailable.",
    }


def test_result_serialisation_uses_stable_envelope() -> None:
    """Result data should use the documented top-level envelope."""
    issue = CliIssue(
        code="task_not_found",
        message="The requested task was not found.",
        field="uuid",
    )
    result = CliResult.failed(
        exit_code=LocalCliExitCode.NOT_FOUND,
        issues=(issue,),
    )

    assert cli_result_to_dict(result) == {
        "data": None,
        "exit_code": 4,
        "issues": [
            {
                "code": "task_not_found",
                "field": "uuid",
                "message": "The requested task was not found.",
            }
        ],
        "success": False,
    }


def test_json_rendering_is_compact_sorted_and_newline_terminated() -> None:
    """Machine-readable output should be deterministic."""
    result = CliResult.succeeded(
        data={
            "version": "3.4.2",
            "healthy": True,
        },
    )

    rendered = render_cli_result_json(result)

    assert rendered == (
        '{"data":{"healthy":true,"version":"3.4.2"},'
        '"exit_code":0,"issues":[],"success":true}\n'
    )
    assert json.loads(rendered)["success"] is True


def test_json_rendering_preserves_utf8() -> None:
    """JSON output should not escape ordinary Unicode text."""
    result = CliResult.succeeded(
        data={"description": "Café"},
    )

    assert '"Café"' in render_cli_result_json(result)


def test_json_rendering_rejects_non_finite_numbers() -> None:
    """JSON output must reject values outside standard JSON."""
    result = CliResult.succeeded(
        data={"value": float("nan")},
    )

    with pytest.raises(ValueError):
        render_cli_result_json(result)
