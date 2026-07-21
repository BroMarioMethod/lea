"""Tests for deterministic persistent proposal listing."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from lea.actions import ActionProposal
from lea.proposals import MarkdownProposalRepository

FIRST_ID = "11111111-1111-4111-8111-111111111111"
SECOND_ID = "22222222-2222-4222-8222-222222222222"
THIRD_ID = "33333333-3333-4333-8333-333333333333"


def create_proposal(
    *,
    proposal_id: str,
    created_at: datetime,
    description: str,
) -> ActionProposal:
    """Return one deterministic proposal."""
    return ActionProposal(
        proposal_id=proposal_id,
        action="task.create",
        parameters={"description": description},
        source="user",
        created_at=created_at,
        reason=f"Create {description}.",
    )


def create_repository(
    tmp_path: Path,
) -> MarkdownProposalRepository:
    """Create one repository with an existing root."""
    root = tmp_path / "proposals"
    root.mkdir()

    return MarkdownProposalRepository(root)


def test_empty_repository_listing_succeeds(
    tmp_path: Path,
) -> None:
    """An existing empty repository should return an empty tuple."""
    repository = create_repository(tmp_path)

    result = repository.list_all()

    assert result.success is True
    assert result.proposals == ()
    assert result.issues == ()


def test_missing_repository_directory_fails(
    tmp_path: Path,
) -> None:
    """Listing must not create a missing repository directory."""
    root = tmp_path / "proposals"
    repository = MarkdownProposalRepository(
        root,
        create_parents=True,
    )

    result = repository.list_all()

    assert result.success is False
    assert result.proposals == ()
    assert result.issues[0].code == "proposal_directory_missing"
    assert result.issues[0].path == root
    assert root.exists() is False


def test_repository_root_occupied_by_file_fails(
    tmp_path: Path,
) -> None:
    """A non-directory repository root should fail closed."""
    root = tmp_path / "proposals"
    root.write_text("conflict", encoding="utf-8")
    repository = MarkdownProposalRepository(root)

    result = repository.list_all()

    assert result.success is False
    assert result.issues[0].code == "proposal_directory_not_directory"
    assert root.read_text(encoding="utf-8") == "conflict"


def test_listing_returns_all_proposals(
    tmp_path: Path,
) -> None:
    """Every canonical document should be returned."""
    repository = create_repository(tmp_path)
    timestamp = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)

    first = create_proposal(
        proposal_id=FIRST_ID,
        created_at=timestamp,
        description="first task",
    )
    second = create_proposal(
        proposal_id=SECOND_ID,
        created_at=timestamp + timedelta(minutes=1),
        description="second task",
    )

    assert repository.create(first).success is True
    assert repository.create(second).success is True

    result = repository.list_all()

    assert result.success is True
    assert result.proposals == (first, second)
    assert result.issues == ()


def test_listing_orders_by_created_at(
    tmp_path: Path,
) -> None:
    """Creation timestamps should determine primary ordering."""
    repository = create_repository(tmp_path)
    timestamp = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)

    later = create_proposal(
        proposal_id=FIRST_ID,
        created_at=timestamp + timedelta(hours=1),
        description="later task",
    )
    earlier = create_proposal(
        proposal_id=SECOND_ID,
        created_at=timestamp,
        description="earlier task",
    )

    assert repository.create(later).success is True
    assert repository.create(earlier).success is True

    result = repository.list_all()

    assert result.success is True
    assert result.proposals == (earlier, later)


def test_listing_uses_identifier_as_tie_breaker(
    tmp_path: Path,
) -> None:
    """Equal timestamps should be ordered by proposal identifier."""
    repository = create_repository(tmp_path)
    timestamp = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)

    second = create_proposal(
        proposal_id=SECOND_ID,
        created_at=timestamp,
        description="second task",
    )
    first = create_proposal(
        proposal_id=FIRST_ID,
        created_at=timestamp,
        description="first task",
    )

    assert repository.create(second).success is True
    assert repository.create(first).success is True

    result = repository.list_all()

    assert result.success is True
    assert result.proposals == (first, second)


def test_listing_order_is_independent_of_file_creation_order(
    tmp_path: Path,
) -> None:
    """Filesystem insertion order must not affect listing order."""
    repository = create_repository(tmp_path)
    timestamp = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)

    proposals = (
        create_proposal(
            proposal_id=THIRD_ID,
            created_at=timestamp + timedelta(minutes=2),
            description="third task",
        ),
        create_proposal(
            proposal_id=FIRST_ID,
            created_at=timestamp,
            description="first task",
        ),
        create_proposal(
            proposal_id=SECOND_ID,
            created_at=timestamp + timedelta(minutes=1),
            description="second task",
        ),
    )

    for proposal in proposals:
        assert repository.create(proposal).success is True

    result = repository.list_all()

    assert result.success is True
    assert tuple(proposal.proposal_id for proposal in result.proposals) == (
        FIRST_ID,
        SECOND_ID,
        THIRD_ID,
    )


def test_malformed_document_fails_entire_listing(
    tmp_path: Path,
) -> None:
    """Listing must not silently skip malformed proposals."""
    repository = create_repository(tmp_path)
    timestamp = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)

    valid = create_proposal(
        proposal_id=FIRST_ID,
        created_at=timestamp,
        description="valid task",
    )
    assert repository.create(valid).success is True

    malformed_path = repository.path_for(SECOND_ID)
    malformed_path.write_text(
        "# Not a proposal\n",
        encoding="utf-8",
    )

    result = repository.list_all()

    assert result.success is False
    assert result.proposals == ()
    assert result.issues[0].code == "proposal_malformed_document"
    assert result.issues[0].path == malformed_path


def test_invalid_canonical_filename_fails_listing(
    tmp_path: Path,
) -> None:
    """A Markdown file without a UUID filename should fail."""
    repository = create_repository(tmp_path)
    invalid_path = repository.root / "not-a-uuid.md"
    invalid_path.write_text(
        "# Unexpected document\n",
        encoding="utf-8",
    )

    result = repository.list_all()

    assert result.success is False
    assert result.proposals == ()
    assert result.issues[0].code == "proposal_invalid_filename"
    assert result.issues[0].path == invalid_path


def test_non_markdown_files_are_not_interpreted(
    tmp_path: Path,
) -> None:
    """Listing should select proposal Markdown documents only."""
    repository = create_repository(tmp_path)
    timestamp = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
    proposal = create_proposal(
        proposal_id=FIRST_ID,
        created_at=timestamp,
        description="test task",
    )

    assert repository.create(proposal).success is True

    unrelated = repository.root / "notes.txt"
    unrelated.write_text(
        "Not a proposal.",
        encoding="utf-8",
    )

    result = repository.list_all()

    assert result.success is True
    assert result.proposals == (proposal,)
    assert unrelated.read_text(encoding="utf-8") == ("Not a proposal.")


def test_listing_does_not_modify_documents(
    tmp_path: Path,
) -> None:
    """Proposal listing must remain read-only."""
    repository = create_repository(tmp_path)
    proposal = create_proposal(
        proposal_id=FIRST_ID,
        created_at=datetime(
            2026,
            7,
            21,
            12,
            0,
            tzinfo=UTC,
        ),
        description="test task",
    )

    write_result = repository.create(proposal)
    assert write_result.path is not None

    before = write_result.path.read_bytes()

    result = repository.list_all()

    assert result.success is True
    assert write_result.path.read_bytes() == before


def test_listing_is_deterministic(
    tmp_path: Path,
) -> None:
    """Repeated listings should produce identical results."""
    repository = create_repository(tmp_path)
    proposal = create_proposal(
        proposal_id=FIRST_ID,
        created_at=datetime(
            2026,
            7,
            21,
            12,
            0,
            tzinfo=UTC,
        ),
        description="test task",
    )

    assert repository.create(proposal).success is True

    first = repository.list_all()
    second = repository.list_all()

    assert first == second
