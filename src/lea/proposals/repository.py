"""Atomic filesystem persistence for canonical proposal documents."""

import os
import tempfile
from contextlib import suppress
from pathlib import Path
from uuid import UUID

from lea.actions import ActionProposal
from lea.proposals.contracts import (
    ProposalRepositoryIssue,
    ProposalWriteResult,
)
from lea.proposals.documents import render_proposal_document


class MarkdownProposalRepository:
    """Persistent Markdown repository for immutable proposals."""

    def __init__(
        self,
        root: Path,
        *,
        create_parents: bool = False,
        fsync: bool = False,
    ) -> None:
        """Configure one explicitly located proposal repository."""
        _validate_repository_root(root)

        self._root = root
        self._create_parents = create_parents
        self._fsync = fsync

    @property
    def root(self) -> Path:
        """Return the configured proposal-directory path."""
        return self._root

    def path_for(
        self,
        proposal_id: str,
    ) -> Path:
        """Return the canonical document path for one proposal."""
        _validate_proposal_id(proposal_id)

        return self._root / f"{proposal_id}.md"

    def create(
        self,
        proposal: ActionProposal,
    ) -> ProposalWriteResult:
        """Atomically create one proposal without overwriting."""
        destination = self.path_for(proposal.proposal_id)

        preparation_issue = self._prepare_root(
            proposal_id=proposal.proposal_id,
            destination=destination,
        )

        if preparation_issue is not None:
            return ProposalWriteResult(
                success=False,
                proposal=None,
                path=destination,
                issues=(preparation_issue,),
            )

        if destination.exists():
            return _failure(
                code="proposal_already_exists",
                message=(
                    "The proposal document already exists and was not overwritten."
                ),
                proposal_id=proposal.proposal_id,
                path=destination,
            )

        document = render_proposal_document(proposal)

        temporary_path: Path | None = None

        try:
            temporary_path = self._write_temporary_document(
                document,
                proposal_id=proposal.proposal_id,
            )

            os.link(
                temporary_path,
                destination,
            )

            if self._fsync:
                _fsync_directory(self._root)
        except FileExistsError:
            return _failure(
                code="proposal_already_exists",
                message=(
                    "The proposal document already exists and was not overwritten."
                ),
                proposal_id=proposal.proposal_id,
                path=destination,
            )
        except OSError:
            return _failure(
                code="proposal_write_failed",
                message="The proposal document could not be created.",
                proposal_id=proposal.proposal_id,
                path=destination,
            )
        finally:
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink(missing_ok=True)

        return ProposalWriteResult(
            success=True,
            proposal=proposal,
            path=destination,
            issues=(),
        )

    def _prepare_root(
        self,
        *,
        proposal_id: str,
        destination: Path,
    ) -> ProposalRepositoryIssue | None:
        """Ensure the configured repository directory is usable."""
        if self._root.exists():
            if not self._root.is_dir():
                return ProposalRepositoryIssue(
                    code="proposal_directory_not_directory",
                    message=(
                        "The configured proposal repository path is not a directory."
                    ),
                    proposal_id=proposal_id,
                    path=self._root,
                )

            return None

        if not self._create_parents:
            return ProposalRepositoryIssue(
                code="proposal_directory_missing",
                message=(
                    "The configured proposal repository directory does not exist."
                ),
                proposal_id=proposal_id,
                path=self._root,
            )

        try:
            self._root.mkdir(
                parents=True,
                exist_ok=True,
            )
        except OSError:
            return ProposalRepositoryIssue(
                code="proposal_write_failed",
                message=("The proposal repository directory could not be created."),
                proposal_id=proposal_id,
                path=destination,
            )

        if not self._root.is_dir():
            return ProposalRepositoryIssue(
                code="proposal_directory_not_directory",
                message=("The configured proposal repository path is not a directory."),
                proposal_id=proposal_id,
                path=self._root,
            )

        return None

    def _write_temporary_document(
        self,
        document: str,
        *,
        proposal_id: str,
    ) -> Path:
        """Write one complete temporary document beside its destination."""
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{proposal_id}.",
            suffix=".tmp",
            dir=self._root,
            text=True,
        )
        temporary_path = Path(temporary_name)

        try:
            with os.fdopen(
                file_descriptor,
                mode="w",
                encoding="utf-8",
                newline="\n",
            ) as stream:
                stream.write(document)
                stream.flush()

                if self._fsync:
                    os.fsync(stream.fileno())
        except BaseException:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)

            raise

        return temporary_path


def _validate_repository_root(
    root: Path,
) -> None:
    """Validate one explicit absolute repository root."""
    if not isinstance(root, Path):
        raise TypeError("root must be a pathlib.Path value.")

    if not root.is_absolute():
        raise ValueError("root must be an absolute path.")

    if "\x00" in str(root):
        raise ValueError("root must not contain a null byte.")


def _validate_proposal_id(
    proposal_id: str,
) -> None:
    """Validate a canonical lower-case proposal UUID."""
    if not isinstance(proposal_id, str):
        raise TypeError("proposal_id must be a string.")

    try:
        parsed_identifier = UUID(proposal_id)
    except ValueError as error:
        raise ValueError("proposal_id must be a valid UUID.") from error

    if str(parsed_identifier) != proposal_id:
        raise ValueError("proposal_id must use canonical lower-case UUID format.")


def _fsync_directory(
    directory: Path,
) -> None:
    """Request filesystem synchronisation for one directory."""
    descriptor = os.open(
        directory,
        os.O_RDONLY,
    )

    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _failure(
    *,
    code: str,
    message: str,
    proposal_id: str,
    path: Path,
) -> ProposalWriteResult:
    """Construct one deterministic failed write result."""
    return ProposalWriteResult(
        success=False,
        proposal=None,
        path=path,
        issues=(
            ProposalRepositoryIssue(
                code=code,
                message=message,
                proposal_id=proposal_id,
                path=path,
            ),
        ),
    )
