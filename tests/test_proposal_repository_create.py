"""Tests for atomic persistent proposal creation."""

import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lea.actions import ActionProposal
from lea.proposals import (
    MarkdownProposalRepository,
    parse_proposal_document,
    render_proposal_document,
)

PROPOSAL_ID = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"


def create_proposal(
    *,
    proposal_id: str = PROPOSAL_ID,
) -> ActionProposal:
    """Return one deterministic proposal."""
    return ActionProposal(
        proposal_id=proposal_id,
        action="task.create",
        parameters={
            "description": "Test task",
            "priority": 2,
        },
        source="user",
        created_at=datetime(
            2026,
            7,
            21,
            12,
            0,
            tzinfo=UTC,
        ),
        reason="Create a test task.",
    )


def test_repository_requires_absolute_root() -> None:
    """Repository location must not depend on the working directory."""
    with pytest.raises(
        ValueError,
        match="root must be an absolute path",
    ):
        MarkdownProposalRepository(
            Path("proposals"),
        )


def test_repository_rejects_non_path_root() -> None:
    """Repository roots must use pathlib values."""
    with pytest.raises(
        TypeError,
        match=r"root must be a pathlib\.Path",
    ):
        MarkdownProposalRepository(
            "/var/lib/lea/proposals",  # type: ignore[arg-type]
        )


def test_repository_exposes_configured_root(
    tmp_path: Path,
) -> None:
    """The explicit repository root should remain inspectable."""
    root = tmp_path / "proposals"
    repository = MarkdownProposalRepository(root)

    assert repository.root == root


def test_path_for_uses_canonical_filename(
    tmp_path: Path,
) -> None:
    """Proposal identifiers should determine canonical filenames."""
    root = tmp_path / "proposals"
    repository = MarkdownProposalRepository(root)

    assert repository.path_for(PROPOSAL_ID) == (root / f"{PROPOSAL_ID}.md")


@pytest.mark.parametrize(
    "proposal_id",
    [
        "not-a-uuid",
        f"../{PROPOSAL_ID}",
        PROPOSAL_ID.upper(),
        f"{PROPOSAL_ID}.md",
    ],
)
def test_path_for_rejects_non_canonical_identifier(
    tmp_path: Path,
    proposal_id: str,
) -> None:
    """Unchecked caller input must never become a path."""
    repository = MarkdownProposalRepository(tmp_path / "proposals")

    with pytest.raises(
        ValueError,
        match="proposal_id",
    ):
        repository.path_for(proposal_id)


def test_missing_repository_directory_fails_by_default(
    tmp_path: Path,
) -> None:
    """Creation must not create parents unless explicitly allowed."""
    root = tmp_path / "proposals"
    repository = MarkdownProposalRepository(root)

    result = repository.create(create_proposal())

    assert result.success is False
    assert result.proposal is None
    assert result.issues[0].code == "proposal_directory_missing"
    assert root.exists() is False


def test_explicit_parent_creation(
    tmp_path: Path,
) -> None:
    """Repository creation may be enabled explicitly."""
    root = tmp_path / "runtime" / "proposals"
    repository = MarkdownProposalRepository(
        root,
        create_parents=True,
    )

    result = repository.create(create_proposal())

    assert result.success is True
    assert root.is_dir()
    assert result.path == root / f"{PROPOSAL_ID}.md"


def test_creation_writes_canonical_document(
    tmp_path: Path,
) -> None:
    """Stored content should exactly match deterministic rendering."""
    root = tmp_path / "proposals"
    root.mkdir()
    proposal = create_proposal()
    repository = MarkdownProposalRepository(root)

    result = repository.create(proposal)

    assert result.success is True
    assert result.proposal == proposal
    assert result.path is not None
    assert result.path.read_text(encoding="utf-8") == render_proposal_document(proposal)


def test_created_document_round_trips(
    tmp_path: Path,
) -> None:
    """Persisted Markdown should reconstruct the proposal."""
    root = tmp_path / "proposals"
    root.mkdir()
    proposal = create_proposal()
    repository = MarkdownProposalRepository(root)

    result = repository.create(proposal)

    assert result.path is not None
    parsed = parse_proposal_document(result.path.read_text(encoding="utf-8"))

    assert parsed.success is True
    assert parsed.proposal == proposal


def test_duplicate_creation_does_not_overwrite(
    tmp_path: Path,
) -> None:
    """Existing proposal content must remain unchanged."""
    root = tmp_path / "proposals"
    root.mkdir()
    repository = MarkdownProposalRepository(root)
    proposal = create_proposal()

    first = repository.create(proposal)
    assert first.success is True
    assert first.path is not None

    original_content = first.path.read_text(encoding="utf-8")

    second = repository.create(proposal)

    assert second.success is False
    assert second.proposal is None
    assert second.issues[0].code == "proposal_already_exists"
    assert first.path.read_text(encoding="utf-8") == original_content


def test_repository_root_occupied_by_file(
    tmp_path: Path,
) -> None:
    """A non-directory repository root must fail closed."""
    root = tmp_path / "proposals"
    root.write_text(
        "conflict",
        encoding="utf-8",
    )
    repository = MarkdownProposalRepository(root)

    result = repository.create(create_proposal())

    assert result.success is False
    assert result.issues[0].code == "proposal_directory_not_directory"
    assert root.read_text(encoding="utf-8") == "conflict"


def test_creation_leaves_no_temporary_files(
    tmp_path: Path,
) -> None:
    """Successful publication should remove temporary documents."""
    root = tmp_path / "proposals"
    root.mkdir()
    repository = MarkdownProposalRepository(root)

    result = repository.create(create_proposal())

    assert result.success is True
    assert tuple(root.glob("*.tmp")) == ()
    assert tuple(root.glob(".*.tmp")) == ()


def test_duplicate_creation_leaves_no_temporary_files(
    tmp_path: Path,
) -> None:
    """Duplicate publication failure should clean its temporary file."""
    root = tmp_path / "proposals"
    root.mkdir()
    repository = MarkdownProposalRepository(root)
    proposal = create_proposal()

    first = repository.create(proposal)
    second = repository.create(proposal)

    assert first.success is True
    assert second.success is False
    assert tuple(root.glob("*.tmp")) == ()
    assert tuple(root.glob(".*.tmp")) == ()


def test_creation_is_independent_of_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing directory must not change persistence location."""
    root = tmp_path / "runtime" / "proposals"
    other = tmp_path / "other"
    root.mkdir(parents=True)
    other.mkdir()
    repository = MarkdownProposalRepository(root)

    monkeypatch.chdir(other)

    result = repository.create(create_proposal())

    assert result.success is True
    assert result.path == root / f"{PROPOSAL_ID}.md"
    assert result.path.is_file()


def test_creation_with_fsync_succeeds(
    tmp_path: Path,
) -> None:
    """Explicit synchronisation should preserve normal behaviour."""
    root = tmp_path / "proposals"
    root.mkdir()
    repository = MarkdownProposalRepository(
        root,
        fsync=True,
    )

    result = repository.create(create_proposal())

    assert result.success is True
    assert result.path is not None
    assert result.path.is_file()


def test_created_proposal_uses_group_readable_mode(
    tmp_path: Path,
) -> None:
    root = tmp_path / "proposals"
    root.mkdir()
    repository = MarkdownProposalRepository(root)

    result = repository.create(create_proposal())

    assert result.success is True
    assert result.path is not None
    assert stat.S_IMODE(result.path.stat().st_mode) == 0o640
