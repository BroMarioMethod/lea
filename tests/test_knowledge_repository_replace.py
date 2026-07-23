"""Tests for version-guarded knowledge replacement and moves."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lea.knowledge import (
    KnowledgeDocument,
    KnowledgeDocumentType,
    KnowledgeSensitivity,
    MarkdownKnowledgeRepository,
)

DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"
CREATED_AT = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)


def _document(
    *,
    version: int,
    title: str = "Boiler review",
    document_type: KnowledgeDocumentType = KnowledgeDocumentType.NOTE,
    created_at: datetime = CREATED_AT,
    updated_at: datetime | None = None,
) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=DOCUMENT_ID,
        document_type=document_type,
        document_version=version,
        title=title,
        sensitivity=KnowledgeSensitivity.MEDIUM,
        created_at=created_at,
        updated_at=updated_at or CREATED_AT + timedelta(minutes=version),
        body=f"# {title}\n",
    )


def _repository(tmp_path: Path) -> MarkdownKnowledgeRepository:
    return MarkdownKnowledgeRepository(
        tmp_path / "knowledge",
        create_parents=True,
    )


def test_replace_updates_and_moves_for_title_change(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    existing = _document(version=1)
    replacement = _document(version=2, title="Updated boiler review")
    created = repository.create(existing)
    assert created.success is True
    assert created.path is not None

    result = repository.replace(replacement, expected_version=1)

    assert result.success is True
    assert result.previous_document == existing
    assert result.document == replacement
    assert result.previous_path == created.path
    assert result.path is not None
    assert result.path != created.path
    assert created.path.exists() is False
    assert repository.read(DOCUMENT_ID).document == replacement


def test_replace_rejects_missing_document(tmp_path: Path) -> None:
    result = _repository(tmp_path).replace(
        _document(version=2),
        expected_version=1,
    )
    assert result.success is False
    assert result.issues[0].code == "knowledge_not_found"


def test_replace_rejects_stale_expected_version(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    existing = _document(version=2)
    assert repository.create(existing).success is True

    result = repository.replace(_document(version=3), expected_version=1)

    assert result.success is False
    assert result.issues[0].code == "knowledge_version_conflict"
    assert result.issues[0].expected_version == 1
    assert result.issues[0].actual_version == 2
    assert repository.read(DOCUMENT_ID).document == existing


@pytest.mark.parametrize("replacement_version", (1, 3, 4))
def test_replace_requires_exact_next_version(
    tmp_path: Path,
    replacement_version: int,
) -> None:
    repository = _repository(tmp_path)
    existing = _document(version=1)
    assert repository.create(existing).success is True

    result = repository.replace(
        _document(version=replacement_version),
        expected_version=1,
    )

    assert result.success is False
    assert result.issues[0].code == "knowledge_invalid_next_version"
    assert repository.read(DOCUMENT_ID).document == existing


def test_replace_preserves_created_at(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    existing = _document(version=1)
    assert repository.create(existing).success is True

    result = repository.replace(
        _document(
            version=2,
            created_at=CREATED_AT + timedelta(hours=1),
            updated_at=CREATED_AT + timedelta(hours=2),
        ),
        expected_version=1,
    )

    assert result.success is False
    assert result.issues[0].code == "knowledge_created_at_changed"


def test_replace_rejects_backwards_updated_at(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    existing = _document(
        version=1,
        updated_at=CREATED_AT + timedelta(hours=2),
    )
    assert repository.create(existing).success is True

    result = repository.replace(
        _document(
            version=2,
            updated_at=CREATED_AT + timedelta(hours=1),
        ),
        expected_version=1,
    )

    assert result.success is False
    assert result.issues[0].code == "knowledge_updated_at_regressed"


def test_type_change_moves_between_directories(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    existing = _document(version=1)
    created = repository.create(existing)
    assert created.path is not None

    replacement = _document(
        version=2,
        document_type=KnowledgeDocumentType.PROJECT,
    )
    result = repository.replace(replacement, expected_version=1)

    assert result.success is True
    assert result.path is not None
    assert result.path.parent.name == "projects"
    assert created.path.exists() is False


def test_replace_leaves_no_temporary_files(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    assert repository.create(_document(version=1)).success is True

    result = repository.replace(
        _document(version=2, title="Renamed"),
        expected_version=1,
    )

    assert result.success is True
    assert tuple(repository.root.rglob("*.tmp")) == ()
    assert tuple(repository.root.rglob(".*.tmp")) == ()


def test_same_path_failure_preserves_existing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(tmp_path)
    existing = _document(version=1)
    assert repository.create(existing).success is True

    def fail_replace(source: object, destination: object) -> None:
        raise OSError("Simulated replacement failure.")

    monkeypatch.setattr(
        "lea.knowledge.repository.os.replace",
        fail_replace,
    )

    result = repository.replace(_document(version=2), expected_version=1)

    assert result.success is False
    assert result.issues[0].code == "knowledge_replace_failed"
    assert repository.read(DOCUMENT_ID).document == existing


def test_replace_with_fsync_succeeds(tmp_path: Path) -> None:
    repository = MarkdownKnowledgeRepository(
        tmp_path / "knowledge",
        create_parents=True,
        fsync=True,
    )
    assert repository.create(_document(version=1)).success is True

    result = repository.replace(
        _document(version=2, title="Fsynced replacement"),
        expected_version=1,
    )

    assert result.success is True
