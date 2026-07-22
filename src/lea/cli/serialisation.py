"""Deterministic JSON serialisation for Local CLI contracts."""

import json
from typing import cast

from lea.cli.contracts import CliIssue, CliResult, JsonValue


def cli_issue_to_dict(issue: CliIssue) -> dict[str, JsonValue]:
    """Convert one CLI issue into deterministic JSON-compatible data."""
    result: dict[str, JsonValue] = {
        "code": issue.code,
        "message": issue.message,
    }

    if issue.field is not None:
        result["field"] = issue.field

    return result


def cli_result_to_dict(result: CliResult) -> dict[str, JsonValue]:
    """Convert one CLI result into its stable JSON envelope."""
    return {
        "data": result.data,
        "exit_code": int(result.exit_code),
        "issues": [
            cast(JsonValue, cli_issue_to_dict(issue)) for issue in result.issues
        ],
        "success": result.success,
    }


def render_cli_result_json(result: CliResult) -> str:
    """Render one result as compact, sorted, newline-terminated JSON."""
    return (
        json.dumps(
            cli_result_to_dict(result),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
