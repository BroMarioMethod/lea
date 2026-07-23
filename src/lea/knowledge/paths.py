"""Deterministic filenames and safe paths for knowledge documents."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from lea.knowledge.contracts import KnowledgeDocument, KnowledgeDocumentType

_SLUG_MAX_LENGTH = 80
_FALLBACK_SLUG = "document"
_TYPE_DIRECTORIES = {
    KnowledgeDocumentType.NOTE: "notes",
    KnowledgeDocumentType.PERSON: "people",
    KnowledgeDocumentType.ORGANISATION: "organisations",
    KnowledgeDocumentType.PROJECT: "projects",
    KnowledgeDocumentType.DECISION: "decisions",
    KnowledgeDocumentType.ROLE: "roles",
}
_IDENTIFIER_SUFFIX_PATTERN = re.compile(
    r"--([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})\.md$"
)


def knowledge_document_slug(title: str) -> str:
    """Return one deterministic lowercase ASCII slug."""
    if not isinstance(title, str):
        raise TypeError("title must be a string.")

    normalised = unicodedata.normalize("NFKD", title)
    ascii_text = normalised.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.casefold()).strip("-")
    slug = slug[:_SLUG_MAX_LENGTH].rstrip("-")
    return slug or _FALLBACK_SLUG


def knowledge_document_filename(document: KnowledgeDocument) -> str:
    """Return the deterministic canonical filename for one document."""
    return f"{knowledge_document_slug(document.title)}--{document.document_id}.md"


def knowledge_document_type_directory(
    document_type: KnowledgeDocumentType,
) -> str:
    """Return the canonical directory name for one document type."""
    try:
        return _TYPE_DIRECTORIES[document_type]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported knowledge document type: {document_type!r}."
        ) from exc


def knowledge_document_path(
    root: Path,
    document: KnowledgeDocument,
) -> Path:
    """Return the canonical absolute path for one document."""
    _validate_root(root)

    destination = (
        root
        / knowledge_document_type_directory(document.document_type)
        / knowledge_document_filename(document)
    )
    validate_knowledge_path(root, destination)
    return destination


def validate_knowledge_path(root: Path, path: Path) -> None:
    """Validate one path without following symbolic links."""
    _validate_root(root)

    if not isinstance(path, Path):
        raise TypeError("path must be a pathlib.Path value.")

    if not path.is_absolute():
        raise ValueError("path must be an absolute path.")

    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            "path must remain inside the configured knowledge root."
        ) from exc

    if not relative.parts:
        raise ValueError("path must identify an item inside the knowledge root.")

    current = root
    for part in relative.parts:
        if part in {"", ".", ".."}:
            raise ValueError("path must not contain traversal components.")

        current = current / part
        if current.is_symlink():
            raise ValueError("Knowledge paths must not use symbolic links.")


def knowledge_document_id_from_filename(filename: str) -> str:
    """Return the identifier suffix from one canonical Markdown filename."""
    if not isinstance(filename, str):
        raise TypeError("filename must be a string.")

    match = _IDENTIFIER_SUFFIX_PATTERN.search(filename)
    if match is None:
        raise ValueError(
            "filename must end with a canonical knowledge document identifier."
        )

    return match.group(1)


def _validate_root(root: Path) -> None:
    """Validate one configured knowledge root."""
    if not isinstance(root, Path):
        raise TypeError("root must be a pathlib.Path value.")

    if not root.is_absolute():
        raise ValueError("root must be an absolute path.")

    current = Path(root.anchor)
    for part in root.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise ValueError(
                "Knowledge root must not contain symbolic-link components."
            )
