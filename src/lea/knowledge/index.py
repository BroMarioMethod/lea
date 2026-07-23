"""Disposable SQLite index for canonical Markdown knowledge."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lea.knowledge.contracts import (
    KnowledgeDocument,
    KnowledgeQuery,
)
from lea.knowledge.repository import MarkdownKnowledgeRepository

KNOWLEDGE_INDEX_SCHEMA_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class KnowledgeIndexIssue:
    """One structured disposable-index problem."""

    code: str
    message: str

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("Knowledge index issue code must be non-empty.")
        if not self.message.strip():
            raise ValueError("Knowledge index issue message must be non-empty.")


@dataclass(frozen=True, slots=True)
class KnowledgeIndexRebuildResult:
    """Result of rebuilding the complete disposable index."""

    success: bool
    indexed_documents: int
    issues: tuple[KnowledgeIndexIssue, ...]

    def __post_init__(self) -> None:
        if self.indexed_documents < 0:
            raise ValueError("indexed_documents must not be negative.")
        if self.success and self.issues:
            raise ValueError("A successful index rebuild must not contain issues.")
        if not self.success and not self.issues:
            raise ValueError("A failed index rebuild must contain issues.")


@dataclass(frozen=True, slots=True)
class KnowledgeIndexVerification:
    """Result of verifying the disposable index structure."""

    available: bool
    valid: bool
    indexed_documents: int
    issues: tuple[KnowledgeIndexIssue, ...]

    def __post_init__(self) -> None:
        if self.indexed_documents < 0:
            raise ValueError("indexed_documents must not be negative.")
        if not self.available and self.valid:
            raise ValueError("An unavailable index cannot be valid.")
        if self.valid and self.issues:
            raise ValueError("A valid index must not contain issues.")
        if not self.valid and not self.issues:
            raise ValueError("An invalid index must contain issues.")


@dataclass(frozen=True, slots=True)
class KnowledgeIndexQueryResult:
    """Lightweight exact-match index-query result."""

    success: bool
    document_ids: tuple[str, ...]
    issues: tuple[KnowledgeIndexIssue, ...]

    def __post_init__(self) -> None:
        if self.success and self.issues:
            raise ValueError("A successful index query must not contain issues.")
        if not self.success and (self.document_ids or not self.issues):
            raise ValueError(
                "A failed index query requires issues and no document identifiers."
            )


@dataclass(frozen=True, slots=True)
class KnowledgeIndexClearResult:
    """Result of deleting the disposable index."""

    success: bool
    removed: bool
    issues: tuple[KnowledgeIndexIssue, ...]

    def __post_init__(self) -> None:
        if self.success and self.issues:
            raise ValueError("A successful index clear must not contain issues.")
        if not self.success and not self.issues:
            raise ValueError("A failed index clear must contain issues.")


class SQLiteKnowledgeIndex:
    """Rebuildable, non-authoritative SQLite knowledge index."""

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path):
            raise TypeError("path must be a pathlib.Path value.")
        if not path.is_absolute():
            raise ValueError("path must be absolute.")
        if "\x00" in str(path):
            raise ValueError("path must not contain a null byte.")
        self._path = path

    @property
    def path(self) -> Path:
        """Return the configured SQLite database path."""
        return self._path

    def rebuild(
        self,
        repository: MarkdownKnowledgeRepository,
    ) -> KnowledgeIndexRebuildResult:
        """Rebuild from canonical Markdown and atomically publish the database."""
        inspection = repository.inspect()
        if not inspection.available or inspection.issues:
            return KnowledgeIndexRebuildResult(
                success=False,
                indexed_documents=0,
                issues=(
                    KnowledgeIndexIssue(
                        code="knowledge_index_source_invalid",
                        message=(
                            "The Markdown knowledge repository must pass inspection "
                            "before the disposable index can be rebuilt."
                        ),
                    ),
                ),
            )

        listed = repository.list()
        if not listed.success:
            return KnowledgeIndexRebuildResult(
                success=False,
                indexed_documents=0,
                issues=(
                    KnowledgeIndexIssue(
                        code="knowledge_index_source_read_failed",
                        message=(
                            "Canonical knowledge documents could not be listed "
                            "for index rebuilding."
                        ),
                    ),
                ),
            )

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return _rebuild_failure("knowledge_index_directory_failed")

        descriptor: int | None = None
        temporary_path: Path | None = None

        try:
            descriptor, name = tempfile.mkstemp(
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                dir=self._path.parent,
            )
            os.close(descriptor)
            descriptor = None
            temporary_path = Path(name)

            with sqlite3.connect(temporary_path) as connection:
                _configure_connection(connection)
                _create_schema(connection)
                _insert_documents(connection, listed.documents)
                connection.commit()

            os.replace(temporary_path, self._path)
            temporary_path = None
        except (OSError, sqlite3.Error):
            return _rebuild_failure("knowledge_index_rebuild_failed")
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink(missing_ok=True)

        return KnowledgeIndexRebuildResult(
            success=True,
            indexed_documents=len(listed.documents),
            issues=(),
        )

    def verify(self) -> KnowledgeIndexVerification:
        """Verify schema metadata and basic relational integrity."""
        if not self._path.exists():
            return KnowledgeIndexVerification(
                available=False,
                valid=False,
                indexed_documents=0,
                issues=(
                    KnowledgeIndexIssue(
                        code="knowledge_index_missing",
                        message="The disposable knowledge index does not exist.",
                    ),
                ),
            )

        if self._path.is_symlink() or not self._path.is_file():
            return _verification_failure(
                available=False,
                code="knowledge_index_invalid_path",
            )

        try:
            with sqlite3.connect(f"file:{self._path}?mode=ro", uri=True) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                schema_row = connection.execute(
                    "SELECT value FROM metadata WHERE key = ?",
                    ("schema_version",),
                ).fetchone()
                integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
                foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
                document_count = int(
                    connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
                )
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return _verification_failure(
                available=True,
                code="knowledge_index_verification_failed",
            )

        if schema_row != (str(KNOWLEDGE_INDEX_SCHEMA_VERSION),):
            return _verification_failure(
                available=True,
                code="knowledge_index_schema_unsupported",
            )

        if integrity_row != ("ok",) or foreign_keys:
            return _verification_failure(
                available=True,
                code="knowledge_index_integrity_failed",
            )

        return KnowledgeIndexVerification(
            available=True,
            valid=True,
            indexed_documents=document_count,
            issues=(),
        )

    def query(
        self,
        query: KnowledgeQuery | None = None,
    ) -> KnowledgeIndexQueryResult:
        """Return matching document identifiers in canonical list order."""
        verification = self.verify()
        if not verification.valid:
            return KnowledgeIndexQueryResult(
                success=False,
                document_ids=(),
                issues=verification.issues,
            )

        clauses: list[str] = []
        parameters: list[object] = []

        if query is not None:
            if query.document_id is not None:
                clauses.append("documents.document_id = ?")
                parameters.append(query.document_id)
            if query.document_type is not None:
                clauses.append("documents.document_type = ?")
                parameters.append(query.document_type.value)
            if query.sensitivity is not None:
                clauses.append("documents.sensitivity = ?")
                parameters.append(query.sensitivity.value)
            if query.link_target_id is not None:
                clauses.append(
                    "EXISTS ("
                    "SELECT 1 FROM links "
                    "WHERE links.source_id = documents.document_id "
                    "AND links.target_id = ?"
                    ")"
                )
                parameters.append(query.link_target_id)
            if query.external_reference_namespace is not None:
                clauses.append(
                    "EXISTS ("
                    "SELECT 1 FROM external_references "
                    "WHERE external_references.document_id = documents.document_id "
                    "AND external_references.namespace = ? "
                    "AND external_references.identifier = ?"
                    ")"
                )
                parameters.extend(
                    (
                        query.external_reference_namespace,
                        query.external_reference_identifier,
                    )
                )

        statement = (
            "SELECT documents.document_id FROM documents"
            + (f" WHERE {' AND '.join(clauses)}" if clauses else "")
            + " ORDER BY documents.document_type, "
            "documents.title_casefold, documents.document_id"
        )

        try:
            with sqlite3.connect(f"file:{self._path}?mode=ro", uri=True) as connection:
                rows = connection.execute(statement, parameters).fetchall()
        except sqlite3.Error:
            return KnowledgeIndexQueryResult(
                success=False,
                document_ids=(),
                issues=(
                    KnowledgeIndexIssue(
                        code="knowledge_index_query_failed",
                        message="The disposable knowledge index query failed.",
                    ),
                ),
            )

        return KnowledgeIndexQueryResult(
            success=True,
            document_ids=tuple(str(row[0]) for row in rows),
            issues=(),
        )

    def clear(self) -> KnowledgeIndexClearResult:
        """Delete the disposable database without affecting Markdown."""
        if not self._path.exists():
            return KnowledgeIndexClearResult(
                success=True,
                removed=False,
                issues=(),
            )

        if self._path.is_symlink() or not self._path.is_file():
            return KnowledgeIndexClearResult(
                success=False,
                removed=False,
                issues=(
                    KnowledgeIndexIssue(
                        code="knowledge_index_invalid_path",
                        message="The disposable index path is not a regular file.",
                    ),
                ),
            )

        try:
            self._path.unlink()
        except OSError:
            return KnowledgeIndexClearResult(
                success=False,
                removed=False,
                issues=(
                    KnowledgeIndexIssue(
                        code="knowledge_index_clear_failed",
                        message="The disposable knowledge index could not be removed.",
                    ),
                ),
            )

        return KnowledgeIndexClearResult(
            success=True,
            removed=True,
            issues=(),
        )


def _configure_connection(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = DELETE")
    connection.execute("PRAGMA synchronous = FULL")


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        ) STRICT;

        CREATE TABLE documents (
            document_id TEXT PRIMARY KEY,
            document_type TEXT NOT NULL,
            document_version INTEGER NOT NULL,
            title_casefold TEXT NOT NULL,
            sensitivity TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        ) STRICT;

        CREATE TABLE links (
            source_id TEXT NOT NULL,
            relation TEXT NOT NULL,
            target_id TEXT NOT NULL,
            PRIMARY KEY (source_id, relation, target_id),
            FOREIGN KEY (source_id)
                REFERENCES documents(document_id)
                ON DELETE CASCADE
        ) STRICT;

        CREATE TABLE external_references (
            document_id TEXT NOT NULL,
            namespace TEXT NOT NULL,
            identifier TEXT NOT NULL,
            PRIMARY KEY (document_id, namespace, identifier),
            FOREIGN KEY (document_id)
                REFERENCES documents(document_id)
                ON DELETE CASCADE
        ) STRICT;

        CREATE INDEX links_target_idx ON links(target_id);
        CREATE INDEX external_references_lookup_idx
            ON external_references(namespace, identifier);
        CREATE INDEX documents_order_idx
            ON documents(document_type, title_casefold, document_id);
        """
    )
    connection.execute(
        "INSERT INTO metadata(key, value) VALUES (?, ?)",
        ("schema_version", str(KNOWLEDGE_INDEX_SCHEMA_VERSION)),
    )


def _insert_documents(
    connection: sqlite3.Connection,
    documents: tuple[KnowledgeDocument, ...],
) -> None:
    for document in documents:
        connection.execute(
            """
            INSERT INTO documents(
                document_id,
                document_type,
                document_version,
                title_casefold,
                sensitivity,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document.document_id,
                document.document_type.value,
                document.document_version,
                document.title.casefold(),
                document.sensitivity.value,
                document.created_at.isoformat(),
                document.updated_at.isoformat(),
            ),
        )
        connection.executemany(
            """
            INSERT INTO links(source_id, relation, target_id)
            VALUES (?, ?, ?)
            """,
            (
                (
                    document.document_id,
                    link.relation,
                    link.document_id,
                )
                for link in document.links
            ),
        )
        connection.executemany(
            """
            INSERT INTO external_references(
                document_id,
                namespace,
                identifier
            ) VALUES (?, ?, ?)
            """,
            (
                (
                    document.document_id,
                    reference.namespace,
                    reference.identifier,
                )
                for reference in document.external_references
            ),
        )


def _rebuild_failure(code: str) -> KnowledgeIndexRebuildResult:
    return KnowledgeIndexRebuildResult(
        success=False,
        indexed_documents=0,
        issues=(
            KnowledgeIndexIssue(
                code=code,
                message="The disposable knowledge index could not be rebuilt.",
            ),
        ),
    )


def _verification_failure(
    *,
    available: bool,
    code: str,
) -> KnowledgeIndexVerification:
    return KnowledgeIndexVerification(
        available=available,
        valid=False,
        indexed_documents=0,
        issues=(
            KnowledgeIndexIssue(
                code=code,
                message="The disposable knowledge index is not valid.",
            ),
        ),
    )
