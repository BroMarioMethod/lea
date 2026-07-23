"""Tests for the audited Markdown knowledge service."""

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from lea.audit import AuditEvent, AuditEventType, AuditSubjectType
from lea.knowledge import (
    KnowledgeDocument,
    KnowledgeDocumentType,
    KnowledgeOperation,
    KnowledgeReadResult,
    KnowledgeReplaceResult,
    KnowledgeSensitivity,
    KnowledgeService,
    KnowledgeWriteResult,
    MarkdownKnowledgeRepository,
)

DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"
EVENT_ID = "21111111-1111-4111-8111-111111111111"
OPERATION_ID = "31111111-1111-4111-8111-111111111111"
NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


class SequenceSource:
    """Return deterministic values in order."""

    def __init__(self, values: tuple[object, ...]) -> None:
        self._values = iter(values)

    def __call__(self) -> object:
        return next(self._values)


class RecordingAuditSink:
    """Record or reject appended audit events."""

    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[AuditEvent] = []
        self.fail = fail

    def append(self, event: AuditEvent) -> None:
        if self.fail:
            raise OSError("Simulated audit failure.")

        self.events.append(event)


def _document(version: int = 1) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=DOCUMENT_ID,
        document_type=KnowledgeDocumentType.NOTE,
        document_version=version,
        title="Sensitive client title",
        sensitivity=KnowledgeSensitivity.CRITICAL,
        created_at=NOW,
        updated_at=NOW,
        body="# Secret body\n",
    )


def _service(
    tmp_path: Path,
    sink: RecordingAuditSink,
    *,
    event_ids: tuple[object, ...] = (EVENT_ID,),
    operation_ids: tuple[object, ...] = (OPERATION_ID,),
    clock_values: tuple[object, ...] = (NOW,),
) -> KnowledgeService:
    return KnowledgeService(
        MarkdownKnowledgeRepository(
            tmp_path / "knowledge",
            create_parents=True,
        ),
        sink,
        SequenceSource(clock_values),
        SequenceSource(event_ids),
        SequenceSource(operation_ids),
    )


def test_create_persists_document_scoped_audit_event(tmp_path: Path) -> None:
    sink = RecordingAuditSink()

    result = _service(tmp_path, sink).create(_document())

    repository_result = cast(
        KnowledgeWriteResult,
        result.repository_result,
    )
    assert repository_result.success is True
    assert result.persisted_event == sink.events[0]
    assert result.issue is None
    assert sink.events[0].subject_type is AuditSubjectType.KNOWLEDGE_DOCUMENT
    assert sink.events[0].subject_id == DOCUMENT_ID
    assert sink.events[0].event_type is AuditEventType.KNOWLEDGE_OPERATION_COMPLETED
    assert sink.events[0].payload["operation"] == "create"


def test_repository_failure_is_still_audited(tmp_path: Path) -> None:
    sink = RecordingAuditSink()
    service = _service(
        tmp_path,
        sink,
        event_ids=(EVENT_ID, "22222222-2222-4222-8222-222222222222"),
        clock_values=(NOW, NOW),
    )

    assert service.create(_document()).repository_result is not None
    result = service.create(_document())

    repository_result = cast(
        KnowledgeWriteResult,
        result.repository_result,
    )
    assert repository_result.success is False
    assert result.issue is None
    assert result.persisted_event is sink.events[1]
    assert sink.events[1].payload["success"] is False
    assert sink.events[1].payload["issue_codes"] == ("knowledge_duplicate_id",)


def test_read_failure_is_audited(tmp_path: Path) -> None:
    sink = RecordingAuditSink()

    result = _service(tmp_path, sink).read(DOCUMENT_ID)

    repository_result = cast(
        KnowledgeReadResult,
        result.repository_result,
    )
    assert repository_result.success is False
    assert result.issue is None
    assert sink.events[0].payload["operation"] == "read"
    assert sink.events[0].payload["success"] is False


def test_list_uses_repository_operation_identifier(tmp_path: Path) -> None:
    sink = RecordingAuditSink()

    result = _service(tmp_path, sink).list()

    assert result.operation is KnowledgeOperation.LIST
    assert result.persisted_event is sink.events[0]
    assert sink.events[0].subject_type is AuditSubjectType.KNOWLEDGE_REPOSITORY
    assert sink.events[0].subject_id == OPERATION_ID
    assert sink.events[0].payload["document_count"] == 0


def test_inspection_uses_repository_subject(tmp_path: Path) -> None:
    sink = RecordingAuditSink()

    result = _service(tmp_path, sink).inspect()

    assert result.persisted_event is sink.events[0]
    assert sink.events[0].subject_type is AuditSubjectType.KNOWLEDGE_REPOSITORY
    assert sink.events[0].payload["operation"] == "inspect"
    assert sink.events[0].payload["available"] is False


def test_audit_payload_excludes_sensitive_content_and_paths(
    tmp_path: Path,
) -> None:
    sink = RecordingAuditSink()

    _service(tmp_path, sink).create(_document())

    encoded = repr(dict(sink.events[0].payload))

    assert "Secret body" not in encoded
    assert "Sensitive client title" not in encoded
    assert str(tmp_path) not in encoded
    assert "links" not in encoded
    assert "external_references" not in encoded


def test_audit_append_failure_preserves_repository_result(
    tmp_path: Path,
) -> None:
    sink = RecordingAuditSink(fail=True)

    result = _service(tmp_path, sink).create(_document())

    repository_result = cast(
        KnowledgeWriteResult,
        result.repository_result,
    )
    assert repository_result.success is True
    assert result.persisted_event is None
    assert result.issue is not None
    assert result.issue.code == "audit_append_failed"


def test_invalid_event_identifier_preserves_repository_result(
    tmp_path: Path,
) -> None:
    sink = RecordingAuditSink()

    result = _service(
        tmp_path,
        sink,
        event_ids=("invalid-id",),
    ).create(_document())

    repository_result = cast(
        KnowledgeWriteResult,
        result.repository_result,
    )
    assert repository_result.success is True
    assert result.persisted_event is None
    assert result.issue is not None
    assert result.issue.code == "knowledge_audit_event_failed"


def test_invalid_operation_identifier_prevents_repository_operation(
    tmp_path: Path,
) -> None:
    sink = RecordingAuditSink()

    result = _service(
        tmp_path,
        sink,
        operation_ids=("invalid-id",),
    ).list()

    assert result.repository_result is None
    assert result.persisted_event is None
    assert result.issue is not None
    assert result.issue.code == "knowledge_operation_id_failed"
    assert sink.events == []


def test_replace_is_audited_with_new_version(tmp_path: Path) -> None:
    sink = RecordingAuditSink()
    service = _service(
        tmp_path,
        sink,
        event_ids=(EVENT_ID, "22222222-2222-4222-8222-222222222222"),
        clock_values=(NOW, NOW),
    )
    assert service.create(_document()).repository_result is not None

    replacement = KnowledgeDocument(
        document_id=DOCUMENT_ID,
        document_type=KnowledgeDocumentType.NOTE,
        document_version=2,
        title="Replacement",
        sensitivity=KnowledgeSensitivity.CRITICAL,
        created_at=NOW,
        updated_at=NOW,
        body="# Replacement\n",
    )
    result = service.replace(replacement, expected_version=1)

    repository_result = cast(
        KnowledgeReplaceResult,
        result.repository_result,
    )
    assert repository_result.success is True
    assert sink.events[1].payload["operation"] == "replace"
    assert sink.events[1].payload["document_version"] == 2
