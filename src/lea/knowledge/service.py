"""Audited application service for Markdown knowledge operations."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from lea.audit import (
    AuditEvent,
    AuditEventType,
    AuditSubjectType,
)
from lea.knowledge.contracts import (
    KnowledgeDocument,
    KnowledgeListResult,
    KnowledgeOperation,
    KnowledgeQuery,
    KnowledgeReadResult,
    KnowledgeReplaceResult,
    KnowledgeRepositoryInspection,
    KnowledgeServiceIssue,
    KnowledgeServiceResult,
    KnowledgeWriteResult,
)
from lea.knowledge.repository import MarkdownKnowledgeRepository

KnowledgeRepositoryResult = (
    KnowledgeWriteResult
    | KnowledgeReadResult
    | KnowledgeListResult
    | KnowledgeReplaceResult
    | KnowledgeRepositoryInspection
)


class KnowledgeAuditSink(Protocol):
    """Minimum append-only audit dependency required by knowledge services."""

    def append(self, event: AuditEvent) -> object:
        """Persist one immutable audit event."""
        ...


class KnowledgeUtcClock(Protocol):
    """Callable source of timezone-aware UTC timestamps."""

    def __call__(self) -> object:
        """Return one timestamp."""
        ...


class KnowledgeAuditEventIdSource(Protocol):
    """Callable source of canonical audit-event UUID strings."""

    def __call__(self) -> object:
        """Return one audit-event identifier."""
        ...


class KnowledgeOperationIdSource(Protocol):
    """Callable source of canonical repository-operation UUID strings."""

    def __call__(self) -> object:
        """Return one repository-operation identifier."""
        ...


class KnowledgeService:
    """Coordinate repository operations with mandatory audit attempts."""

    __slots__ = (
        "_audit_event_id_source",
        "_audit_sink",
        "_clock",
        "_operation_id_source",
        "_repository",
    )

    def __init__(
        self,
        repository: MarkdownKnowledgeRepository,
        audit_sink: KnowledgeAuditSink,
        clock: KnowledgeUtcClock,
        audit_event_id_source: KnowledgeAuditEventIdSource,
        operation_id_source: KnowledgeOperationIdSource,
    ) -> None:
        """Initialise the service with explicit deterministic dependencies."""
        self._repository = repository
        self._audit_sink = audit_sink
        self._clock = clock
        self._audit_event_id_source = audit_event_id_source
        self._operation_id_source = operation_id_source

    def create(self, document: KnowledgeDocument) -> KnowledgeServiceResult:
        """Create one document and audit the completed attempt."""
        return self._document_operation(
            KnowledgeOperation.CREATE,
            document.document_id,
            document=document,
            invoke=lambda: self._repository.create(document),
        )

    def read(self, document_id: str) -> KnowledgeServiceResult:
        """Read one document and audit the completed attempt."""
        return self._document_operation(
            KnowledgeOperation.READ,
            document_id,
            document=None,
            invoke=lambda: self._repository.read(document_id),
        )

    def replace(
        self,
        document: KnowledgeDocument,
        *,
        expected_version: int,
    ) -> KnowledgeServiceResult:
        """Replace one document and audit the completed attempt."""
        return self._document_operation(
            KnowledgeOperation.REPLACE,
            document.document_id,
            document=document,
            invoke=lambda: self._repository.replace(
                document,
                expected_version=expected_version,
            ),
        )

    def list(
        self,
        query: KnowledgeQuery | None = None,
    ) -> KnowledgeServiceResult:
        """List documents and audit the repository-wide attempt."""
        return self._repository_operation(
            KnowledgeOperation.LIST,
            invoke=lambda: self._repository.list(query),
        )

    def inspect(self) -> KnowledgeServiceResult:
        """Inspect the repository and audit the repository-wide attempt."""
        return self._repository_operation(
            KnowledgeOperation.INSPECT,
            invoke=self._repository.inspect,
        )

    def _document_operation(
        self,
        operation: KnowledgeOperation,
        document_id: str,
        *,
        document: KnowledgeDocument | None,
        invoke: object,
    ) -> KnowledgeServiceResult:
        """Run and audit one document-scoped repository operation."""
        try:
            repository_result = invoke()  # type: ignore[operator]
            operation_issue = None
        except Exception:
            repository_result = None
            operation_issue = KnowledgeServiceIssue(
                code="knowledge_operation_failed",
                message="The knowledge repository operation raised an exception.",
                operation=operation,
                subject_id=document_id,
            )

        return self._audit_result(
            operation,
            subject_type=AuditSubjectType.KNOWLEDGE_DOCUMENT,
            subject_id=document_id,
            repository_result=repository_result,
            operation_issue=operation_issue,
            document=document,
        )

    def _repository_operation(
        self,
        operation: KnowledgeOperation,
        *,
        invoke: object,
    ) -> KnowledgeServiceResult:
        """Run and audit one repository-scoped operation."""
        try:
            subject_id = self._next_uuid(
                self._operation_id_source,
                source_name="knowledge operation identifier source",
            )
        except Exception:
            return KnowledgeServiceResult(
                operation=operation,
                repository_result=None,
                persisted_event=None,
                issue=KnowledgeServiceIssue(
                    code="knowledge_operation_id_failed",
                    message=(
                        "A repository operation identifier could not be obtained."
                    ),
                    operation=operation,
                    subject_id=None,
                ),
            )

        try:
            repository_result = invoke()  # type: ignore[operator]
            operation_issue = None
        except Exception:
            repository_result = None
            operation_issue = KnowledgeServiceIssue(
                code="knowledge_operation_failed",
                message="The knowledge repository operation raised an exception.",
                operation=operation,
                subject_id=subject_id,
            )

        return self._audit_result(
            operation,
            subject_type=AuditSubjectType.KNOWLEDGE_REPOSITORY,
            subject_id=subject_id,
            repository_result=repository_result,
            operation_issue=operation_issue,
            document=None,
        )

    def _audit_result(
        self,
        operation: KnowledgeOperation,
        *,
        subject_type: AuditSubjectType,
        subject_id: str,
        repository_result: KnowledgeRepositoryResult | None,
        operation_issue: KnowledgeServiceIssue | None,
        document: KnowledgeDocument | None,
    ) -> KnowledgeServiceResult:
        """Create and persist one safe audit event."""
        try:
            event = AuditEvent(
                event_id=self._next_uuid(
                    self._audit_event_id_source,
                    source_name="knowledge audit-event identifier source",
                ),
                subject_type=subject_type,
                subject_id=subject_id,
                event_type=AuditEventType.KNOWLEDGE_OPERATION_COMPLETED,
                occurred_at=self._next_utc_timestamp(),
                payload=_audit_payload(
                    operation,
                    repository_result,
                    operation_issue=operation_issue,
                    document=document,
                ),
            )
        except Exception:
            return KnowledgeServiceResult(
                operation=operation,
                repository_result=repository_result,
                persisted_event=None,
                issue=KnowledgeServiceIssue(
                    code="knowledge_audit_event_failed",
                    message="The knowledge audit event could not be created.",
                    operation=operation,
                    subject_id=subject_id,
                ),
            )

        try:
            self._audit_sink.append(event)
        except Exception:
            return KnowledgeServiceResult(
                operation=operation,
                repository_result=repository_result,
                persisted_event=None,
                issue=KnowledgeServiceIssue(
                    code="audit_append_failed",
                    message="The knowledge audit event could not be persisted.",
                    operation=operation,
                    subject_id=subject_id,
                ),
            )

        return KnowledgeServiceResult(
            operation=operation,
            repository_result=repository_result,
            persisted_event=event,
            issue=operation_issue,
        )

    def _next_utc_timestamp(self) -> datetime:
        """Return one validated timezone-aware UTC timestamp."""
        value = self._clock()

        if not isinstance(value, datetime):
            raise ValueError("The knowledge clock must return a datetime.")

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "The knowledge clock must return a timezone-aware datetime."
            )

        if value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("The knowledge clock must return a UTC datetime.")

        return value.astimezone(UTC)

    @staticmethod
    def _next_uuid(source: object, *, source_name: str) -> str:
        """Return one validated canonical UUID from a callable source."""
        value = source()  # type: ignore[operator]

        if not isinstance(value, str):
            raise ValueError(f"The {source_name} must return a string.")

        try:
            parsed = UUID(value)
        except ValueError as error:
            raise ValueError(f"The {source_name} must return a valid UUID.") from error

        if str(parsed) != value:
            raise ValueError(
                f"The {source_name} must return a canonical lower-case UUID."
            )

        return value


def _audit_payload(
    operation: KnowledgeOperation,
    repository_result: KnowledgeRepositoryResult | None,
    *,
    operation_issue: KnowledgeServiceIssue | None,
    document: KnowledgeDocument | None,
) -> Mapping[str, object]:
    """Return safe audit metadata without knowledge content or paths."""
    issue_codes: tuple[str, ...]

    if operation_issue is not None:
        issue_codes = (operation_issue.code,)
    else:
        issue_codes = _repository_issue_codes(repository_result)

    payload: dict[str, object] = {
        "operation": operation.value,
        "success": _repository_success(repository_result),
        "issue_codes": list(issue_codes),
        "issue_count": len(issue_codes),
    }

    metadata_document = _result_document(repository_result) or document

    if metadata_document is not None:
        payload.update(
            {
                "document_id": metadata_document.document_id,
                "document_type": metadata_document.document_type.value,
                "document_version": metadata_document.document_version,
                "sensitivity": metadata_document.sensitivity.value,
            }
        )

    if isinstance(repository_result, KnowledgeListResult):
        payload["document_count"] = len(repository_result.documents)

    if isinstance(repository_result, KnowledgeRepositoryInspection):
        payload.update(
            {
                "available": repository_result.available,
                "checked_documents": repository_result.checked_documents,
                "valid_documents": repository_result.valid_documents,
            }
        )

    return payload


def _repository_success(
    result: KnowledgeRepositoryResult | None,
) -> bool:
    """Return the operation success represented by a repository result."""
    if result is None:
        return False

    if isinstance(result, KnowledgeRepositoryInspection):
        return result.available and not result.issues

    return result.success


def _repository_issue_codes(
    result: KnowledgeRepositoryResult | None,
) -> tuple[str, ...]:
    """Return deterministic repository issue codes."""
    if result is None:
        return ()

    return tuple(issue.code for issue in result.issues)


def _result_document(
    result: KnowledgeRepositoryResult | None,
) -> KnowledgeDocument | None:
    """Return safe document metadata from a result when available."""
    if isinstance(
        result,
        (KnowledgeWriteResult, KnowledgeReadResult, KnowledgeReplaceResult),
    ):
        return result.document

    return None
