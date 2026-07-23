"""Tests for the initial Markdown knowledge repository boundary."""

from datetime import UTC, datetime
from pathlib import Path

from lea.knowledge import (
    KnowledgeDocument,
    KnowledgeDocumentLink,
    KnowledgeDocumentType,
    KnowledgeExternalReference,
    KnowledgeQuery,
    KnowledgeSensitivity,
    MarkdownKnowledgeRepository,
    render_knowledge_document,
)

FIRST_ID = "11111111-1111-4111-8111-111111111111"
SECOND_ID = "22222222-2222-4222-8222-222222222222"
TARGET_ID = "33333333-3333-4333-8333-333333333333"
THIRD_ID = "44444444-4444-4444-8444-444444444444"


def _document(
    document_id: str,
    *,
    title: str,
    document_type: KnowledgeDocumentType = KnowledgeDocumentType.NOTE,
    sensitivity: KnowledgeSensitivity = KnowledgeSensitivity.LOW,
) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=document_id,
        document_type=document_type,
        document_version=1,
        title=title,
        sensitivity=sensitivity,
        created_at=datetime(2026, 7, 23, 8, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 23, 8, 0, tzinfo=UTC),
        body=f"# {title}\n",
        links=(
            KnowledgeDocumentLink(
                relation="related",
                document_id=TARGET_ID,
            ),
        ),
        external_references=(
            KnowledgeExternalReference(
                namespace="lea.proposal",
                identifier=TARGET_ID,
            ),
        ),
    )


def test_create_and_read_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    repository = MarkdownKnowledgeRepository(root, create_parents=True)
    document = _document(FIRST_ID, title="Boiler review")

    created = repository.create(document)
    read = repository.read(FIRST_ID)

    assert created.success is True
    assert read.success is True
    assert read.document == document
    assert created.path is not None
    assert created.path.read_text(encoding="utf-8") == (
        render_knowledge_document(document)
    )


def test_create_rejects_duplicate_identifier(tmp_path: Path) -> None:
    repository = MarkdownKnowledgeRepository(
        tmp_path / "knowledge",
        create_parents=True,
    )

    assert repository.create(_document(FIRST_ID, title="First")).success is True

    duplicate = repository.create(_document(FIRST_ID, title="Renamed"))

    assert duplicate.success is False
    assert duplicate.issues[0].code == "knowledge_duplicate_id"


def test_missing_read_returns_structured_failure(tmp_path: Path) -> None:
    result = MarkdownKnowledgeRepository(tmp_path / "knowledge").read(FIRST_ID)

    assert result.success is False
    assert result.issues[0].code == "knowledge_not_found"


def test_invalid_utf8_is_reported(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    notes = root / "notes"
    notes.mkdir(parents=True)
    (notes / f"invalid--{FIRST_ID}.md").write_bytes(b"\xff\xfe")

    result = MarkdownKnowledgeRepository(root).read(FIRST_ID)

    assert result.success is False
    assert result.issues[0].code == "knowledge_invalid_utf8"


def test_filename_metadata_mismatch_is_reported(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    notes = root / "notes"
    notes.mkdir(parents=True)
    document = _document(FIRST_ID, title="Correct title")
    wrong = notes / f"wrong-title--{FIRST_ID}.md"
    wrong.write_text(render_knowledge_document(document), encoding="utf-8")

    result = MarkdownKnowledgeRepository(root).read(FIRST_ID)

    assert result.success is False
    assert result.issues[0].code == "knowledge_filename_mismatch"


def test_empty_existing_repository_lists_successfully(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()

    result = MarkdownKnowledgeRepository(root).list()

    assert result.success is True
    assert result.documents == ()


def test_list_uses_type_title_and_identifier_order(tmp_path: Path) -> None:
    repository = MarkdownKnowledgeRepository(
        tmp_path / "knowledge",
        create_parents=True,
    )

    documents = (
        _document(
            FIRST_ID,
            title="Zulu",
            document_type=KnowledgeDocumentType.PROJECT,
        ),
        _document(SECOND_ID, title="beta"),
        _document(THIRD_ID, title="Alpha"),
    )

    for document in documents:
        assert repository.create(document).success is True

    result = repository.list()

    assert result.success is True
    assert tuple(item.document_id for item in result.documents) == (
        THIRD_ID,
        SECOND_ID,
        FIRST_ID,
    )


def test_list_filters_exact_fields(tmp_path: Path) -> None:
    repository = MarkdownKnowledgeRepository(
        tmp_path / "knowledge",
        create_parents=True,
    )

    low_note = _document(FIRST_ID, title="Low note")
    critical_project = _document(
        SECOND_ID,
        title="Critical project",
        document_type=KnowledgeDocumentType.PROJECT,
        sensitivity=KnowledgeSensitivity.CRITICAL,
    )

    assert repository.create(low_note).success is True
    assert repository.create(critical_project).success is True

    result = repository.list(
        KnowledgeQuery(
            document_type=KnowledgeDocumentType.PROJECT,
            sensitivity=KnowledgeSensitivity.CRITICAL,
            link_target_id=TARGET_ID,
            external_reference_namespace="lea.proposal",
            external_reference_identifier=TARGET_ID,
        )
    )

    assert result.success is True
    assert result.documents == (critical_project,)


def test_symlinked_type_directory_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "notes").symlink_to(outside, target_is_directory=True)

    result = MarkdownKnowledgeRepository(root).list()

    assert result.success is False
    assert result.issues[0].code == "knowledge_symlink_rejected"


def test_creation_leaves_no_temporary_files(tmp_path: Path) -> None:
    repository = MarkdownKnowledgeRepository(
        tmp_path / "knowledge",
        create_parents=True,
    )

    result = repository.create(_document(FIRST_ID, title="Temporary check"))

    assert result.success is True
    assert tuple(repository.root.rglob("*.tmp")) == ()
    assert tuple(repository.root.rglob(".*.tmp")) == ()
