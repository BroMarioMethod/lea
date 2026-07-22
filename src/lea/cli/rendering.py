"""Output-stream boundaries for Local CLI results."""

from collections.abc import Callable
from typing import TextIO

from lea.cli.contracts import CliResult
from lea.cli.serialisation import render_cli_result_json

HumanResultRenderer = Callable[[CliResult], str]


def write_cli_result(
    result: CliResult,
    *,
    stdout: TextIO,
    stderr: TextIO,
    json_output: bool,
    human_renderer: HumanResultRenderer,
) -> int:
    """Write one CLI result and return its stable process exit status."""
    if json_output:
        stdout.write(render_cli_result_json(result))
        return int(result.exit_code)

    rendered = _ensure_trailing_newline(human_renderer(result))

    if result.success:
        stdout.write(rendered)
    else:
        stderr.write(rendered)

    return int(result.exit_code)


def _ensure_trailing_newline(value: str) -> str:
    """Return human-readable output ending in exactly one newline."""
    return value.rstrip("\n") + "\n"
