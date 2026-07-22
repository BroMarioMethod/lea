"""Tests for Local CLI output stream handling."""

from io import StringIO

from lea.cli import (
    CliIssue,
    CliResult,
    LocalCliExitCode,
    write_cli_result,
)


def render_human_result(result: CliResult) -> str:
    """Render one predictable human-readable test value."""
    if result.success:
        return "Command completed."

    return result.issues[0].message


def test_human_success_is_written_to_stdout() -> None:
    """Successful human output belongs on standard output."""
    stdout = StringIO()
    stderr = StringIO()

    exit_code = write_cli_result(
        CliResult.succeeded(),
        stdout=stdout,
        stderr=stderr,
        json_output=False,
        human_renderer=render_human_result,
    )

    assert exit_code == LocalCliExitCode.SUCCESS
    assert stdout.getvalue() == "Command completed.\n"
    assert stderr.getvalue() == ""


def test_human_failure_is_written_to_stderr() -> None:
    """Failed human output belongs on standard error."""
    stdout = StringIO()
    stderr = StringIO()
    result = CliResult.failed(
        exit_code=LocalCliExitCode.NOT_FOUND,
        issues=(
            CliIssue(
                code="task_not_found",
                message="The requested task was not found.",
            ),
        ),
    )

    exit_code = write_cli_result(
        result,
        stdout=stdout,
        stderr=stderr,
        json_output=False,
        human_renderer=render_human_result,
    )

    assert exit_code == LocalCliExitCode.NOT_FOUND
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "The requested task was not found.\n"


def test_human_output_normalises_trailing_newlines() -> None:
    """Human renderers should not create variable blank lines."""
    stdout = StringIO()

    exit_code = write_cli_result(
        CliResult.succeeded(),
        stdout=stdout,
        stderr=StringIO(),
        json_output=False,
        human_renderer=lambda result: "Done.\n\n",
    )

    assert exit_code == LocalCliExitCode.SUCCESS
    assert stdout.getvalue() == "Done.\n"


def test_json_success_is_written_only_to_stdout() -> None:
    """JSON mode must produce exactly one stdout document."""
    stdout = StringIO()
    stderr = StringIO()

    exit_code = write_cli_result(
        CliResult.succeeded(data={"count": 0}),
        stdout=stdout,
        stderr=stderr,
        json_output=True,
        human_renderer=render_human_result,
    )

    assert exit_code == LocalCliExitCode.SUCCESS
    assert stdout.getvalue() == (
        '{"data":{"count":0},"exit_code":0,"issues":[],"success":true}\n'
    )
    assert stderr.getvalue() == ""


def test_json_failure_is_written_only_to_stdout() -> None:
    """Failed JSON results remain one machine-readable stdout document."""
    stdout = StringIO()
    stderr = StringIO()
    result = CliResult.failed(
        exit_code=LocalCliExitCode.PROVIDER_UNAVAILABLE,
        issues=(
            CliIssue(
                code="provider_unavailable",
                message="The task provider is unavailable.",
            ),
        ),
    )

    exit_code = write_cli_result(
        result,
        stdout=stdout,
        stderr=stderr,
        json_output=True,
        human_renderer=render_human_result,
    )

    assert exit_code == LocalCliExitCode.PROVIDER_UNAVAILABLE
    assert '"exit_code":8' in stdout.getvalue()
    assert '"success":false' in stdout.getvalue()
    assert stderr.getvalue() == ""
