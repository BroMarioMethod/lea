"""Durability-failure tests for versioned knowledge replacement."""

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
) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=DOCUMENT_ID,
        document_type=document_type,
        document_version=version,
        title=title,
        sensitivity=KnowledgeSensitivity.MEDIUM,
        created_at=CREATED_AT,
        updated_at=CREATED_AT + timedelta(minutes=version),
        body=f"# {title}\n",
    )


def _repository(tmp_path: Path) -> MarkdownKnowledgeRepository:
    repository = MarkdownKnowledgeRepository(
        tmp_path / "knowledge",
        create_parents=True,
        fsync=True,
    )
    assert repository.create(_document(version=1)).success is True
    return repository


def test_move_destination_fsync_failure_preserves_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(tmp_path)
    existing = repository.read(DOCUMENT_ID)
    assert existing.path is not None

    def fail_fsync(directory: Path) -> None:
        raise OSError("Simulated destination fsync failure.")

    monkeypatch.setattr(
        "lea.knowledge.repository._fsync_directory",
        fail_fsync,
    )

    replacement = _document(
        version=2,
        document_type=KnowledgeDocumentType.PROJECT,
    )
    result = repository.replace(replacement, expected_version=1)

    assert result.success is False
    assert result.issues[0].code == "knowledge_move_failed"
    assert existing.path.exists() is True
    assert repository.read(DOCUMENT_ID).document == existing.document
    assert tuple(repository.root.rglob(f"*--{DOCUMENT_ID}.md")) == (existing.path,)


def test_move_source_fsync_failure_retains_published_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(tmp_path)
    existing = repository.read(DOCUMENT_ID)
    assert existing.path is not None
    calls = 0

    def fail_second_fsync(directory: Path) -> None:
        nonlocal calls
        calls += 1

        if calls == 2:
            raise OSError("Simulated source-directory fsync failure.")

    monkeypatch.setattr(
        "lea.knowledge.repository._fsync_directory",
        fail_second_fsync,
    )

    replacement = _document(
        version=2,
        document_type=KnowledgeDocumentType.PROJECT,
    )
    result = repository.replace(replacement, expected_version=1)

    assert result.success is False
    assert result.issues[0].code == "knowledge_durability_failed"
    assert existing.path.exists() is False

    readback = repository.read(DOCUMENT_ID)
    assert readback.success is True
    assert readback.document == replacement
    assert readback.path == result.path


def test_same_path_fsync_failure_retains_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(tmp_path)

    def fail_fsync(directory: Path) -> None:
        raise OSError("Simulated same-path fsync failure.")

    monkeypatch.setattr(
        "lea.knowledge.repository._fsync_directory",
        fail_fsync,
    )

    replacement = _document(version=2)
    result = repository.replace(replacement, expected_version=1)

    assert result.success is False
    assert result.issues[0].code == "knowledge_durability_failed"
    assert repository.read(DOCUMENT_ID).document == replacement


def test_source_unlink_failure_rolls_back_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(tmp_path)
    existing = repository.read(DOCUMENT_ID)
    assert existing.path is not None
    original_unlink = Path.unlink

    def fail_source_unlink(
        path: Path,
        missing_ok: bool = False,
    ) -> None:
        if path == existing.path:
            raise OSError("Simulated source unlink failure.")

        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_source_unlink)

    replacement = _document(
        version=2,
        document_type=KnowledgeDocumentType.PROJECT,
    )
    result = repository.replace(replacement, expected_version=1)

    assert result.success is False
    assert result.issues[0].code == "knowledge_move_failed"
    assert existing.path.exists() is True
    assert repository.read(DOCUMENT_ID).document == existing.document
    assert tuple(repository.root.rglob(f"*--{DOCUMENT_ID}.md")) == (existing.path,)
