"""Tests for runtime-bound Markdown knowledge components."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lea.audit import IntegrityJsonlAuditStore
from lea.knowledge import (
    KnowledgeDocument,
    KnowledgeDocumentType,
    KnowledgeSensitivity,
    MarkdownKnowledgeRepository,
    SQLiteKnowledgeIndex,
)
from lea.runtime import (
    KNOWLEDGE_INDEX_FILENAME,
    build_knowledge_runtime,
    isolated_test_runtime_config,
    isolated_test_runtime_paths,
)

DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"
EVENT_ID = "21111111-1111-4111-8111-111111111111"
OPERATION_ID = "31111111-1111-4111-8111-111111111111"
NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


def _document() -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=DOCUMENT_ID,
        document_type=KnowledgeDocumentType.NOTE,
        document_version=1,
        title="Runtime knowledge",
        sensitivity=KnowledgeSensitivity.LOW,
        created_at=NOW,
        updated_at=NOW,
        body="# Runtime knowledge\n",
    )


def test_build_from_runtime_paths_uses_canonical_locations(
    tmp_path: Path,
) -> None:
    paths = isolated_test_runtime_paths(tmp_path / "runtime")

    runtime = build_knowledge_runtime(
        paths,
        clock=lambda: NOW,
        audit_event_id_source=lambda: EVENT_ID,
        operation_id_source=lambda: OPERATION_ID,
    )

    assert isinstance(runtime.repository, MarkdownKnowledgeRepository)
    assert runtime.repository.root == paths.knowledge_dir
    assert isinstance(runtime.index, SQLiteKnowledgeIndex)
    assert runtime.index.path == paths.index_dir / KNOWLEDGE_INDEX_FILENAME
    assert isinstance(runtime.audit_store, IntegrityJsonlAuditStore)
    assert runtime.audit_store.path == paths.audit_file


def test_build_from_runtime_config_uses_configured_paths(
    tmp_path: Path,
) -> None:
    config = isolated_test_runtime_config(tmp_path / "runtime")

    runtime = build_knowledge_runtime(config)

    assert runtime.repository.root == config.paths.knowledge_dir
    assert runtime.index.path == (config.paths.index_dir / KNOWLEDGE_INDEX_FILENAME)
    assert runtime.audit_store.path == config.paths.audit_file


def test_construction_does_not_mutate_filesystem(tmp_path: Path) -> None:
    paths = isolated_test_runtime_paths(tmp_path / "runtime")

    runtime = build_knowledge_runtime(paths)

    assert paths.state_dir.exists() is False
    assert runtime.index.path.exists() is False
    assert runtime.audit_store.path.exists() is False


def test_service_uses_bound_repository_and_audit_store(
    tmp_path: Path,
) -> None:
    paths = isolated_test_runtime_paths(tmp_path / "runtime")
    paths.knowledge_dir.mkdir(parents=True)
    paths.audit_dir.mkdir(parents=True)
    paths.index_dir.mkdir(parents=True)

    runtime = build_knowledge_runtime(
        paths,
        clock=lambda: NOW,
        audit_event_id_source=lambda: EVENT_ID,
        operation_id_source=lambda: OPERATION_ID,
    )

    result = runtime.service.create(_document())

    assert result.repository_result is not None
    assert result.persisted_event is not None
    assert runtime.repository.read(DOCUMENT_ID).success is True
    assert runtime.audit_store.read_all()[0].event == result.persisted_event


def test_fsync_setting_is_accepted(tmp_path: Path) -> None:
    paths = isolated_test_runtime_paths(tmp_path / "runtime")

    runtime = build_knowledge_runtime(paths, fsync=True)

    assert runtime.repository.root == paths.knowledge_dir
    assert runtime.audit_store.path == paths.audit_file


def test_runtime_bundle_is_immutable(tmp_path: Path) -> None:
    runtime = build_knowledge_runtime(isolated_test_runtime_paths(tmp_path / "runtime"))

    with pytest.raises(FrozenInstanceError):
        runtime.index = runtime.index  # type: ignore[misc]


def test_invalid_runtime_input_is_rejected() -> None:
    with pytest.raises(
        TypeError,
        match="RuntimeConfig or RuntimePaths",
    ):
        build_knowledge_runtime(object())  # type: ignore[arg-type]
