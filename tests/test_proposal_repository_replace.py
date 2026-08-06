"""Tests for atomic persistent proposal replacement."""

import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lea.actions import ActionProposal, ActionStatus
from lea.proposals import MarkdownProposalRepository

PROPOSAL_ID = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"


def create_proposal(
    *,
    status: ActionStatus,
) -> ActionProposal:
    """Return one deterministic proposal at the requested status."""
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={
            "description": "Test task",
            "priority": 2,
        },
        status=status,
        source="user",
        created_at=datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
        reason="Create a test task.",
    )


def create_repository(
    tmp_path: Path,
) -> MarkdownProposalRepository:
    """Create one repository with an existing root."""
    root = tmp_path / "proposals"
    root.mkdir()
    return MarkdownProposalRepository(root)


def test_replace_updates_existing_canonical_document(
    tmp_path: Path,
) -> None:
    repository = create_repository(tmp_path)
    existing = create_proposal(status=ActionStatus.AWAITING_CONFIRMATION)
    replacement = create_proposal(status=ActionStatus.APPROVED)

    assert repository.create(existing).success is True

    result = repository.replace(
        replacement,
        expected_status=ActionStatus.AWAITING_CONFIRMATION,
    )

    assert result.success is True
    assert result.previous_proposal == existing
    assert result.proposal == replacement
    assert repository.read(PROPOSAL_ID).proposal == replacement


def test_replace_rejects_missing_proposal(
    tmp_path: Path,
) -> None:
    repository = create_repository(tmp_path)

    result = repository.replace(
        create_proposal(status=ActionStatus.APPROVED),
        expected_status=ActionStatus.AWAITING_CONFIRMATION,
    )

    assert result.success is False
    assert result.issues[0].code == "proposal_not_found"


def test_replace_rejects_stale_expected_status(
    tmp_path: Path,
) -> None:
    repository = create_repository(tmp_path)
    existing = create_proposal(status=ActionStatus.APPROVED)

    assert repository.create(existing).success is True

    result = repository.replace(
        create_proposal(status=ActionStatus.REJECTED),
        expected_status=ActionStatus.AWAITING_CONFIRMATION,
    )

    assert result.success is False
    assert result.issues[0].code == "proposal_status_conflict"
    assert repository.read(PROPOSAL_ID).proposal == existing


def test_replace_leaves_no_temporary_files(
    tmp_path: Path,
) -> None:
    repository = create_repository(tmp_path)
    existing = create_proposal(status=ActionStatus.AWAITING_CONFIRMATION)

    assert repository.create(existing).success is True

    result = repository.replace(
        create_proposal(status=ActionStatus.APPROVED),
        expected_status=ActionStatus.AWAITING_CONFIRMATION,
    )

    assert result.success is True
    assert tuple(repository.root.glob("*.tmp")) == ()
    assert tuple(repository.root.glob(".*.tmp")) == ()


def test_replace_failure_preserves_existing_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = create_repository(tmp_path)
    existing = create_proposal(status=ActionStatus.AWAITING_CONFIRMATION)

    assert repository.create(existing).success is True

    def fail_replace(source: object, destination: object) -> None:
        raise OSError("Simulated replacement failure.")

    monkeypatch.setattr("lea.proposals.repository.os.replace", fail_replace)

    result = repository.replace(
        create_proposal(status=ActionStatus.APPROVED),
        expected_status=ActionStatus.AWAITING_CONFIRMATION,
    )

    assert result.success is False
    assert result.issues[0].code == "proposal_replace_failed"
    assert repository.read(PROPOSAL_ID).proposal == existing
    assert tuple(repository.root.glob(".*.tmp")) == ()


def test_replace_with_fsync_succeeds(
    tmp_path: Path,
) -> None:
    root = tmp_path / "proposals"
    root.mkdir()
    repository = MarkdownProposalRepository(root, fsync=True)
    existing = create_proposal(status=ActionStatus.AWAITING_CONFIRMATION)

    assert repository.create(existing).success is True

    result = repository.replace(
        create_proposal(status=ActionStatus.APPROVED),
        expected_status=ActionStatus.AWAITING_CONFIRMATION,
    )

    assert result.success is True


def test_replaced_proposal_preserves_group_readable_mode(
    tmp_path: Path,
) -> None:
    root = tmp_path / "proposals"
    root.mkdir()
    repository = MarkdownProposalRepository(root)
    existing = create_proposal(
        status=ActionStatus.AWAITING_CONFIRMATION,
    )

    assert repository.create(existing).success is True

    result = repository.replace(
        create_proposal(status=ActionStatus.APPROVED),
        expected_status=ActionStatus.AWAITING_CONFIRMATION,
    )

    assert result.success is True
    assert result.path is not None
    assert stat.S_IMODE(result.path.stat().st_mode) == 0o640
