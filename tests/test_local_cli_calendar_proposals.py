"""Tests for Local CLI calendar proposal submission."""

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest

from lea.actions import ConfirmationPolicy
from lea.cli import LocalCliExitCode, execute_local_cli
from lea.cli.calendar_proposal_commands import CalendarProposalCommandDependencies
from lea.proposals import MarkdownProposalRepository
from lea.runtime import ConfigurationResult, isolated_test_runtime_config

PROPOSAL_ID = "11111111-1111-4111-8111-111111111111"
CREATED_AT = datetime(2026, 8, 4, 10, tzinfo=UTC)


def _dependencies(
    tmp_path: Path,
) -> tuple[CalendarProposalCommandDependencies, MarkdownProposalRepository]:
    config = isolated_test_runtime_config(tmp_path / "runtime")
    config.paths.proposal_dir.mkdir(parents=True)
    repository = MarkdownProposalRepository(config.paths.proposal_dir)
    return (
        CalendarProposalCommandDependencies(
            load_configuration=lambda _path: ConfigurationResult(True, config, ()),
            create_repository=lambda _config: repository,
            proposal_id_source=lambda: PROPOSAL_ID,
            clock=lambda: CREATED_AT,
        ),
        repository,
    )


@pytest.mark.parametrize(
    ("arguments", "expected_action"),
    [
        (
            [
                "calendar",
                "create",
                "personal",
                "--summary",
                "Review milestone",
                "--start",
                "2026-08-04T08:00:00+02:00",
                "--end",
                "2026-08-04T09:00:00+02:00",
                "--timezone",
                "Africa/Gaborone",
            ],
            "calendar.create",
        ),
        (
            [
                "calendar",
                "modify",
                "personal",
                "event-1",
                "--summary",
                "Updated",
            ],
            "calendar.modify",
        ),
        (["calendar", "cancel", "personal", "event-1"], "calendar.cancel"),
        (["calendar", "sync"], "calendar.sync"),
    ],
)
def test_calendar_commands_persist_always_confirm_proposals_without_provider_access(
    tmp_path: Path,
    arguments: list[str],
    expected_action: str,
) -> None:
    dependencies, repository = _dependencies(tmp_path)
    stdout = StringIO()

    exit_code = execute_local_cli(
        ["--config", str(tmp_path / "lea.toml"), *arguments],
        stdout=stdout,
        stderr=StringIO(),
        calendar_proposal_dependencies=dependencies,
    )

    assert exit_code == LocalCliExitCode.SUCCESS
    written = repository.read(PROPOSAL_ID)
    assert written.success is True
    assert written.proposal is not None
    assert written.proposal.action == expected_action
    assert written.proposal.source == "cli:local"
    assert written.proposal.confirmation_policy is ConfirmationPolicy.ALWAYS
    assert "Approval and explicit execution are required." in stdout.getvalue()


def test_calendar_create_rejects_naive_datetime_before_configuration_access() -> None:
    exit_code = execute_local_cli(
        [
            "calendar",
            "create",
            "personal",
            "--summary",
            "Unsafe time",
            "--start",
            "2026-08-04T08:00:00",
            "--end",
            "2026-08-04T09:00:00",
            "--timezone",
            "Africa/Gaborone",
        ],
        stdout=StringIO(),
        stderr=StringIO(),
        calendar_proposal_dependencies=CalendarProposalCommandDependencies(
            load_configuration=lambda _path: pytest.fail(
                "configuration must not be loaded"
            )
        ),
    )

    assert exit_code == LocalCliExitCode.VALIDATION_ERROR
