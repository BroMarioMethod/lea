"""Immutable contracts for Markdown knowledge documents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID

KNOWLEDGE_SCHEMA_VERSION = 1

_RELATION_PATTERN = re.compile(
    r"^(?:[a-z][a-z0-9_]*|[a-z][a-z0-9_.-]*:[a-z][a-z0-9_.-]*)$"
)
_NAMESPACE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$")
_SUPPORTED_EXTERNAL_REFERENCE_NAMESPACES = frozenset(
    {
        "lea.audit_event",
        "lea.proposal",
        "taskwarrior.task",
    }
)


class KnowledgeDocumentType(StrEnum):
    """Supported canonical Markdown knowledge-document types."""

    NOTE = "note"
    PERSON = "person"
    ORGANISATION = "organisation"
    PROJECT = "project"
    DECISION = "decision"
    ROLE = "role"


class KnowledgeSensitivity(StrEnum):
    """Supported knowledge sensitivity classifications."""

    LOW = "low"
    MEDIUM = "medium"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True, order=True)
class KnowledgeDocumentLink:
    """One immutable link to another knowledge document."""

    relation: str
    document_id: str

    def __post_init__(self) -> None:
        """Validate the link relation and target identifier."""
        if not _RELATION_PATTERN.fullmatch(self.relation):
            raise ValueError(
                "relation must be a lowercase core identifier or a valid "
                "namespaced identifier."
            )

        _validate_uuid(self.document_id, field_name="document_id")


@dataclass(frozen=True, slots=True, order=True)
class KnowledgeExternalReference:
    """One immutable reference owned by another LEA subsystem."""

    namespace: str
    identifier: str

    def __post_init__(self) -> None:
        """Validate the external-reference namespace and identifier."""
        if not _NAMESPACE_PATTERN.fullmatch(self.namespace):
            raise ValueError(
                "namespace must be a canonical lowercase namespace identifier."
            )

        if self.namespace not in _SUPPORTED_EXTERNAL_REFERENCE_NAMESPACES:
            raise ValueError(
                f"Unsupported external-reference namespace: {self.namespace}."
            )

        _validate_uuid(self.identifier, field_name="identifier")


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    """One immutable canonical Markdown knowledge document."""

    document_id: str
    document_type: KnowledgeDocumentType
    document_version: int
    title: str
    sensitivity: KnowledgeSensitivity
    created_at: datetime
    updated_at: datetime
    body: str = ""
    links: tuple[KnowledgeDocumentLink, ...] = ()
    external_references: tuple[KnowledgeExternalReference, ...] = ()
    schema_version: int = KNOWLEDGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Validate and canonicalise one knowledge document."""
        _validate_uuid(self.document_id, field_name="document_id")

        if self.schema_version != KNOWLEDGE_SCHEMA_VERSION:
            raise ValueError(
                "schema_version must equal the supported knowledge schema version."
            )

        if self.document_version < 1:
            raise ValueError("document_version must be greater than zero.")

        if not self.title.strip():
            raise ValueError("title must be non-empty.")

        _validate_utc_datetime(self.created_at, field_name="created_at")
        _validate_utc_datetime(self.updated_at, field_name="updated_at")

        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at.")

        if "\x00" in self.body:
            raise ValueError("body must not contain NUL characters.")

        canonical_links = tuple(sorted(self.links))
        if len(canonical_links) != len(set(canonical_links)):
            raise ValueError("links must not contain duplicates.")

        for link in canonical_links:
            if link.document_id == self.document_id:
                raise ValueError("A knowledge document must not link to itself.")

        canonical_references = tuple(sorted(self.external_references))
        if len(canonical_references) != len(set(canonical_references)):
            raise ValueError("external_references must not contain duplicates.")

        object.__setattr__(self, "links", canonical_links)
        object.__setattr__(
            self,
            "external_references",
            canonical_references,
        )


@dataclass(frozen=True, slots=True)
class KnowledgeRepositoryIssue:
    """One structured knowledge-repository problem."""

    code: str
    message: str
    document_id: str | None = None
    path: Path | None = None
    field: str | None = None
    line_number: int | None = None
    expected_version: int | None = None
    actual_version: int | None = None

    def __post_init__(self) -> None:
        """Validate repository-issue fields."""
        if not self.code.strip():
            raise ValueError("Knowledge repository issue code must be non-empty.")

        if not self.message.strip():
            raise ValueError("Knowledge repository issue message must be non-empty.")

        if self.document_id is not None:
            _validate_uuid(self.document_id, field_name="document_id")

        if self.path is not None and not self.path.is_absolute():
            raise ValueError("path must be absolute when provided.")

        if self.field is not None and not self.field.strip():
            raise ValueError("field must be non-empty when provided.")

        if self.line_number is not None and self.line_number < 1:
            raise ValueError("line_number must be greater than zero.")

        for field_name, value in (
            ("expected_version", self.expected_version),
            ("actual_version", self.actual_version),
        ):
            if value is not None and value < 1:
                raise ValueError(f"{field_name} must be greater than zero.")


@dataclass(frozen=True, slots=True)
class KnowledgeDocumentResult:
    """Immutable result of parsing one Markdown knowledge document."""

    success: bool
    document: KnowledgeDocument | None
    issues: tuple[KnowledgeRepositoryIssue, ...]

    def __post_init__(self) -> None:
        """Validate knowledge-document result consistency."""
        if self.success:
            if self.document is None:
                raise ValueError(
                    "A successful knowledge document result must contain a document."
                )
            if self.issues:
                raise ValueError(
                    "A successful knowledge document result must not contain issues."
                )
            return

        if self.document is not None:
            raise ValueError(
                "A failed knowledge document result must not contain a document."
            )
        if not self.issues:
            raise ValueError(
                "A failed knowledge document result must contain at least one issue."
            )


@dataclass(frozen=True, slots=True)
class KnowledgeWriteResult:
    """Immutable result of creating one knowledge document."""

    success: bool
    document: KnowledgeDocument | None
    path: Path | None
    issues: tuple[KnowledgeRepositoryIssue, ...]

    def __post_init__(self) -> None:
        if self.success:
            if self.document is None or self.path is None or self.issues:
                raise ValueError(
                    "Successful knowledge writes require document and path."
                )
            if not self.path.is_absolute():
                raise ValueError("path must be absolute.")
            return

        if self.document is not None or not self.issues:
            raise ValueError("Failed knowledge writes require issues and no document.")


@dataclass(frozen=True, slots=True)
class KnowledgeReadResult:
    """Immutable result of reading one knowledge document."""

    success: bool
    document: KnowledgeDocument | None
    path: Path | None
    issues: tuple[KnowledgeRepositoryIssue, ...]

    def __post_init__(self) -> None:
        if self.success:
            if self.document is None or self.path is None or self.issues:
                raise ValueError(
                    "Successful knowledge reads require document and path."
                )
            if not self.path.is_absolute():
                raise ValueError("path must be absolute.")
            return

        if self.document is not None or not self.issues:
            raise ValueError("Failed knowledge reads require issues and no document.")


@dataclass(frozen=True, slots=True)
class KnowledgeListResult:
    """Immutable result of listing knowledge documents."""

    success: bool
    documents: tuple[KnowledgeDocument, ...]
    issues: tuple[KnowledgeRepositoryIssue, ...]

    def __post_init__(self) -> None:
        if self.success and self.issues:
            raise ValueError("Successful knowledge lists must not contain issues.")

        if not self.success and (self.documents or not self.issues):
            raise ValueError("Failed knowledge lists require issues and no documents.")


@dataclass(frozen=True, slots=True)
class KnowledgeReplaceResult:
    """Immutable result of replacing one knowledge document."""

    success: bool
    document: KnowledgeDocument | None
    previous_document: KnowledgeDocument | None
    path: Path | None
    previous_path: Path | None
    issues: tuple[KnowledgeRepositoryIssue, ...]

    def __post_init__(self) -> None:
        if self.success:
            if (
                self.document is None
                or self.previous_document is None
                or self.path is None
                or self.previous_path is None
                or self.issues
            ):
                raise ValueError(
                    "Successful knowledge replacements require both "
                    "documents and both paths."
                )

            if not self.path.is_absolute() or not self.previous_path.is_absolute():
                raise ValueError("Replacement paths must be absolute.")

            return

        if self.document is not None or not self.issues:
            raise ValueError(
                "Failed knowledge replacements require issues and no document."
            )


@dataclass(frozen=True, slots=True)
class KnowledgeQuery:
    """Immutable exact-match knowledge repository query."""

    document_id: str | None = None
    document_type: KnowledgeDocumentType | None = None
    sensitivity: KnowledgeSensitivity | None = None
    link_target_id: str | None = None
    external_reference_namespace: str | None = None
    external_reference_identifier: str | None = None

    def __post_init__(self) -> None:
        """Validate exact supported query filters."""
        if self.document_id is not None:
            _validate_uuid(self.document_id, field_name="document_id")

        if self.link_target_id is not None:
            _validate_uuid(self.link_target_id, field_name="link_target_id")

        namespace = self.external_reference_namespace
        identifier = self.external_reference_identifier

        if (namespace is None) is not (identifier is None):
            raise ValueError(
                "external_reference_namespace and "
                "external_reference_identifier must be supplied together."
            )

        if namespace is not None:
            if namespace not in _SUPPORTED_EXTERNAL_REFERENCE_NAMESPACES:
                raise ValueError(
                    f"Unsupported external-reference namespace: {namespace}."
                )

            assert identifier is not None
            _validate_uuid(
                identifier,
                field_name="external_reference_identifier",
            )


@dataclass(frozen=True, slots=True)
class KnowledgeRepositoryInspection:
    """Immutable result of inspecting one knowledge repository."""

    available: bool
    checked_documents: int
    valid_documents: int
    issues: tuple[KnowledgeRepositoryIssue, ...]

    def __post_init__(self) -> None:
        """Validate repository-inspection consistency."""
        if self.checked_documents < 0:
            raise ValueError("checked_documents must not be negative.")

        if self.valid_documents < 0:
            raise ValueError("valid_documents must not be negative.")

        if self.valid_documents > self.checked_documents:
            raise ValueError("valid_documents must not exceed checked_documents.")

        if not self.available and not self.issues:
            raise ValueError(
                "An unavailable knowledge repository must contain at least one issue."
            )


def _validate_uuid(value: str, *, field_name: str) -> None:
    """Validate one canonical lowercase hyphenated UUID."""
    try:
        parsed = UUID(value)
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid UUID.") from exc

    if str(parsed) != value:
        raise ValueError(
            f"{field_name} must use canonical lowercase hyphenated UUID text."
        )


def _validate_utc_datetime(value: datetime, *, field_name: str) -> None:
    """Validate one timezone-aware UTC datetime."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")

    if value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{field_name} must use UTC.")
