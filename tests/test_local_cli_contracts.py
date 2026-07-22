"""Tests for Local CLI contracts and exit-code compatibility."""

import pytest

from lea.cli import (
    CliIssue,
    CliResult,
    LocalCliExitCode,
    normalise_runtime_cli_exit_code,
)


def test_cli_issue_accepts_stable_values() -> None:
    """Issue contracts should preserve their supplied values."""
    issue = CliIssue(
        code="task_not_found",
        message="The requested task was not found.",
        field="uuid",
    )

    assert issue.code == "task_not_found"
    assert issue.message == "The requested task was not found."
    assert issue.field == "uuid"


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("", "Message."),
        ("   ", "Message."),
        ("code", ""),
        ("code", "   "),
    ],
)
def test_cli_issue_rejects_blank_required_values(
    code: str,
    message: str,
) -> None:
    """Issue codes and messages must not be blank."""
    with pytest.raises(ValueError):
        CliIssue(code=code, message=message)


def test_cli_issue_rejects_blank_optional_field() -> None:
    """A supplied issue field must identify a real field."""
    with pytest.raises(ValueError):
        CliIssue(
            code="invalid_value",
            message="The value is invalid.",
            field=" ",
        )


def test_success_result_uses_success_exit_code() -> None:
    """Successful helper construction should be internally consistent."""
    result = CliResult.succeeded(
        data={"status": "healthy"},
    )

    assert result.success is True
    assert result.exit_code is LocalCliExitCode.SUCCESS
    assert result.data == {"status": "healthy"}
    assert result.issues == ()


def test_failed_result_requires_an_issue() -> None:
    """A failed command must explain its failure."""
    with pytest.raises(ValueError):
        CliResult.failed(
            exit_code=LocalCliExitCode.NOT_FOUND,
            issues=(),
        )


def test_failed_result_rejects_success_exit_code() -> None:
    """Failure construction must not use status zero."""
    issue = CliIssue(
        code="task_not_found",
        message="The requested task was not found.",
    )

    with pytest.raises(ValueError):
        CliResult.failed(
            exit_code=LocalCliExitCode.SUCCESS,
            issues=(issue,),
        )


def test_direct_result_rejects_inconsistent_success_state() -> None:
    """Direct construction must preserve success and status agreement."""
    with pytest.raises(ValueError):
        CliResult(
            success=True,
            exit_code=LocalCliExitCode.APPLICATION_ERROR,
        )

    with pytest.raises(ValueError):
        CliResult(
            success=False,
            exit_code=LocalCliExitCode.SUCCESS,
        )


@pytest.mark.parametrize(
    "exit_code",
    [0, 1, 2],
)
def test_runtime_exit_code_compatibility_preserves_known_codes(
    exit_code: int,
) -> None:
    """Existing runtime CLI statuses must remain unchanged."""
    assert normalise_runtime_cli_exit_code(exit_code) == exit_code


@pytest.mark.parametrize(
    "exit_code",
    [-1, 3, 4, 69, 71],
)
def test_unknown_runtime_exit_code_becomes_internal_error(
    exit_code: int,
) -> None:
    """Unexpected runtime statuses should fail closed."""
    assert normalise_runtime_cli_exit_code(exit_code) == LocalCliExitCode.INTERNAL_ERROR
