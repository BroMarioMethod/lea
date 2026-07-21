"""Tests for read-only proposal repository verification."""

from datetime import UTC, datetime
from pathlib import Path

from lea.actions import ActionProposal
from lea.proposals import (
    MarkdownProposalRepository,
    render_proposal_document,
)

FIRST_ID = "11111111-1111-4111-8111-111111111111"
SECOND_ID = "22222222-2222-4222-8222-222222222222"


def create_proposal(
    *,
    proposal_id: str = FIRST_ID,
) -> ActionProposal:
    """Return one deterministic proposal."""
    return ActionProposal(
        proposal_id=proposal_id,
        action="task.create",
        parameters={"description": "Test task"},
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


def issue_codes(
    repository: MarkdownProposalRepository,
) -> tuple[str, ...]:
    """Return verification issue codes in reported order."""
    return tuple(issue.code for issue in repository.verify().issues)


def test_empty_repository_is_valid(
    tmp_path: Path,
) -> None:
    """An existing empty repository should be valid."""
    repository = create_repository(tmp_path)

    result = repository.verify()

    assert result.valid is True
    assert result.checked_documents == 0
    assert result.issues == ()


def test_valid_repository_is_verified(
    tmp_path: Path,
) -> None:
    """Canonical proposal documents should pass verification."""
    repository = create_repository(tmp_path)
    proposal = create_proposal()

    assert repository.create(proposal).success is True

    result = repository.verify()

    assert result.valid is True
    assert result.checked_documents == 1
    assert result.issues == ()


def test_multiple_valid_documents_are_counted(
    tmp_path: Path,
) -> None:
    """Every canonical document should be inspected."""
    repository = create_repository(tmp_path)

    assert repository.create(create_proposal(proposal_id=FIRST_ID)).success is True
    assert repository.create(create_proposal(proposal_id=SECOND_ID)).success is True

    result = repository.verify()

    assert result.valid is True
    assert result.checked_documents == 2
    assert result.issues == ()


def test_missing_repository_is_invalid_and_not_created(
    tmp_path: Path,
) -> None:
    """Verification must not create a missing directory."""
    root = tmp_path / "proposals"
    repository = MarkdownProposalRepository(
        root,
        create_parents=True,
    )

    result = repository.verify()

    assert result.valid is False
    assert result.checked_documents == 0
    assert result.issues[0].code == "proposal_directory_missing"
    assert result.issues[0].path == root
    assert root.exists() is False


def test_repository_root_occupied_by_file_is_invalid(
    tmp_path: Path,
) -> None:
    """A repository root must be a directory."""
    root = tmp_path / "proposals"
    root.write_text("conflict", encoding="utf-8")
    repository = MarkdownProposalRepository(root)

    result = repository.verify()

    assert result.valid is False
    assert result.checked_documents == 0
    assert result.issues[0].code == "proposal_directory_not_directory"
    assert root.read_text(encoding="utf-8") == "conflict"


def test_malformed_document_is_reported(
    tmp_path: Path,
) -> None:
    """Malformed canonical documents should invalidate the repository."""
    repository = create_repository(tmp_path)
    destination = repository.path_for(FIRST_ID)
    destination.write_text(
        "# Not a proposal\n",
        encoding="utf-8",
    )

    result = repository.verify()

    assert result.valid is False
    assert result.checked_documents == 1
    assert result.issues[0].code == "proposal_malformed_document"
    assert result.issues[0].path == destination


def test_non_canonical_document_is_reported(
    tmp_path: Path,
) -> None:
    """Semantically valid but non-canonical content should fail."""
    repository = create_repository(tmp_path)
    proposal = create_proposal()
    destination = repository.path_for(FIRST_ID)

    document = render_proposal_document(proposal).replace(
        '{"description":"Test task"}',
        '{"description": "Test task"}',
    )
    destination.write_text(
        document,
        encoding="utf-8",
    )

    result = repository.verify()

    assert result.valid is False
    assert result.checked_documents == 1
    assert result.issues[0].code == "proposal_non_canonical_document"


def test_filename_document_identity_mismatch_is_reported(
    tmp_path: Path,
) -> None:
    """A document may not claim another proposal identifier."""
    repository = create_repository(tmp_path)
    destination = repository.path_for(FIRST_ID)
    destination.write_text(
        render_proposal_document(create_proposal(proposal_id=SECOND_ID)),
        encoding="utf-8",
    )

    result = repository.verify()

    assert result.valid is False
    assert result.checked_documents == 1
    assert result.issues[0].code == "proposal_identity_mismatch"
    assert result.issues[0].path == destination


def test_invalid_markdown_filename_is_reported(
    tmp_path: Path,
) -> None:
    """Markdown files must use canonical UUID filenames."""
    repository = create_repository(tmp_path)
    invalid_path = repository.root / "not-a-uuid.md"
    invalid_path.write_text(
        "# Unexpected document\n",
        encoding="utf-8",
    )

    result = repository.verify()

    assert result.valid is False
    assert result.checked_documents == 0
    assert result.issues[0].code == "proposal_invalid_filename"
    assert result.issues[0].path == invalid_path


def test_unexpected_non_markdown_file_is_reported(
    tmp_path: Path,
) -> None:
    """Unrecognised files should not be silently ignored."""
    repository = create_repository(tmp_path)
    unexpected = repository.root / "notes.txt"
    unexpected.write_text(
        "Unexpected.",
        encoding="utf-8",
    )

    result = repository.verify()

    assert result.valid is False
    assert result.checked_documents == 0
    assert result.issues[0].code == "proposal_unexpected_file"
    assert result.issues[0].path == unexpected


def test_unexpected_directory_is_reported(
    tmp_path: Path,
) -> None:
    """Nested directories are not part of the flat repository."""
    repository = create_repository(tmp_path)
    unexpected = repository.root / "nested"
    unexpected.mkdir()

    result = repository.verify()

    assert result.valid is False
    assert result.checked_documents == 0
    assert result.issues[0].code == "proposal_unexpected_entry"
    assert result.issues[0].path == unexpected


def test_leftover_temporary_file_is_reported(
    tmp_path: Path,
) -> None:
    """Interrupted-write artefacts should be visible."""
    repository = create_repository(tmp_path)
    temporary = repository.root / f".{FIRST_ID}.interrupted.tmp"
    temporary.write_text(
        "partial",
        encoding="utf-8",
    )

    result = repository.verify()

    assert result.valid is False
    assert result.checked_documents == 0
    assert result.issues[0].code == "proposal_temporary_file"
    assert result.issues[0].path == temporary


def test_symbolic_link_is_reported(
    tmp_path: Path,
) -> None:
    """Verification must not follow repository symbolic links."""
    repository = create_repository(tmp_path)
    target = tmp_path / "outside.md"
    target.write_text(
        render_proposal_document(create_proposal()),
        encoding="utf-8",
    )
    link = repository.path_for(FIRST_ID)
    link.symlink_to(target)

    result = repository.verify()

    assert result.valid is False
    assert result.checked_documents == 0
    assert result.issues[0].code == "proposal_symbolic_link"
    assert result.issues[0].path == link


def test_all_detected_issues_are_returned(
    tmp_path: Path,
) -> None:
    """Verification should not stop after the first bad entry."""
    repository = create_repository(tmp_path)

    (repository.root / "notes.txt").write_text(
        "Unexpected.",
        encoding="utf-8",
    )
    (repository.root / "not-a-uuid.md").write_text(
        "# Invalid\n",
        encoding="utf-8",
    )
    repository.path_for(FIRST_ID).write_text(
        "# Malformed\n",
        encoding="utf-8",
    )

    result = repository.verify()

    assert result.valid is False
    assert result.checked_documents == 1
    assert issue_codes(repository) == (
        "proposal_malformed_document",
        "proposal_invalid_filename",
        "proposal_unexpected_file",
    )


def test_issue_order_is_deterministic(
    tmp_path: Path,
) -> None:
    """Issues should follow deterministic filename ordering."""
    repository = create_repository(tmp_path)

    (repository.root / "z.txt").write_text(
        "Unexpected.",
        encoding="utf-8",
    )
    (repository.root / "a.txt").write_text(
        "Unexpected.",
        encoding="utf-8",
    )

    first = repository.verify()
    second = repository.verify()

    assert first == second
    assert tuple(
        issue.path.name for issue in first.issues if issue.path is not None
    ) == (
        "a.txt",
        "z.txt",
    )


def test_verification_does_not_modify_repository(
    tmp_path: Path,
) -> None:
    """Verification must be strictly read-only."""
    repository = create_repository(tmp_path)
    proposal = create_proposal()

    write_result = repository.create(proposal)
    assert write_result.path is not None

    unexpected = repository.root / "notes.txt"
    unexpected.write_text(
        "Keep this.",
        encoding="utf-8",
    )

    before = {
        path.name: path.read_bytes()
        for path in repository.root.iterdir()
        if path.is_file()
    }

    result = repository.verify()

    after = {
        path.name: path.read_bytes()
        for path in repository.root.iterdir()
        if path.is_file()
    }

    assert result.valid is False
    assert before == after
