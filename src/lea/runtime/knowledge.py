"""Deterministic runtime construction for Markdown knowledge services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from lea.audit import IntegrityJsonlAuditStore
from lea.knowledge import (
    KnowledgeAuditEventIdSource,
    KnowledgeOperationIdSource,
    KnowledgeService,
    KnowledgeUtcClock,
    MarkdownKnowledgeRepository,
    SQLiteKnowledgeIndex,
)
from lea.runtime.contracts import RuntimeConfig, RuntimePaths

KNOWLEDGE_INDEX_FILENAME = "knowledge.sqlite3"


@dataclass(frozen=True, slots=True)
class KnowledgeRuntime:
    """Immutable bundle of runtime-bound knowledge components."""

    repository: MarkdownKnowledgeRepository
    index: SQLiteKnowledgeIndex
    audit_store: IntegrityJsonlAuditStore
    service: KnowledgeService


def build_knowledge_runtime(
    runtime: RuntimeConfig | RuntimePaths,
    *,
    clock: KnowledgeUtcClock = lambda: datetime.now(UTC),
    audit_event_id_source: KnowledgeAuditEventIdSource = lambda: str(uuid4()),
    operation_id_source: KnowledgeOperationIdSource = lambda: str(uuid4()),
    fsync: bool = False,
) -> KnowledgeRuntime:
    """Construct knowledge components from validated runtime paths."""
    paths = _runtime_paths(runtime)

    repository = MarkdownKnowledgeRepository(
        paths.knowledge_dir,
        create_parents=False,
        fsync=fsync,
    )
    index = SQLiteKnowledgeIndex(
        paths.index_dir / KNOWLEDGE_INDEX_FILENAME,
    )
    audit_store = IntegrityJsonlAuditStore(
        paths.audit_file,
        create_parents=False,
        fsync=fsync,
    )
    service = KnowledgeService(
        repository,
        audit_store,
        clock,
        audit_event_id_source,
        operation_id_source,
    )

    return KnowledgeRuntime(
        repository=repository,
        index=index,
        audit_store=audit_store,
        service=service,
    )


def _runtime_paths(
    runtime: RuntimeConfig | RuntimePaths,
) -> RuntimePaths:
    """Return paths from one supported runtime input."""
    if isinstance(runtime, RuntimeConfig):
        return runtime.paths

    if isinstance(runtime, RuntimePaths):
        return runtime

    raise TypeError("runtime must be a RuntimeConfig or RuntimePaths value.")
