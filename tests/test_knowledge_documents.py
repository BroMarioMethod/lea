"""Tests for deterministic Markdown knowledge documents."""

from datetime import UTC, datetime

import pytest

from lea.knowledge import (
    KnowledgeDocument,
    KnowledgeDocumentLink,
    KnowledgeDocumentType,
    KnowledgeExternalReference,
    KnowledgeSensitivity,
    parse_knowledge_document,
    render_knowledge_document,
)

DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"
TARGET_ID = "22222222-2222-4222-8222-222222222222"
REFERENCE_ID = "33333333-3333-4333-8333-333333333333"


def _document(
    *,
    body: str = "# Boiler review\n\nHuman and AI knowledge.\n",
    document_type: KnowledgeDocumentType = KnowledgeDocumentType.NOTE,
) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=DOCUMENT_ID,
        document_type=document_type,
        document_version=1,
        title='Boiler "efficiency" review',
        sensitivity=KnowledgeSensitivity.MEDIUM,
        created_at=datetime(2026, 7, 23, 8, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 23, 9, 0, tzinfo=UTC),
        body=body,
        links=(
            KnowledgeDocumentLink(
                relation="related",
                document_id=TARGET_ID,
            ),
        ),
        external_references=(
            KnowledgeExternalReference(
                namespace="taskwarrior.task",
                identifier=REFERENCE_ID,
            ),
        ),
    )


def test_round_trip_preserves_document_and_body() -> None:
    source = _document()
    result = parse_knowledge_document(render_knowledge_document(source))

    assert result.success is True
    assert result.document == source
    assert result.document is not None
    assert result.document.body == source.body


@pytest.mark.parametrize("document_type", tuple(KnowledgeDocumentType))
def test_every_document_type_round_trips(
    document_type: KnowledgeDocumentType,
) -> None:
    source = _document(document_type=document_type)
    result = parse_knowledge_document(render_knowledge_document(source))
    assert result.document == source


def test_canonical_front_matter_and_collections() -> None:
    rendered = render_knowledge_document(_document())

    assert rendered.startswith(
        "---\n"
        "schema_version: 1\n"
        f"document_id: {DOCUMENT_ID}\n"
        "document_type: note\n"
        "document_version: 1\n"
        'title: "Boiler \\"efficiency\\" review"\n'
        "sensitivity: medium\n"
        "created_at: 2026-07-23T08:00:00Z\n"
        "updated_at: 2026-07-23T09:00:00Z\n"
    )
    assert (
        f'links: [{{"document_id":"{TARGET_ID}","relation":"related"}}]\n' in rendered
    )
    assert (
        "external_references: "
        f'[{{"identifier":"{REFERENCE_ID}",'
        '"namespace":"taskwarrior.task"}]\n' in rendered
    )


def test_empty_body_round_trips() -> None:
    source = _document(body="")
    result = parse_knowledge_document(render_knowledge_document(source))
    assert result.document == source


def test_body_trailing_newlines_are_canonicalised() -> None:
    rendered = render_knowledge_document(_document(body="Body\n\n\n"))
    assert rendered.endswith("---\nBody\n")


@pytest.mark.parametrize(
    ("change", "code"),
    (
        (
            lambda value: value.rstrip("\n"),
            "knowledge_malformed_document",
        ),
        (
            lambda value: value.replace("\n", "\r\n"),
            "knowledge_non_canonical_document",
        ),
        (
            lambda value: value.replace(
                "document_type: note\n",
                "document_type: note\nunexpected: value\n",
            ),
            "knowledge_front_matter_unknown_key",
        ),
        (
            lambda value: value.replace(
                "document_type: note\n",
                "document_type: note\ndocument_type: note\n",
            ),
            "knowledge_front_matter_duplicate_key",
        ),
        (
            lambda value: value.replace("sensitivity: medium\n", ""),
            "knowledge_required_field_missing",
        ),
        (
            lambda value: value.replace(
                "document_type: note\ndocument_version: 1\n",
                "document_version: 1\ndocument_type: note\n",
            ),
            "knowledge_non_canonical_document",
        ),
        (
            lambda value: value.replace(
                "schema_version: 1",
                "schema_version: 2",
            ),
            "knowledge_schema_unsupported",
        ),
        (
            lambda value: value.replace(
                "sensitivity: medium",
                "sensitivity: secret",
            ),
            "knowledge_invalid_contract",
        ),
        (
            lambda value: value.replace(
                "created_at: 2026-07-23T08:00:00Z",
                "created_at: 2026-07-23T08:00:00+00:00",
            ),
            "knowledge_invalid_contract",
        ),
        (
            lambda value: value.replace(
                '"relation":"related"',
                '"relation": "related"',
            ),
            "knowledge_non_canonical_document",
        ),
    ),
)
def test_invalid_documents_fail_with_stable_code(
    change: object,
    code: str,
) -> None:
    rendered = render_knowledge_document(_document())
    changed = change(rendered)  # type: ignore[operator]
    result = parse_knowledge_document(changed)
    assert result.success is False
    assert result.issues[0].code == code


def test_missing_and_unclosed_front_matter_are_distinct() -> None:
    missing = parse_knowledge_document("# Knowledge\n")
    unclosed = parse_knowledge_document("---\nschema_version: 1\n")

    assert missing.issues[0].code == "knowledge_front_matter_missing"
    assert unclosed.issues[0].code == "knowledge_front_matter_unclosed"


def test_non_string_input_raises_type_error() -> None:
    with pytest.raises(TypeError, match="string"):
        parse_knowledge_document(123)  # type: ignore[arg-type]
