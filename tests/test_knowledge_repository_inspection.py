"""Tests for read-only knowledge repository inspection."""

from datetime import UTC, datetime
from pathlib import Path

from lea.knowledge import (
    KnowledgeDocument,
    KnowledgeDocumentType,
    KnowledgeSensitivity,
    MarkdownKnowledgeRepository,
    render_knowledge_document,
)

FIRST_ID = "11111111-1111-4111-8111-111111111111"


def _document(
    document_id: str = FIRST_ID,
    *,
    title: str = "Boiler review",
) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=document_id,
        document_type=KnowledgeDocumentType.NOTE,
        document_version=1,
        title=title,
        sensitivity=KnowledgeSensitivity.LOW,
        created_at=datetime(2026, 7, 23, 8, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 23, 8, 0, tzinfo=UTC),
        body=f"# {title}\n",
    )


def _repository(tmp_path: Path) -> MarkdownKnowledgeRepository:
    root = tmp_path / "knowledge"
    root.mkdir()
    return MarkdownKnowledgeRepository(root)


def _issue_codes(
    repository: MarkdownKnowledgeRepository,
) -> tuple[str, ...]:
    return tuple(issue.code for issue in repository.inspect().issues)


def test_empty_repository_is_available_and_valid(tmp_path: Path) -> None:
    result = _repository(tmp_path).inspect()

    assert result.available is True
    assert result.checked_documents == 0
    assert result.valid_documents == 0
    assert result.issues == ()


def test_valid_repository_is_inspected(tmp_path: Path) -> None:
    repository = MarkdownKnowledgeRepository(
        tmp_path / "knowledge",
        create_parents=True,
    )
    assert repository.create(_document()).success is True

    result = repository.inspect()

    assert result.available is True
    assert result.checked_documents == 1
    assert result.valid_documents == 1
    assert result.issues == ()


def test_missing_repository_is_unavailable_and_not_created(
    tmp_path: Path,
) -> None:
    root = tmp_path / "knowledge"
    repository = MarkdownKnowledgeRepository(root, create_parents=True)

    result = repository.inspect()

    assert result.available is False
    assert result.checked_documents == 0
    assert result.valid_documents == 0
    assert result.issues[0].code == "knowledge_directory_missing"
    assert root.exists() is False


def test_accessible_repository_can_be_degraded(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    unexpected = repository.root / "unexpected.txt"
    unexpected.write_text("External artefact.", encoding="utf-8")

    result = repository.inspect()

    assert result.available is True
    assert result.checked_documents == 0
    assert result.valid_documents == 0
    assert result.issues[0].code == "knowledge_unexpected_file"


def test_malformed_document_is_reported(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    notes = repository.root / "notes"
    notes.mkdir()
    path = notes / f"broken--{FIRST_ID}.md"
    path.write_text("# Not canonical knowledge\n", encoding="utf-8")

    result = repository.inspect()

    assert result.available is True
    assert result.checked_documents == 1
    assert result.valid_documents == 0
    assert result.issues[0].code == "knowledge_front_matter_missing"
    assert result.issues[0].path == path


def test_externally_renamed_document_is_reported(tmp_path: Path) -> None:
    repository = MarkdownKnowledgeRepository(
        tmp_path / "knowledge",
        create_parents=True,
    )
    document = _document(title="Correct title")
    created = repository.create(document)
    assert created.path is not None

    renamed = created.path.with_name(f"wrong-title--{FIRST_ID}.md")
    created.path.rename(renamed)

    result = repository.inspect()

    assert result.available is True
    assert result.checked_documents == 1
    assert result.valid_documents == 0
    assert result.issues[0].code == "knowledge_filename_mismatch"


def test_duplicate_identifiers_are_reported(tmp_path: Path) -> None:
    repository = MarkdownKnowledgeRepository(
        tmp_path / "knowledge",
        create_parents=True,
    )
    document = _document()
    created = repository.create(document)
    assert created.path is not None

    projects = repository.root / "projects"
    projects.mkdir()
    duplicate = projects / f"duplicate--{FIRST_ID}.md"
    duplicate.write_text(
        render_knowledge_document(document),
        encoding="utf-8",
    )

    result = repository.inspect()

    assert result.available is True
    assert result.checked_documents == 2
    assert result.valid_documents == 1
    assert "knowledge_duplicate_id" in _issue_codes(repository)


def test_leftover_temporary_file_is_reported(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    notes = repository.root / "notes"
    notes.mkdir()
    temporary = notes / f".{FIRST_ID}.interrupted.tmp"
    temporary.write_text("partial", encoding="utf-8")

    result = repository.inspect()

    assert result.available is True
    assert result.issues[0].code == "knowledge_temporary_file"


def test_symbolic_links_are_reported_without_following(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = repository.root / "notes"
    link.symlink_to(outside, target_is_directory=True)

    result = repository.inspect()

    assert result.available is True
    assert result.issues[0].code == "knowledge_symlink_rejected"


def test_all_issues_are_returned_in_deterministic_order(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    notes = repository.root / "notes"
    notes.mkdir()

    (repository.root / "z.txt").write_text("Z", encoding="utf-8")
    (repository.root / "a.txt").write_text("A", encoding="utf-8")
    (notes / "bad.md").write_text("# Invalid\n", encoding="utf-8")

    first = repository.inspect()
    second = repository.inspect()

    assert first == second
    assert tuple(
        issue.path.name for issue in first.issues if issue.path is not None
    ) == ("a.txt", "bad.md", "z.txt")


def test_inspection_does_not_modify_repository(tmp_path: Path) -> None:
    repository = MarkdownKnowledgeRepository(
        tmp_path / "knowledge",
        create_parents=True,
    )
    created = repository.create(_document())
    assert created.path is not None
    before = created.path.read_bytes()

    result = repository.inspect()

    assert result.available is True
    assert created.path.read_bytes() == before
