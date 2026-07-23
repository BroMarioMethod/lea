"""Tests for deterministic knowledge filenames and safe paths."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from lea.knowledge import (
    KnowledgeDocument,
    KnowledgeDocumentType,
    KnowledgeSensitivity,
    knowledge_document_filename,
    knowledge_document_id_from_filename,
    knowledge_document_path,
    knowledge_document_slug,
    knowledge_document_type_directory,
    validate_knowledge_path,
)

DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"


def _document(
    *,
    title: str = "Boiler Efficiency Review",
    document_type: KnowledgeDocumentType = KnowledgeDocumentType.NOTE,
) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=DOCUMENT_ID,
        document_type=document_type,
        document_version=1,
        title=title,
        sensitivity=KnowledgeSensitivity.LOW,
        created_at=datetime(2026, 7, 23, 8, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 23, 8, 0, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("title", "expected"),
    (
        ("Boiler Efficiency Review", "boiler-efficiency-review"),
        ("  Boiler---Efficiency  ", "boiler-efficiency"),
        ("Crème brûlée", "creme-brulee"),
        ("123 Project", "123-project"),
        ("中文", "document"),
        ("!!!", "document"),
    ),
)
def test_slug_generation_is_deterministic(
    title: str,
    expected: str,
) -> None:
    assert knowledge_document_slug(title) == expected


def test_slug_is_limited_to_eighty_characters() -> None:
    assert knowledge_document_slug("A" * 100) == "a" * 80


def test_filename_uses_slug_and_identifier() -> None:
    assert knowledge_document_filename(_document()) == (
        f"boiler-efficiency-review--{DOCUMENT_ID}.md"
    )


@pytest.mark.parametrize(
    ("document_type", "directory"),
    (
        (KnowledgeDocumentType.NOTE, "notes"),
        (KnowledgeDocumentType.PERSON, "people"),
        (KnowledgeDocumentType.ORGANISATION, "organisations"),
        (KnowledgeDocumentType.PROJECT, "projects"),
        (KnowledgeDocumentType.DECISION, "decisions"),
        (KnowledgeDocumentType.ROLE, "roles"),
    ),
)
def test_document_type_directory_is_stable(
    document_type: KnowledgeDocumentType,
    directory: str,
) -> None:
    assert knowledge_document_type_directory(document_type) == directory


def test_document_path_is_canonical(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    document = _document(document_type=KnowledgeDocumentType.PROJECT)

    assert knowledge_document_path(root, document) == (
        root / "projects" / f"boiler-efficiency-review--{DOCUMENT_ID}.md"
    )


def test_identifier_can_be_read_from_canonical_filename() -> None:
    assert (
        knowledge_document_id_from_filename(knowledge_document_filename(_document()))
        == DOCUMENT_ID
    )


@pytest.mark.parametrize(
    "filename",
    (
        "missing-id.md",
        f"slug-{DOCUMENT_ID}.md",
        "slug--ABCDEFAB-CDEF-4ABC-8DEF-ABCDEFABCDEF.md",
        f"slug--{DOCUMENT_ID}.txt",
    ),
)
def test_identifier_extraction_rejects_non_canonical_filename(
    filename: str,
) -> None:
    with pytest.raises(ValueError, match="canonical"):
        knowledge_document_id_from_filename(filename)


def test_relative_root_is_rejected() -> None:
    with pytest.raises(ValueError, match="absolute"):
        knowledge_document_path(Path("knowledge"), _document())


def test_relative_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        validate_knowledge_path(
            tmp_path / "knowledge",
            Path("notes/a.md"),
        )


def test_path_outside_root_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"

    with pytest.raises(ValueError, match="inside"):
        validate_knowledge_path(root, tmp_path / "outside.md")


def test_root_symbolic_link_is_rejected(tmp_path: Path) -> None:
    real_root = tmp_path / "real"
    real_root.mkdir()
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(ValueError, match="symbolic"):
        validate_knowledge_path(
            linked_root,
            linked_root / "notes" / "a.md",
        )


def test_symbolic_link_component_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    linked = root / "notes"
    linked.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symbolic"):
        validate_knowledge_path(root, linked / "document.md")


def test_non_existing_safe_path_is_accepted(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    validate_knowledge_path(
        root,
        root / "notes" / f"review--{DOCUMENT_ID}.md",
    )


def test_non_path_values_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match=r"pathlib\.Path"):
        validate_knowledge_path(
            tmp_path / "knowledge",
            "/tmp/knowledge.md",  # type: ignore[arg-type]
        )
