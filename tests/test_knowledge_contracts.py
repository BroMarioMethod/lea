"""Tests for immutable Markdown knowledge contracts."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from lea.knowledge import (
    KNOWLEDGE_SCHEMA_VERSION,
    KnowledgeDocument,
    KnowledgeDocumentLink,
    KnowledgeDocumentType,
    KnowledgeExternalReference,
    KnowledgeQuery,
    KnowledgeRepositoryInspection,
    KnowledgeRepositoryIssue,
    KnowledgeSensitivity,
)

DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"
TARGET_ID = "22222222-2222-4222-8222-222222222222"
REFERENCE_ID = "33333333-3333-4333-8333-333333333333"
CREATED_AT = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)
UPDATED_AT = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)


def _document(**overrides: object) -> KnowledgeDocument:
    values: dict[str, object] = {
        "document_id": DOCUMENT_ID,
        "document_type": KnowledgeDocumentType.NOTE,
        "document_version": 1,
        "title": "Boiler efficiency review",
        "sensitivity": KnowledgeSensitivity.MEDIUM,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "body": "# Review\n\nHuman-authored knowledge.\n",
        "links": (),
        "external_references": (),
        "schema_version": KNOWLEDGE_SCHEMA_VERSION,
    }
    values.update(overrides)
    return KnowledgeDocument(**values)  # type: ignore[arg-type]


def test_document_types_are_stable_strings() -> None:
    assert tuple(item.value for item in KnowledgeDocumentType) == (
        "note",
        "person",
        "organisation",
        "project",
        "decision",
        "role",
    )


def test_sensitivity_values_are_stable_strings() -> None:
    assert tuple(item.value for item in KnowledgeSensitivity) == (
        "low",
        "medium",
        "critical",
    )


def test_document_preserves_body_and_canonicalises_collections() -> None:
    links = (
        KnowledgeDocumentLink(relation="supports", document_id=TARGET_ID),
        KnowledgeDocumentLink(relation="related", document_id=REFERENCE_ID),
    )
    references = (
        KnowledgeExternalReference(
            namespace="taskwarrior.task",
            identifier=REFERENCE_ID,
        ),
        KnowledgeExternalReference(
            namespace="lea.proposal",
            identifier=TARGET_ID,
        ),
    )

    document = _document(
        links=links,
        external_references=references,
    )

    assert document.body == "# Review\n\nHuman-authored knowledge.\n"
    assert document.links == tuple(sorted(links))
    assert document.external_references == tuple(sorted(references))


@pytest.mark.parametrize(
    "document_type",
    tuple(KnowledgeDocumentType),
)
def test_every_initial_document_type_is_accepted(
    document_type: KnowledgeDocumentType,
) -> None:
    assert _document(document_type=document_type).document_type is document_type


@pytest.mark.parametrize(
    "sensitivity",
    tuple(KnowledgeSensitivity),
)
def test_every_sensitivity_is_accepted(
    sensitivity: KnowledgeSensitivity,
) -> None:
    assert _document(sensitivity=sensitivity).sensitivity is sensitivity


@pytest.mark.parametrize(
    "document_id",
    (
        "11111111111141118111111111111111",
        "11111111-1111-4111-8111-11111111111A",
        "not-a-uuid",
    ),
)
def test_document_rejects_non_canonical_identifier(document_id: str) -> None:
    with pytest.raises(ValueError, match=r"canonical|valid UUID"):
        _document(document_id=document_id)


def test_document_rejects_unsupported_schema_version() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        _document(schema_version=2)


def test_document_rejects_non_positive_version() -> None:
    with pytest.raises(ValueError, match="document_version"):
        _document(document_version=0)


def test_document_rejects_empty_title() -> None:
    with pytest.raises(ValueError, match="title"):
        _document(title="   ")


def test_document_rejects_non_utc_timestamp() -> None:
    with pytest.raises(ValueError, match="UTC"):
        _document(updated_at=datetime.fromisoformat("2026-07-23T11:00:00+02:00"))


def test_document_rejects_updated_timestamp_before_creation() -> None:
    with pytest.raises(ValueError, match="earlier"):
        _document(updated_at=datetime(2026, 7, 23, 7, 59, tzinfo=UTC))


def test_document_rejects_self_link() -> None:
    with pytest.raises(ValueError, match="link to itself"):
        _document(
            links=(
                KnowledgeDocumentLink(
                    relation="related",
                    document_id=DOCUMENT_ID,
                ),
            )
        )


def test_document_rejects_duplicate_links() -> None:
    link = KnowledgeDocumentLink(
        relation="related",
        document_id=TARGET_ID,
    )

    with pytest.raises(ValueError, match="duplicates"):
        _document(links=(link, link))


def test_link_accepts_namespaced_relation() -> None:
    link = KnowledgeDocumentLink(
        relation="crm:customer",
        document_id=TARGET_ID,
    )

    assert link.relation == "crm:customer"


@pytest.mark.parametrize(
    "relation",
    ("Related", "related item", ":related", "related:"),
)
def test_link_rejects_invalid_relation(relation: str) -> None:
    with pytest.raises(ValueError, match="relation"):
        KnowledgeDocumentLink(
            relation=relation,
            document_id=TARGET_ID,
        )


def test_external_reference_rejects_unknown_namespace() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        KnowledgeExternalReference(
            namespace="unknown.record",
            identifier=REFERENCE_ID,
        )


def test_query_requires_complete_external_reference_filter() -> None:
    with pytest.raises(ValueError, match="supplied together"):
        KnowledgeQuery(
            external_reference_namespace="lea.proposal",
        )


def test_repository_issue_validates_absolute_path() -> None:
    with pytest.raises(ValueError, match="absolute"):
        KnowledgeRepositoryIssue(
            code="knowledge_invalid",
            message="Invalid knowledge document.",
            path=Path("relative.md"),
        )


def test_available_inspection_has_no_issues() -> None:
    inspection = KnowledgeRepositoryInspection(
        available=True,
        checked_documents=3,
        valid_documents=3,
        issues=(),
    )

    assert inspection.available is True


def test_unavailable_inspection_requires_issue() -> None:
    with pytest.raises(ValueError, match="at least one issue"):
        KnowledgeRepositoryInspection(
            available=False,
            checked_documents=0,
            valid_documents=0,
            issues=(),
        )
