"""Tests for exact persistent proposal retrieval."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from lea.actions import ActionProposal
from lea.proposals import (
    MarkdownProposalRepository,
    render_proposal_document,
)

PROPOSAL_ID = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"
OTHER_PROPOSAL_ID = "9fd926b8-1ce6-447f-a8bb-cdc48017d551"


def create_proposal(
    *,
    proposal_id: str = PROPOSAL_ID,
) -> ActionProposal:
    """Return one deterministic action proposal."""
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


def create_repository(
    tmp_path: Path,
) -> MarkdownProposalRepository:
    """Create one repository with an existing root."""
    root = tmp_path / "proposals"
    root.mkdir()

    return MarkdownProposalRepository(root)


def test_read_returns_exact_proposal(
    tmp_path: Path,
) -> None:
    """A canonical document should reconstruct its proposal."""
    repository = create_repository(tmp_path)
    proposal = create_proposal()

    write_result = repository.create(proposal)
    read_result = repository.read(PROPOSAL_ID)

    assert write_result.success is True
    assert read_result.success is True
    assert read_result.proposal == proposal
    assert read_result.path == repository.path_for(PROPOSAL_ID)
    assert read_result.issues == ()


def test_missing_proposal_returns_structured_failure(
    tmp_path: Path,
) -> None:
    """Missing documents should not be treated as empty results."""
    repository = create_repository(tmp_path)

    result = repository.read(PROPOSAL_ID)

    assert result.success is False
    assert result.proposal is None
    assert result.path == repository.path_for(PROPOSAL_ID)
    assert result.issues[0].code == "proposal_not_found"
    assert result.issues[0].proposal_id == PROPOSAL_ID


def test_read_rejects_invalid_identifier(
    tmp_path: Path,
) -> None:
    """Unchecked caller input must not become a filesystem path."""
    repository = create_repository(tmp_path)

    with pytest.raises(
        ValueError,
        match="proposal_id",
    ):
        repository.read("../proposal")


def test_read_rejects_uppercase_identifier(
    tmp_path: Path,
) -> None:
    """Only canonical lower-case UUID text is permitted."""
    repository = create_repository(tmp_path)

    with pytest.raises(
        ValueError,
        match="canonical lower-case UUID",
    ):
        repository.read(PROPOSAL_ID.upper())


def test_canonical_path_occupied_by_directory(
    tmp_path: Path,
) -> None:
    """A directory at the document path should fail explicitly."""
    repository = create_repository(tmp_path)
    destination = repository.path_for(PROPOSAL_ID)
    destination.mkdir()

    result = repository.read(PROPOSAL_ID)

    assert result.success is False
    assert result.issues[0].code == "proposal_read_failed"
    assert result.path == destination


def test_malformed_document_returns_parser_issue(
    tmp_path: Path,
) -> None:
    """Malformed Markdown should preserve structured parser context."""
    repository = create_repository(tmp_path)
    destination = repository.path_for(PROPOSAL_ID)
    destination.write_text(
        "# Not a proposal\n",
        encoding="utf-8",
    )

    result = repository.read(PROPOSAL_ID)

    assert result.success is False
    assert result.proposal is None
    assert result.issues[0].code == "proposal_malformed_document"
    assert result.issues[0].path == destination
    assert result.issues[0].proposal_id == PROPOSAL_ID


def test_non_canonical_document_returns_parser_issue(
    tmp_path: Path,
) -> None:
    """Semantically valid but non-canonical Markdown must fail."""
    repository = create_repository(tmp_path)
    proposal = create_proposal()
    destination = repository.path_for(PROPOSAL_ID)

    document = render_proposal_document(proposal).replace(
        '{"description":"Test task","priority":2}',
        '{"description": "Test task", "priority": 2}',
    )
    destination.write_text(
        document,
        encoding="utf-8",
    )

    result = repository.read(PROPOSAL_ID)

    assert result.success is False
    assert result.issues[0].code == "proposal_non_canonical_document"
    assert result.issues[0].path == destination


def test_filename_and_document_identifier_must_match(
    tmp_path: Path,
) -> None:
    """A document may not claim another proposal identity."""
    repository = create_repository(tmp_path)
    proposal = create_proposal(
        proposal_id=OTHER_PROPOSAL_ID,
    )
    destination = repository.path_for(PROPOSAL_ID)
    destination.write_text(
        render_proposal_document(proposal),
        encoding="utf-8",
    )

    result = repository.read(PROPOSAL_ID)

    assert result.success is False
    assert result.issues[0].code == "proposal_identity_mismatch"
    assert result.issues[0].proposal_id == PROPOSAL_ID
    assert result.path == destination


def test_invalid_utf8_returns_read_failure(
    tmp_path: Path,
) -> None:
    """Non-UTF-8 content should fail without leaking decoder details."""
    repository = create_repository(tmp_path)
    destination = repository.path_for(PROPOSAL_ID)
    destination.write_bytes(b"\xff\xfe\x00")

    result = repository.read(PROPOSAL_ID)

    assert result.success is False
    assert result.issues[0].code == "proposal_read_failed"
    assert result.path == destination


def test_read_is_independent_of_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exact retrieval must use only the configured repository root."""
    repository = create_repository(tmp_path)
    proposal = create_proposal()
    write_result = repository.create(proposal)

    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)

    read_result = repository.read(PROPOSAL_ID)

    assert write_result.success is True
    assert read_result.success is True
    assert read_result.proposal == proposal


def test_read_does_not_modify_document(
    tmp_path: Path,
) -> None:
    """Retrieval must remain read-only."""
    repository = create_repository(tmp_path)
    proposal = create_proposal()

    write_result = repository.create(proposal)
    assert write_result.path is not None

    original = write_result.path.read_bytes()

    read_result = repository.read(PROPOSAL_ID)

    assert read_result.success is True
    assert write_result.path.read_bytes() == original


def test_read_does_not_create_missing_repository(
    tmp_path: Path,
) -> None:
    """Retrieval must not create the configured repository root."""
    root = tmp_path / "proposals"
    repository = MarkdownProposalRepository(
        root,
        create_parents=True,
    )

    result = repository.read(PROPOSAL_ID)

    assert result.success is False
    assert result.issues[0].code == "proposal_not_found"
    assert root.exists() is False
