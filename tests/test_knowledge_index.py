"""Tests for the disposable SQLite knowledge index."""

import sqlite3
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
    SQLiteKnowledgeIndex,
)

FIRST_ID = "11111111-1111-4111-8111-111111111111"
SECOND_ID = "22222222-2222-4222-8222-222222222222"
TARGET_ID = "33333333-3333-4333-8333-333333333333"
NOW = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)


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
        created_at=NOW,
        updated_at=NOW,
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


def _repository(tmp_path: Path) -> MarkdownKnowledgeRepository:
    repository = MarkdownKnowledgeRepository(
        tmp_path / "knowledge",
        create_parents=True,
    )
    assert repository.create(
        _document(
            FIRST_ID,
            title="Zulu",
            document_type=KnowledgeDocumentType.PROJECT,
            sensitivity=KnowledgeSensitivity.CRITICAL,
        )
    ).success
    assert repository.create(_document(SECOND_ID, title="alpha")).success
    return repository


def _index(tmp_path: Path) -> SQLiteKnowledgeIndex:
    return SQLiteKnowledgeIndex((tmp_path / "indexes" / "knowledge.sqlite3").absolute())


def test_rebuild_creates_disposable_database(tmp_path: Path) -> None:
    index = _index(tmp_path)

    result = index.rebuild(_repository(tmp_path))

    assert result.success is True
    assert result.indexed_documents == 2
    assert index.path.is_file()


def test_verify_reports_valid_schema_and_count(tmp_path: Path) -> None:
    index = _index(tmp_path)
    assert index.rebuild(_repository(tmp_path)).success

    verification = index.verify()

    assert verification.available is True
    assert verification.valid is True
    assert verification.indexed_documents == 2


def test_query_preserves_canonical_repository_order(tmp_path: Path) -> None:
    index = _index(tmp_path)
    assert index.rebuild(_repository(tmp_path)).success

    result = index.query()

    assert result.success is True
    assert result.document_ids == (SECOND_ID, FIRST_ID)


def test_query_supports_all_exact_filters(tmp_path: Path) -> None:
    index = _index(tmp_path)
    assert index.rebuild(_repository(tmp_path)).success

    result = index.query(
        KnowledgeQuery(
            document_id=FIRST_ID,
            document_type=KnowledgeDocumentType.PROJECT,
            sensitivity=KnowledgeSensitivity.CRITICAL,
            link_target_id=TARGET_ID,
            external_reference_namespace="lea.proposal",
            external_reference_identifier=TARGET_ID,
        )
    )

    assert result.success is True
    assert result.document_ids == (FIRST_ID,)


def test_index_stores_no_body_or_original_title(tmp_path: Path) -> None:
    index = _index(tmp_path)
    repository = _repository(tmp_path)
    assert index.rebuild(repository).success

    with sqlite3.connect(index.path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(documents)").fetchall()
        }
        row = connection.execute(
            "SELECT title_casefold FROM documents WHERE document_id = ?",
            (FIRST_ID,),
        ).fetchone()

    assert "body" not in columns
    assert "title" not in columns
    assert row == ("zulu",)


def test_failed_source_inspection_preserves_existing_index(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    index = _index(tmp_path)
    assert index.rebuild(repository).success
    before = index.path.read_bytes()

    (repository.root / "unexpected.txt").write_text(
        "invalid repository entry",
        encoding="utf-8",
    )

    result = index.rebuild(repository)

    assert result.success is False
    assert result.issues[0].code == "knowledge_index_source_invalid"
    assert index.path.read_bytes() == before


def test_rebuild_replaces_stale_index(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    index = _index(tmp_path)
    assert index.rebuild(repository).success

    third_id = "44444444-4444-4444-8444-444444444444"
    assert repository.create(_document(third_id, title="Beta")).success

    result = index.rebuild(repository)

    assert result.success is True
    assert result.indexed_documents == 3
    assert index.verify().indexed_documents == 3


def test_clear_deletes_only_disposable_database(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    index = _index(tmp_path)
    assert index.rebuild(repository).success

    result = index.clear()

    assert result.success is True
    assert result.removed is True
    assert index.path.exists() is False
    assert repository.read(FIRST_ID).success is True


def test_clear_missing_index_is_idempotent(tmp_path: Path) -> None:
    result = _index(tmp_path).clear()

    assert result.success is True
    assert result.removed is False


def test_query_missing_index_fails_closed(tmp_path: Path) -> None:
    result = _index(tmp_path).query()

    assert result.success is False
    assert result.issues[0].code == "knowledge_index_missing"


def test_runtime_bootstrap_does_not_create_database(tmp_path: Path) -> None:
    index = _index(tmp_path)

    index.path.parent.mkdir(parents=True)

    assert index.path.exists() is False
