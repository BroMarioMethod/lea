"""Deterministic Markdown serialisation for knowledge documents."""

from __future__ import annotations

import json
from datetime import datetime
from typing import cast

from lea.knowledge.contracts import (
    KNOWLEDGE_SCHEMA_VERSION,
    KnowledgeDocument,
    KnowledgeDocumentLink,
    KnowledgeDocumentResult,
    KnowledgeDocumentType,
    KnowledgeExternalReference,
    KnowledgeRepositoryIssue,
    KnowledgeSensitivity,
)

_FIELDS = (
    "schema_version",
    "document_id",
    "document_type",
    "document_version",
    "title",
    "sensitivity",
    "created_at",
    "updated_at",
    "links",
    "external_references",
)
_FIELD_SET = frozenset(_FIELDS)


def render_knowledge_document(document: KnowledgeDocument) -> str:
    """Render one knowledge document as canonical Markdown."""
    body = document.body.rstrip("\n")
    lines = [
        "---",
        f"schema_version: {document.schema_version}",
        f"document_id: {document.document_id}",
        f"document_type: {document.document_type.value}",
        f"document_version: {document.document_version}",
        f"title: {json.dumps(document.title, ensure_ascii=False)}",
        f"sensitivity: {document.sensitivity.value}",
        f"created_at: {_render_timestamp(document.created_at)}",
        f"updated_at: {_render_timestamp(document.updated_at)}",
        f"links: {_render_links(document.links)}",
        f"external_references: {_render_references(document.external_references)}",
        "---",
        body,
    ]
    return "\n".join(lines) + "\n"


def parse_knowledge_document(document: str) -> KnowledgeDocumentResult:
    """Parse one untrusted Markdown knowledge document."""
    if not isinstance(document, str):
        raise TypeError("document must be a string.")

    if "\r" in document:
        return _failure(
            "knowledge_non_canonical_document",
            "Knowledge documents must use LF line endings.",
        )

    if not document.endswith("\n"):
        return _failure(
            "knowledge_malformed_document",
            "The knowledge document must end with a newline.",
        )

    parsed = _parse_front_matter(document.splitlines())
    if isinstance(parsed, KnowledgeDocumentResult):
        return parsed

    values, body_start, lines = parsed
    body_text = "\n".join(lines[body_start:])
    body = f"{body_text}\n" if body_text else ""

    try:
        knowledge = KnowledgeDocument(
            schema_version=cast(int, values["schema_version"]),
            document_id=cast(str, values["document_id"]),
            document_type=KnowledgeDocumentType(cast(str, values["document_type"])),
            document_version=cast(int, values["document_version"]),
            title=cast(str, values["title"]),
            sensitivity=KnowledgeSensitivity(cast(str, values["sensitivity"])),
            created_at=_parse_timestamp(
                cast(str, values["created_at"]),
                field="created_at",
            ),
            updated_at=_parse_timestamp(
                cast(str, values["updated_at"]),
                field="updated_at",
            ),
            links=_parse_links(values["links"]),
            external_references=_parse_references(values["external_references"]),
            body=body,
        )
    except (TypeError, ValueError) as error:
        return _failure("knowledge_invalid_contract", str(error))

    if render_knowledge_document(knowledge) != document:
        return _failure(
            "knowledge_non_canonical_document",
            "The knowledge document is valid but is not canonical.",
            document_id=knowledge.document_id,
        )

    return KnowledgeDocumentResult(True, knowledge, ())


def _parse_front_matter(
    lines: list[str],
) -> tuple[dict[str, object], int, list[str]] | KnowledgeDocumentResult:
    if not lines or lines[0] != "---":
        return _failure(
            "knowledge_front_matter_missing",
            "The knowledge document must begin with front matter.",
            line_number=1,
        )

    try:
        closing = lines.index("---", 1)
    except ValueError:
        return _failure(
            "knowledge_front_matter_unclosed",
            "The knowledge front matter is not closed.",
            line_number=1,
        )

    values: dict[str, object] = {}
    for line_number, line in enumerate(lines[1:closing], start=2):
        if ": " not in line:
            return _failure(
                "knowledge_front_matter_malformed",
                "Front-matter fields must use 'name: value'.",
                line_number=line_number,
            )

        field, value = line.split(": ", 1)
        if field in values:
            return _failure(
                "knowledge_front_matter_duplicate_key",
                f"Front-matter field '{field}' is duplicated.",
                field=field,
                line_number=line_number,
            )

        if field not in _FIELD_SET:
            return _failure(
                "knowledge_front_matter_unknown_key",
                f"Unknown front-matter field '{field}' is not permitted.",
                field=field,
                line_number=line_number,
            )

        parsed_value = _parse_value(field, value)
        if isinstance(parsed_value, KnowledgeDocumentResult):
            return parsed_value
        values[field] = parsed_value

    missing = [field for field in _FIELDS if field not in values]
    if missing:
        return _failure(
            "knowledge_required_field_missing",
            f"Required front-matter field '{missing[0]}' is missing.",
            field=missing[0],
        )

    if tuple(values) != _FIELDS:
        return _failure(
            "knowledge_non_canonical_document",
            "Knowledge front-matter fields are not in canonical order.",
        )

    if values["schema_version"] != KNOWLEDGE_SCHEMA_VERSION:
        return _failure(
            "knowledge_schema_unsupported",
            "The knowledge document schema version is unsupported.",
            field="schema_version",
        )

    return values, closing + 1, lines


def _parse_value(
    field: str,
    value: str,
) -> object | KnowledgeDocumentResult:
    if field in {"schema_version", "document_version"}:
        try:
            return int(value)
        except ValueError:
            return value

    if field == "title":
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return _failure(
                "knowledge_front_matter_malformed",
                "The title must be a JSON string scalar.",
                field=field,
            )
        if not isinstance(parsed, str):
            return _failure(
                "knowledge_front_matter_malformed",
                "The title must be a JSON string scalar.",
                field=field,
            )
        return parsed

    if field in {"links", "external_references"}:
        try:
            parsed_collection = json.loads(value)
        except json.JSONDecodeError:
            return _failure(
                "knowledge_front_matter_malformed",
                f"The {field} field must contain valid compact JSON.",
                field=field,
            )
        if not isinstance(parsed_collection, list):
            return _failure(
                "knowledge_front_matter_malformed",
                f"The {field} field must be a JSON array.",
                field=field,
            )
        return parsed_collection

    return value


def _parse_links(value: object) -> tuple[KnowledgeDocumentLink, ...]:
    if not isinstance(value, list):
        raise ValueError("links must be a list.")

    result: list[KnowledgeDocumentLink] = []
    for item in value:
        if not isinstance(item, dict) or tuple(item) != (
            "document_id",
            "relation",
        ):
            raise ValueError(
                "Each link must contain canonical document_id and relation fields."
            )
        result.append(
            KnowledgeDocumentLink(
                relation=cast(str, item["relation"]),
                document_id=cast(str, item["document_id"]),
            )
        )
    return tuple(result)


def _parse_references(
    value: object,
) -> tuple[KnowledgeExternalReference, ...]:
    if not isinstance(value, list):
        raise ValueError("external_references must be a list.")

    result: list[KnowledgeExternalReference] = []
    for item in value:
        if not isinstance(item, dict) or tuple(item) != (
            "identifier",
            "namespace",
        ):
            raise ValueError(
                "Each external reference must contain canonical identifier "
                "and namespace fields."
            )
        result.append(
            KnowledgeExternalReference(
                namespace=cast(str, item["namespace"]),
                identifier=cast(str, item["identifier"]),
            )
        )
    return tuple(result)


def _render_links(links: tuple[KnowledgeDocumentLink, ...]) -> str:
    return json.dumps(
        [
            {"document_id": item.document_id, "relation": item.relation}
            for item in links
        ],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _render_references(
    references: tuple[KnowledgeExternalReference, ...],
) -> str:
    return json.dumps(
        [
            {"identifier": item.identifier, "namespace": item.namespace}
            for item in references
        ],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _render_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str, *, field: str) -> datetime:
    if not value.endswith("Z"):
        raise ValueError(f"{field} must use a canonical UTC Z suffix.")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if _render_timestamp(parsed) != value:
        raise ValueError(f"{field} must use canonical RFC 3339 text.")
    return parsed


def _failure(
    code: str,
    message: str,
    *,
    document_id: str | None = None,
    field: str | None = None,
    line_number: int | None = None,
) -> KnowledgeDocumentResult:
    return KnowledgeDocumentResult(
        False,
        None,
        (
            KnowledgeRepositoryIssue(
                code=code,
                message=message,
                document_id=document_id,
                field=field,
                line_number=line_number,
            ),
        ),
    )
