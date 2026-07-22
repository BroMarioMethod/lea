"""Atomic filesystem persistence for canonical proposal documents."""

import os
import tempfile
from contextlib import suppress
from pathlib import Path
from uuid import UUID

from lea.actions import ActionProposal, ActionStatus
from lea.proposals.contracts import (
    ProposalListResult,
    ProposalReadResult,
    ProposalReplaceResult,
    ProposalRepositoryIssue,
    ProposalVerificationResult,
    ProposalWriteResult,
)
from lea.proposals.documents import (
    parse_proposal_document,
    render_proposal_document,
)


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

    def read(
        self,
        proposal_id: str,
    ) -> ProposalReadResult:
        """Read one exact canonical proposal document."""
        destination = self.path_for(proposal_id)

        if not destination.exists():
            return _read_failure(
                code="proposal_not_found",
                message="The proposal document was not found.",
                proposal_id=proposal_id,
                path=destination,
            )

        if not destination.is_file():
            return _read_failure(
                code="proposal_read_failed",
                message=("The canonical proposal path is not a regular file."),
                proposal_id=proposal_id,
                path=destination,
            )

        try:
            document = destination.read_text(
                encoding="utf-8",
            )
        except (OSError, UnicodeError):
            return _read_failure(
                code="proposal_read_failed",
                message="The proposal document could not be read.",
                proposal_id=proposal_id,
                path=destination,
            )

        parsed = parse_proposal_document(document)

        if not parsed.success:
            issues = tuple(
                ProposalRepositoryIssue(
                    code=issue.code,
                    message=issue.message,
                    proposal_id=(
                        issue.proposal_id
                        if issue.proposal_id is not None
                        else proposal_id
                    ),
                    path=destination,
                    line_number=issue.line_number,
                    field=issue.field,
                )
                for issue in parsed.issues
            )

            return ProposalReadResult(
                success=False,
                proposal=None,
                path=destination,
                issues=issues,
            )

        proposal = parsed.proposal

        if proposal is None:
            return _read_failure(
                code="proposal_read_failed",
                message=("Proposal parsing succeeded without returning a proposal."),
                proposal_id=proposal_id,
                path=destination,
            )

        if proposal.proposal_id != proposal_id:
            return _read_failure(
                code="proposal_identity_mismatch",
                message=(
                    "The proposal identifier inside the document does not "
                    "match its filename."
                ),
                proposal_id=proposal_id,
                path=destination,
            )

        return ProposalReadResult(
            success=True,
            proposal=proposal,
            path=destination,
            issues=(),
        )

    def replace(
        self,
        proposal: ActionProposal,
        *,
        expected_status: ActionStatus,
    ) -> ProposalReplaceResult:
        """Atomically replace one existing canonical proposal document."""
        destination = self.path_for(proposal.proposal_id)
        existing_result = self.read(proposal.proposal_id)

        if not existing_result.success:
            return ProposalReplaceResult(
                success=False,
                proposal=None,
                previous_proposal=None,
                path=destination,
                issues=existing_result.issues,
            )

        existing = existing_result.proposal

        if existing is None:
            return _replace_failure(
                code="proposal_read_failed",
                message=(
                    "Proposal reading succeeded without returning "
                    "the existing proposal."
                ),
                proposal_id=proposal.proposal_id,
                path=destination,
            )

        if existing.status is not expected_status:
            return _replace_failure(
                code="proposal_status_conflict",
                message=(
                    "The existing proposal status does not match the expected status."
                ),
                proposal_id=proposal.proposal_id,
                path=destination,
                field="status",
            )

        document = render_proposal_document(proposal)
        temporary_path: Path | None = None

        try:
            temporary_path = self._write_temporary_document(
                document,
                proposal_id=proposal.proposal_id,
            )
            os.replace(
                temporary_path,
                destination,
            )
            temporary_path = None

            if self._fsync:
                _fsync_directory(self._root)
        except OSError:
            return _replace_failure(
                code="proposal_replace_failed",
                message="The proposal document could not be replaced.",
                proposal_id=proposal.proposal_id,
                path=destination,
            )
        finally:
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink(missing_ok=True)

        readback = self.read(proposal.proposal_id)

        if not readback.success:
            return ProposalReplaceResult(
                success=False,
                proposal=None,
                previous_proposal=existing,
                path=destination,
                issues=readback.issues,
            )

        persisted = readback.proposal

        if persisted != proposal:
            return _replace_failure(
                code="proposal_readback_mismatch",
                message=(
                    "The replaced proposal did not match the requested canonical value."
                ),
                proposal_id=proposal.proposal_id,
                path=destination,
            )

        return ProposalReplaceResult(
            success=True,
            proposal=persisted,
            previous_proposal=existing,
            path=destination,
            issues=(),
        )

    def list_all(self) -> ProposalListResult:
        """Read every canonical proposal in deterministic order."""
        root_issue = self._inspect_root_for_listing()

        if root_issue is not None:
            return ProposalListResult(
                success=False,
                proposals=(),
                issues=(root_issue,),
            )

        proposals: list[ActionProposal] = []

        try:
            document_paths = tuple(
                sorted(
                    self._root.glob("*.md"),
                    key=lambda path: path.name,
                )
            )
        except OSError:
            return _list_failure(
                code="proposal_read_failed",
                message=("The proposal repository directory could not be listed."),
                path=self._root,
            )

        for path in document_paths:
            proposal_id = path.stem

            try:
                _validate_proposal_id(proposal_id)
            except (TypeError, ValueError):
                return _list_failure(
                    code="proposal_invalid_filename",
                    message=(
                        "A proposal document does not use a canonical "
                        "proposal identifier filename."
                    ),
                    path=path,
                )

            result = self.read(proposal_id)

            if not result.success:
                return ProposalListResult(
                    success=False,
                    proposals=(),
                    issues=result.issues,
                )

            proposal = result.proposal

            if proposal is None:
                return _list_failure(
                    code="proposal_read_failed",
                    message=(
                        "Proposal reading succeeded without returning a proposal."
                    ),
                    path=path,
                    proposal_id=proposal_id,
                )

            proposals.append(proposal)

        proposals.sort(
            key=lambda proposal: (
                proposal.created_at,
                proposal.proposal_id,
            )
        )

        return ProposalListResult(
            success=True,
            proposals=tuple(proposals),
            issues=(),
        )

    def verify(self) -> ProposalVerificationResult:
        """Verify every repository entry without modifying anything."""
        if not self._root.exists():
            return ProposalVerificationResult(
                valid=False,
                checked_documents=0,
                issues=(
                    ProposalRepositoryIssue(
                        code="proposal_directory_missing",
                        message=(
                            "The configured proposal repository directory "
                            "does not exist."
                        ),
                        path=self._root,
                    ),
                ),
            )

        if not self._root.is_dir():
            return ProposalVerificationResult(
                valid=False,
                checked_documents=0,
                issues=(
                    ProposalRepositoryIssue(
                        code="proposal_directory_not_directory",
                        message=(
                            "The configured proposal repository path is not "
                            "a directory."
                        ),
                        path=self._root,
                    ),
                ),
            )

        try:
            entries = tuple(
                sorted(
                    self._root.iterdir(),
                    key=lambda path: path.name,
                )
            )
        except OSError:
            return ProposalVerificationResult(
                valid=False,
                checked_documents=0,
                issues=(
                    ProposalRepositoryIssue(
                        code="proposal_directory_read_failed",
                        message=(
                            "The proposal repository directory could not be inspected."
                        ),
                        path=self._root,
                    ),
                ),
            )

        checked_documents = 0
        issues: list[ProposalRepositoryIssue] = []

        for path in entries:
            if path.is_symlink():
                issues.append(
                    ProposalRepositoryIssue(
                        code="proposal_symbolic_link",
                        message=(
                            "Symbolic links are not permitted in the proposal "
                            "repository."
                        ),
                        path=path,
                    )
                )
                continue

            if path.name.startswith(".") and path.name.endswith(".tmp"):
                issues.append(
                    ProposalRepositoryIssue(
                        code="proposal_temporary_file",
                        message=("A leftover temporary proposal file was found."),
                        path=path,
                    )
                )
                continue

            if path.is_dir():
                issues.append(
                    ProposalRepositoryIssue(
                        code="proposal_unexpected_entry",
                        message=(
                            "An unexpected directory was found in the "
                            "proposal repository."
                        ),
                        path=path,
                    )
                )
                continue

            if path.suffix != ".md":
                issues.append(
                    ProposalRepositoryIssue(
                        code="proposal_unexpected_file",
                        message=(
                            "An unexpected non-Markdown file was found in "
                            "the proposal repository."
                        ),
                        path=path,
                    )
                )
                continue

            proposal_id = path.stem

            try:
                _validate_proposal_id(proposal_id)
            except (TypeError, ValueError):
                issues.append(
                    ProposalRepositoryIssue(
                        code="proposal_invalid_filename",
                        message=(
                            "A proposal document does not use a canonical "
                            "proposal identifier filename."
                        ),
                        path=path,
                    )
                )
                continue

            checked_documents += 1
            result = self.read(proposal_id)

            if not result.success:
                issues.extend(result.issues)

        return ProposalVerificationResult(
            valid=not issues,
            checked_documents=checked_documents,
            issues=tuple(issues),
        )

    def _inspect_root_for_listing(
        self,
    ) -> ProposalRepositoryIssue | None:
        """Check the repository root without creating anything."""
        if not self._root.exists():
            return ProposalRepositoryIssue(
                code="proposal_directory_missing",
                message=(
                    "The configured proposal repository directory does not exist."
                ),
                path=self._root,
            )

        if not self._root.is_dir():
            return ProposalRepositoryIssue(
                code="proposal_directory_not_directory",
                message=("The configured proposal repository path is not a directory."),
                path=self._root,
            )

        return None

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


def _replace_failure(
    *,
    code: str,
    message: str,
    proposal_id: str,
    path: Path,
    field: str | None = None,
) -> ProposalReplaceResult:
    """Construct one deterministic failed replacement result."""
    return ProposalReplaceResult(
        success=False,
        proposal=None,
        previous_proposal=None,
        path=path,
        issues=(
            ProposalRepositoryIssue(
                code=code,
                message=message,
                proposal_id=proposal_id,
                path=path,
                field=field,
            ),
        ),
    )


def _read_failure(
    *,
    code: str,
    message: str,
    proposal_id: str,
    path: Path,
) -> ProposalReadResult:
    """Construct one deterministic failed read result."""
    return ProposalReadResult(
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


def _list_failure(
    *,
    code: str,
    message: str,
    path: Path,
    proposal_id: str | None = None,
) -> ProposalListResult:
    """Construct one deterministic failed listing result."""
    return ProposalListResult(
        success=False,
        proposals=(),
        issues=(
            ProposalRepositoryIssue(
                code=code,
                message=message,
                proposal_id=proposal_id,
                path=path,
            ),
        ),
    )
