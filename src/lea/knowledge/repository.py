"""Atomic filesystem persistence for canonical knowledge documents."""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path
from uuid import UUID

from lea.knowledge.contracts import (
    KnowledgeDocument,
    KnowledgeDocumentType,
    KnowledgeListResult,
    KnowledgeQuery,
    KnowledgeReadResult,
    KnowledgeReplaceResult,
    KnowledgeRepositoryInspection,
    KnowledgeRepositoryIssue,
    KnowledgeWriteResult,
)
from lea.knowledge.documents import (
    parse_knowledge_document,
    render_knowledge_document,
)
from lea.knowledge.paths import (
    knowledge_document_filename,
    knowledge_document_id_from_filename,
    knowledge_document_path,
    knowledge_document_type_directory,
    validate_knowledge_path,
)


class MarkdownKnowledgeRepository:
    """Persistent Markdown repository for canonical knowledge documents."""

    def __init__(
        self,
        root: Path,
        *,
        create_parents: bool = False,
        fsync: bool = False,
    ) -> None:
        """Configure one explicitly located knowledge repository."""
        _validate_root(root)
        self._root = root
        self._create_parents = create_parents
        self._fsync = fsync

    @property
    def root(self) -> Path:
        """Return the configured knowledge root."""
        return self._root

    def create(self, document: KnowledgeDocument) -> KnowledgeWriteResult:
        """Atomically create one document without overwriting."""
        destination = knowledge_document_path(self._root, document)
        issue = self._prepare_destination(destination, document.document_id)

        if issue is not None:
            return _write_failure(destination, issue)

        matches = self._matching_paths(document.document_id)
        if isinstance(matches, KnowledgeRepositoryIssue):
            return _write_failure(destination, matches)

        if matches or destination.exists() or destination.is_symlink():
            return _write_failure(
                destination,
                KnowledgeRepositoryIssue(
                    code="knowledge_duplicate_id",
                    message=(
                        "A knowledge document with this identifier already exists."
                    ),
                    document_id=document.document_id,
                    path=matches[0] if matches else destination,
                ),
            )

        rendered = render_knowledge_document(document)
        temporary_path: Path | None = None

        try:
            temporary_path = self._write_temporary(
                destination.parent,
                document.document_id,
                rendered,
            )
            os.link(temporary_path, destination)

            if self._fsync:
                _fsync_directory(destination.parent)
        except FileExistsError:
            return _write_failure(
                destination,
                KnowledgeRepositoryIssue(
                    code="knowledge_duplicate_id",
                    message="The canonical knowledge destination already exists.",
                    document_id=document.document_id,
                    path=destination,
                ),
            )
        except OSError:
            return _write_failure(
                destination,
                KnowledgeRepositoryIssue(
                    code="knowledge_atomic_write_failed",
                    message="The knowledge document could not be created.",
                    document_id=document.document_id,
                    path=destination,
                ),
            )
        finally:
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink(missing_ok=True)

        readback = self.read(document.document_id)

        if not readback.success or readback.document != document:
            return _write_failure(
                destination,
                KnowledgeRepositoryIssue(
                    code="knowledge_readback_mismatch",
                    message=(
                        "The persisted knowledge document did not match "
                        "the requested canonical value."
                    ),
                    document_id=document.document_id,
                    path=destination,
                ),
            )

        return KnowledgeWriteResult(
            success=True,
            document=document,
            path=destination,
            issues=(),
        )

    def read(self, document_id: str) -> KnowledgeReadResult:
        """Read one exact document by stable identifier."""
        _validate_document_id(document_id)
        matches = self._matching_paths(document_id)

        if isinstance(matches, KnowledgeRepositoryIssue):
            return _read_failure(None, matches)

        if not matches:
            return _read_failure(
                None,
                KnowledgeRepositoryIssue(
                    code="knowledge_not_found",
                    message="The knowledge document was not found.",
                    document_id=document_id,
                ),
            )

        if len(matches) > 1:
            return _read_failure(
                None,
                KnowledgeRepositoryIssue(
                    code="knowledge_duplicate_id",
                    message=("Multiple knowledge documents use the same identifier."),
                    document_id=document_id,
                    path=matches[0],
                ),
            )

        path = matches[0]

        try:
            validate_knowledge_path(self._root, path)
        except (TypeError, ValueError):
            return _read_failure(
                path,
                KnowledgeRepositoryIssue(
                    code="knowledge_path_outside_root",
                    message="The knowledge document path is not permitted.",
                    document_id=document_id,
                    path=path,
                ),
            )

        if path.is_symlink():
            return _read_failure(
                path,
                KnowledgeRepositoryIssue(
                    code="knowledge_symlink_rejected",
                    message="Symbolic links are not permitted.",
                    document_id=document_id,
                    path=path,
                ),
            )

        if not path.is_file():
            return _read_failure(
                path,
                KnowledgeRepositoryIssue(
                    code="knowledge_read_failed",
                    message="The knowledge document path is not a regular file.",
                    document_id=document_id,
                    path=path,
                ),
            )

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeError:
            return _read_failure(
                path,
                KnowledgeRepositoryIssue(
                    code="knowledge_invalid_utf8",
                    message="The knowledge document is not valid UTF-8.",
                    document_id=document_id,
                    path=path,
                ),
            )
        except OSError:
            return _read_failure(
                path,
                KnowledgeRepositoryIssue(
                    code="knowledge_read_failed",
                    message="The knowledge document could not be read.",
                    document_id=document_id,
                    path=path,
                ),
            )

        parsed = parse_knowledge_document(content)

        if not parsed.success:
            return KnowledgeReadResult(
                success=False,
                document=None,
                path=path,
                issues=tuple(
                    KnowledgeRepositoryIssue(
                        code=issue.code,
                        message=issue.message,
                        document_id=issue.document_id or document_id,
                        path=path,
                        field=issue.field,
                        line_number=issue.line_number,
                    )
                    for issue in parsed.issues
                ),
            )

        knowledge = parsed.document

        if knowledge is None:
            return _read_failure(
                path,
                KnowledgeRepositoryIssue(
                    code="knowledge_read_failed",
                    message=(
                        "Knowledge parsing succeeded without returning a document."
                    ),
                    document_id=document_id,
                    path=path,
                ),
            )

        expected_filename = knowledge_document_filename(knowledge)
        expected_directory = knowledge_document_type_directory(knowledge.document_type)

        if (
            knowledge.document_id != document_id
            or path.name != expected_filename
            or path.parent.name != expected_directory
        ):
            return _read_failure(
                path,
                KnowledgeRepositoryIssue(
                    code="knowledge_filename_mismatch",
                    message=("The knowledge path does not match canonical metadata."),
                    document_id=document_id,
                    path=path,
                ),
            )

        return KnowledgeReadResult(
            success=True,
            document=knowledge,
            path=path,
            issues=(),
        )

    def replace(
        self,
        document: KnowledgeDocument,
        *,
        expected_version: int,
    ) -> KnowledgeReplaceResult:
        """Replace one document with optimistic version guarding."""
        if not isinstance(expected_version, int):
            raise TypeError("expected_version must be an integer.")

        if expected_version < 1:
            raise ValueError("expected_version must be greater than zero.")

        existing_result = self.read(document.document_id)

        if not existing_result.success:
            return KnowledgeReplaceResult(
                success=False,
                document=None,
                previous_document=None,
                path=None,
                previous_path=existing_result.path,
                issues=existing_result.issues,
            )

        existing = existing_result.document
        previous_path = existing_result.path

        if existing is None or previous_path is None:
            return _replace_failure(
                code="knowledge_read_failed",
                message=(
                    "Knowledge reading succeeded without returning a document and path."
                ),
                document_id=document.document_id,
                path=previous_path,
            )

        destination = knowledge_document_path(self._root, document)

        if existing.document_version != expected_version:
            return _replace_failure(
                code="knowledge_version_conflict",
                message=(
                    "The stored knowledge version does not match the expected version."
                ),
                document_id=document.document_id,
                path=previous_path,
                previous_document=existing,
                previous_path=previous_path,
                expected_version=expected_version,
                actual_version=existing.document_version,
            )

        required_version = expected_version + 1

        if document.document_version != required_version:
            return _replace_failure(
                code="knowledge_invalid_next_version",
                message=(
                    "The replacement version must be exactly one "
                    "greater than the expected version."
                ),
                document_id=document.document_id,
                path=destination,
                previous_document=existing,
                previous_path=previous_path,
                expected_version=required_version,
                actual_version=document.document_version,
            )

        if document.created_at != existing.created_at:
            return _replace_failure(
                code="knowledge_created_at_changed",
                message=("Replacement must preserve the original created_at value."),
                document_id=document.document_id,
                path=destination,
                previous_document=existing,
                previous_path=previous_path,
            )

        if document.updated_at < existing.updated_at:
            return _replace_failure(
                code="knowledge_updated_at_regressed",
                message=("Replacement updated_at must not move backwards."),
                document_id=document.document_id,
                path=destination,
                previous_document=existing,
                previous_path=previous_path,
            )

        issue = self._prepare_destination(
            destination,
            document.document_id,
        )

        if issue is not None:
            return KnowledgeReplaceResult(
                success=False,
                document=None,
                previous_document=existing,
                path=destination,
                previous_path=previous_path,
                issues=(issue,),
            )

        if destination != previous_path and (
            destination.exists() or destination.is_symlink()
        ):
            return _replace_failure(
                code="knowledge_destination_exists",
                message=(
                    "The replacement destination already exists "
                    "and was not overwritten."
                ),
                document_id=document.document_id,
                path=destination,
                previous_document=existing,
                previous_path=previous_path,
            )

        rendered = render_knowledge_document(document)
        temporary_path: Path | None = None

        try:
            temporary_path = self._write_temporary(
                destination.parent,
                document.document_id,
                rendered,
            )

            if destination == previous_path:
                os.replace(temporary_path, destination)
                temporary_path = None

                if self._fsync:
                    try:
                        _fsync_directory(destination.parent)
                    except OSError:
                        return _replace_failure(
                            code="knowledge_durability_failed",
                            message=(
                                "The replacement was published, but its "
                                "directory durability could not be confirmed."
                            ),
                            document_id=document.document_id,
                            path=destination,
                            previous_document=existing,
                            previous_path=previous_path,
                        )
            else:
                os.link(temporary_path, destination)

                if self._fsync:
                    try:
                        _fsync_directory(destination.parent)
                    except OSError:
                        with suppress(OSError):
                            destination.unlink(missing_ok=True)

                        return _replace_failure(
                            code="knowledge_move_failed",
                            message=(
                                "The replacement destination could not be "
                                "made durable before removing the source."
                            ),
                            document_id=document.document_id,
                            path=destination,
                            previous_document=existing,
                            previous_path=previous_path,
                        )

                try:
                    previous_path.unlink()
                except OSError:
                    with suppress(OSError):
                        destination.unlink(missing_ok=True)

                    return _replace_failure(
                        code="knowledge_move_failed",
                        message=(
                            "The replacement destination was published, "
                            "but the previous path could not be removed."
                        ),
                        document_id=document.document_id,
                        path=destination,
                        previous_document=existing,
                        previous_path=previous_path,
                    )

                if self._fsync and previous_path.parent != destination.parent:
                    try:
                        _fsync_directory(previous_path.parent)
                    except OSError:
                        return _replace_failure(
                            code="knowledge_durability_failed",
                            message=(
                                "The replacement was published and the source "
                                "was removed, but source-directory durability "
                                "could not be confirmed."
                            ),
                            document_id=document.document_id,
                            path=destination,
                            previous_document=existing,
                            previous_path=previous_path,
                        )
        except OSError:
            return _replace_failure(
                code=(
                    "knowledge_move_failed"
                    if destination != previous_path
                    else "knowledge_replace_failed"
                ),
                message=(
                    "The knowledge document could not be moved."
                    if destination != previous_path
                    else "The knowledge document could not be replaced."
                ),
                document_id=document.document_id,
                path=destination,
                previous_document=existing,
                previous_path=previous_path,
            )
        finally:
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink(missing_ok=True)

        readback = self.read(document.document_id)

        if not readback.success or readback.document != document:
            return _replace_failure(
                code="knowledge_readback_mismatch",
                message=(
                    "The replaced knowledge document did not match "
                    "the requested canonical value."
                ),
                document_id=document.document_id,
                path=destination,
                previous_document=existing,
                previous_path=previous_path,
            )

        return KnowledgeReplaceResult(
            success=True,
            document=document,
            previous_document=existing,
            path=destination,
            previous_path=previous_path,
            issues=(),
        )

    def list(
        self,
        query: KnowledgeQuery | None = None,
    ) -> KnowledgeListResult:
        """List canonical documents in deterministic order."""
        root_issue = self._inspect_root()

        if root_issue is not None:
            return _list_failure(root_issue)

        paths = self._all_document_paths()

        if isinstance(paths, KnowledgeRepositoryIssue):
            return _list_failure(paths)

        documents: list[KnowledgeDocument] = []
        seen: set[str] = set()

        for path in paths:
            try:
                document_id = knowledge_document_id_from_filename(path.name)
            except (TypeError, ValueError):
                return _list_failure(
                    KnowledgeRepositoryIssue(
                        code="knowledge_filename_mismatch",
                        message=(
                            "A knowledge Markdown file has a non-canonical filename."
                        ),
                        path=path,
                    )
                )

            if document_id in seen:
                return _list_failure(
                    KnowledgeRepositoryIssue(
                        code="knowledge_duplicate_id",
                        message=(
                            "Multiple knowledge documents use the same identifier."
                        ),
                        document_id=document_id,
                        path=path,
                    )
                )

            seen.add(document_id)
            result = self.read(document_id)

            if not result.success:
                return KnowledgeListResult(
                    success=False,
                    documents=(),
                    issues=result.issues,
                )

            assert result.document is not None

            if _matches_query(result.document, query):
                documents.append(result.document)

        documents.sort(
            key=lambda item: (
                item.document_type.value,
                item.title.casefold(),
                item.document_id,
            )
        )

        return KnowledgeListResult(
            success=True,
            documents=tuple(documents),
            issues=(),
        )

    def inspect(self) -> KnowledgeRepositoryInspection:
        """Inspect every repository entry without modifying anything."""
        if not self._root.exists():
            return KnowledgeRepositoryInspection(
                available=False,
                checked_documents=0,
                valid_documents=0,
                issues=(
                    KnowledgeRepositoryIssue(
                        code="knowledge_directory_missing",
                        message="The configured knowledge root does not exist.",
                        path=self._root,
                    ),
                ),
            )

        if self._root.is_symlink() or not self._root.is_dir():
            return KnowledgeRepositoryInspection(
                available=False,
                checked_documents=0,
                valid_documents=0,
                issues=(
                    KnowledgeRepositoryIssue(
                        code="knowledge_directory_not_directory",
                        message=(
                            "The configured knowledge root is not a regular directory."
                        ),
                        path=self._root,
                    ),
                ),
            )

        issues: list[KnowledgeRepositoryIssue] = []
        checked_documents = 0
        valid_documents = 0
        seen_ids: dict[str, Path] = {}
        canonical_directories = {
            knowledge_document_type_directory(document_type)
            for document_type in KnowledgeDocumentType
        }

        try:
            root_entries = tuple(
                sorted(self._root.iterdir(), key=lambda item: item.name)
            )
        except OSError:
            return KnowledgeRepositoryInspection(
                available=False,
                checked_documents=0,
                valid_documents=0,
                issues=(
                    KnowledgeRepositoryIssue(
                        code="knowledge_read_failed",
                        message=(
                            "The knowledge repository root could not be inspected."
                        ),
                        path=self._root,
                    ),
                ),
            )

        for entry in root_entries:
            if entry.is_symlink():
                issues.append(
                    KnowledgeRepositoryIssue(
                        code="knowledge_symlink_rejected",
                        message="Symbolic links are not permitted.",
                        path=entry,
                    )
                )
                continue

            if entry.name not in canonical_directories:
                issues.append(
                    KnowledgeRepositoryIssue(
                        code=(
                            "knowledge_unexpected_entry"
                            if entry.is_dir()
                            else "knowledge_unexpected_file"
                        ),
                        message=(
                            "An unexpected entry was found in the knowledge repository."
                        ),
                        path=entry,
                    )
                )
                continue

            if not entry.is_dir():
                issues.append(
                    KnowledgeRepositoryIssue(
                        code="knowledge_directory_not_directory",
                        message=("A canonical knowledge type path is not a directory."),
                        path=entry,
                    )
                )
                continue

            try:
                children = tuple(sorted(entry.iterdir(), key=lambda item: item.name))
            except OSError:
                issues.append(
                    KnowledgeRepositoryIssue(
                        code="knowledge_read_failed",
                        message=("A knowledge type directory could not be inspected."),
                        path=entry,
                    )
                )
                continue

            for path in children:
                if path.is_symlink():
                    issues.append(
                        KnowledgeRepositoryIssue(
                            code="knowledge_symlink_rejected",
                            message="Symbolic links are not permitted.",
                            path=path,
                        )
                    )
                    continue

                if path.name.startswith(".") and path.name.endswith(".tmp"):
                    issues.append(
                        KnowledgeRepositoryIssue(
                            code="knowledge_temporary_file",
                            message=("A leftover temporary knowledge file was found."),
                            path=path,
                        )
                    )
                    continue

                if path.is_dir():
                    issues.append(
                        KnowledgeRepositoryIssue(
                            code="knowledge_unexpected_entry",
                            message=(
                                "An unexpected directory was found in a "
                                "knowledge type directory."
                            ),
                            path=path,
                        )
                    )
                    continue

                if path.suffix != ".md":
                    issues.append(
                        KnowledgeRepositoryIssue(
                            code="knowledge_unexpected_file",
                            message=("An unexpected non-Markdown file was found."),
                            path=path,
                        )
                    )
                    continue

                checked_documents += 1

                try:
                    document_id = knowledge_document_id_from_filename(path.name)
                except (TypeError, ValueError):
                    issues.append(
                        KnowledgeRepositoryIssue(
                            code="knowledge_filename_mismatch",
                            message=(
                                "A knowledge Markdown file has a "
                                "non-canonical filename."
                            ),
                            path=path,
                        )
                    )
                    continue

                if document_id in seen_ids:
                    issues.append(
                        KnowledgeRepositoryIssue(
                            code="knowledge_duplicate_id",
                            message=(
                                "Multiple knowledge documents use the same identifier."
                            ),
                            document_id=document_id,
                            path=path,
                        )
                    )
                    continue

                seen_ids[document_id] = path

                try:
                    content = path.read_text(encoding="utf-8")
                except UnicodeError:
                    issues.append(
                        KnowledgeRepositoryIssue(
                            code="knowledge_invalid_utf8",
                            message=("The knowledge document is not valid UTF-8."),
                            document_id=document_id,
                            path=path,
                        )
                    )
                    continue
                except OSError:
                    issues.append(
                        KnowledgeRepositoryIssue(
                            code="knowledge_read_failed",
                            message=("The knowledge document could not be read."),
                            document_id=document_id,
                            path=path,
                        )
                    )
                    continue

                parsed = parse_knowledge_document(content)

                if not parsed.success:
                    issues.extend(
                        KnowledgeRepositoryIssue(
                            code=issue.code,
                            message=issue.message,
                            document_id=issue.document_id or document_id,
                            path=path,
                            field=issue.field,
                            line_number=issue.line_number,
                        )
                        for issue in parsed.issues
                    )
                    continue

                document = parsed.document

                if document is None:
                    issues.append(
                        KnowledgeRepositoryIssue(
                            code="knowledge_read_failed",
                            message=(
                                "Knowledge parsing succeeded without "
                                "returning a document."
                            ),
                            document_id=document_id,
                            path=path,
                        )
                    )
                    continue

                expected_path = knowledge_document_path(
                    self._root,
                    document,
                )

                if document.document_id != document_id or path != expected_path:
                    issues.append(
                        KnowledgeRepositoryIssue(
                            code="knowledge_filename_mismatch",
                            message=(
                                "The knowledge path does not match canonical metadata."
                            ),
                            document_id=document_id,
                            path=path,
                        )
                    )
                    continue

                valid_documents += 1

        return KnowledgeRepositoryInspection(
            available=True,
            checked_documents=checked_documents,
            valid_documents=valid_documents,
            issues=tuple(issues),
        )

    def _prepare_destination(
        self,
        destination: Path,
        document_id: str,
    ) -> KnowledgeRepositoryIssue | None:
        """Ensure the root and canonical type directory are usable."""
        if not self._root.exists():
            if not self._create_parents:
                return KnowledgeRepositoryIssue(
                    code="knowledge_directory_missing",
                    message="The configured knowledge root does not exist.",
                    document_id=document_id,
                    path=self._root,
                )

            try:
                self._root.mkdir(parents=True, exist_ok=True)
            except OSError:
                return KnowledgeRepositoryIssue(
                    code="knowledge_atomic_write_failed",
                    message="The configured knowledge root could not be created.",
                    document_id=document_id,
                    path=self._root,
                )

        if self._root.is_symlink() or not self._root.is_dir():
            return KnowledgeRepositoryIssue(
                code="knowledge_directory_not_directory",
                message=("The configured knowledge root is not a regular directory."),
                document_id=document_id,
                path=self._root,
            )

        directory = destination.parent

        try:
            validate_knowledge_path(self._root, directory)
        except (TypeError, ValueError):
            return KnowledgeRepositoryIssue(
                code="knowledge_path_outside_root",
                message="The canonical knowledge directory is not permitted.",
                document_id=document_id,
                path=directory,
            )

        if directory.exists():
            if directory.is_symlink():
                return KnowledgeRepositoryIssue(
                    code="knowledge_symlink_rejected",
                    message="Symbolic links are not permitted.",
                    document_id=document_id,
                    path=directory,
                )

            if not directory.is_dir():
                return KnowledgeRepositoryIssue(
                    code="knowledge_directory_not_directory",
                    message=("The canonical knowledge type path is not a directory."),
                    document_id=document_id,
                    path=directory,
                )

            return None

        try:
            directory.mkdir()
        except OSError:
            return KnowledgeRepositoryIssue(
                code="knowledge_atomic_write_failed",
                message="The canonical type directory could not be created.",
                document_id=document_id,
                path=directory,
            )

        return None

    def _inspect_root(self) -> KnowledgeRepositoryIssue | None:
        """Inspect the repository root without modifying it."""
        if not self._root.exists():
            return KnowledgeRepositoryIssue(
                code="knowledge_directory_missing",
                message="The configured knowledge root does not exist.",
                path=self._root,
            )

        if self._root.is_symlink() or not self._root.is_dir():
            return KnowledgeRepositoryIssue(
                code="knowledge_directory_not_directory",
                message=("The configured knowledge root is not a regular directory."),
                path=self._root,
            )

        return None

    def _matching_paths(
        self,
        document_id: str,
    ) -> tuple[Path, ...] | KnowledgeRepositoryIssue:
        """Find canonical-looking paths for one identifier."""
        if not self._root.exists():
            return ()

        paths = self._all_document_paths()

        if isinstance(paths, KnowledgeRepositoryIssue):
            return paths

        suffix = f"--{document_id}.md"
        return tuple(path for path in paths if path.name.endswith(suffix))

    def _all_document_paths(
        self,
    ) -> tuple[Path, ...] | KnowledgeRepositoryIssue:
        """Collect Markdown files from canonical type directories."""
        collected: list[Path] = []

        for document_type in KnowledgeDocumentType:
            directory = self._root / knowledge_document_type_directory(document_type)

            if not directory.exists():
                continue

            if directory.is_symlink():
                return KnowledgeRepositoryIssue(
                    code="knowledge_symlink_rejected",
                    message="Symbolic links are not permitted.",
                    path=directory,
                )

            if not directory.is_dir():
                return KnowledgeRepositoryIssue(
                    code="knowledge_directory_not_directory",
                    message=("A canonical knowledge type path is not a directory."),
                    path=directory,
                )

            try:
                entries = tuple(directory.iterdir())
            except OSError:
                return KnowledgeRepositoryIssue(
                    code="knowledge_read_failed",
                    message="A knowledge directory could not be listed.",
                    path=directory,
                )

            for path in entries:
                if path.is_symlink():
                    return KnowledgeRepositoryIssue(
                        code="knowledge_symlink_rejected",
                        message="Symbolic links are not permitted.",
                        path=path,
                    )

                if path.suffix == ".md":
                    collected.append(path)

        return tuple(sorted(collected, key=lambda item: str(item)))

    def _write_temporary(
        self,
        directory: Path,
        document_id: str,
        content: str,
    ) -> Path:
        """Write one complete temporary document beside its destination."""
        descriptor, name = tempfile.mkstemp(
            prefix=f".{document_id}.",
            suffix=".tmp",
            dir=directory,
            text=True,
        )
        temporary = Path(name)

        try:
            with os.fdopen(
                descriptor,
                mode="w",
                encoding="utf-8",
                newline="\n",
            ) as stream:
                stream.write(content)
                stream.flush()

                if self._fsync:
                    os.fsync(stream.fileno())
        except BaseException:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
            raise

        return temporary


def _matches_query(
    document: KnowledgeDocument,
    query: KnowledgeQuery | None,
) -> bool:
    """Return whether one document matches exact query filters."""
    if query is None:
        return True

    if query.document_id is not None and document.document_id != query.document_id:
        return False

    if (
        query.document_type is not None
        and document.document_type is not query.document_type
    ):
        return False

    if query.sensitivity is not None and document.sensitivity is not query.sensitivity:
        return False

    if query.link_target_id is not None and all(
        link.document_id != query.link_target_id for link in document.links
    ):
        return False

    if query.external_reference_namespace is not None:
        assert query.external_reference_identifier is not None

        if all(
            reference.namespace != query.external_reference_namespace
            or reference.identifier != query.external_reference_identifier
            for reference in document.external_references
        ):
            return False

    return True


def _validate_root(root: Path) -> None:
    if not isinstance(root, Path):
        raise TypeError("root must be a pathlib.Path value.")

    if not root.is_absolute():
        raise ValueError("root must be an absolute path.")

    if "\x00" in str(root):
        raise ValueError("root must not contain a null byte.")


def _validate_document_id(document_id: str) -> None:
    if not isinstance(document_id, str):
        raise TypeError("document_id must be a string.")

    try:
        parsed = UUID(document_id)
    except ValueError as exc:
        raise ValueError("document_id must be a valid UUID.") from exc

    if str(parsed) != document_id:
        raise ValueError(
            "document_id must use canonical lowercase hyphenated UUID text."
        )


def _write_failure(
    path: Path,
    issue: KnowledgeRepositoryIssue,
) -> KnowledgeWriteResult:
    return KnowledgeWriteResult(False, None, path, (issue,))


def _replace_failure(
    *,
    code: str,
    message: str,
    document_id: str,
    path: Path | None,
    previous_document: KnowledgeDocument | None = None,
    previous_path: Path | None = None,
    expected_version: int | None = None,
    actual_version: int | None = None,
) -> KnowledgeReplaceResult:
    """Construct one deterministic failed replacement result."""
    return KnowledgeReplaceResult(
        success=False,
        document=None,
        previous_document=previous_document,
        path=path,
        previous_path=previous_path,
        issues=(
            KnowledgeRepositoryIssue(
                code=code,
                message=message,
                document_id=document_id,
                path=path,
                expected_version=expected_version,
                actual_version=actual_version,
            ),
        ),
    )


def _read_failure(
    path: Path | None,
    issue: KnowledgeRepositoryIssue,
) -> KnowledgeReadResult:
    return KnowledgeReadResult(False, None, path, (issue,))


def _list_failure(issue: KnowledgeRepositoryIssue) -> KnowledgeListResult:
    return KnowledgeListResult(False, (), (issue,))


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)

    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
