"""Immutable result contracts for persistent proposal repositories."""

from dataclasses import dataclass
from pathlib import Path

from lea.actions import ActionProposal


@dataclass(frozen=True, slots=True)
class ProposalRepositoryIssue:
    """One structured proposal-repository problem."""

    code: str
    message: str
    proposal_id: str | None = None
    path: Path | None = None
    line_number: int | None = None
    field: str | None = None

    def __post_init__(self) -> None:
        """Validate repository-issue fields."""
        if not self.code.strip():
            raise ValueError("Proposal repository issue code must be non-empty.")

        if not self.message.strip():
            raise ValueError("Proposal repository issue message must be non-empty.")

        if self.proposal_id is not None:
            _validate_proposal_id(self.proposal_id)

        if self.path is not None:
            _validate_absolute_path(
                self.path,
                field_name="path",
            )

        if self.line_number is not None and self.line_number < 1:
            raise ValueError(
                "Proposal repository issue line_number must be greater than zero."
            )

        if self.field is not None and not self.field.strip():
            raise ValueError(
                "Proposal repository issue field must be non-empty when provided."
            )


@dataclass(frozen=True, slots=True)
class ProposalDocumentResult:
    """Immutable result of parsing one proposal document."""

    success: bool
    proposal: ActionProposal | None
    issues: tuple[ProposalRepositoryIssue, ...]

    def __post_init__(self) -> None:
        """Validate proposal-document result consistency."""
        if self.success:
            if self.proposal is None:
                raise ValueError(
                    "A successful proposal document result must contain a proposal."
                )

            if self.issues:
                raise ValueError(
                    "A successful proposal document result must not contain issues."
                )

            return

        if self.proposal is not None:
            raise ValueError(
                "A failed proposal document result must not contain a proposal."
            )

        if not self.issues:
            raise ValueError(
                "A failed proposal document result must contain at least one issue."
            )


@dataclass(frozen=True, slots=True)
class ProposalWriteResult:
    """Immutable result of creating one proposal document."""

    success: bool
    proposal: ActionProposal | None
    path: Path | None
    issues: tuple[ProposalRepositoryIssue, ...]

    def __post_init__(self) -> None:
        """Validate proposal-write result consistency."""
        if self.success:
            if self.proposal is None:
                raise ValueError("A successful proposal write must contain a proposal.")

            if self.path is None:
                raise ValueError("A successful proposal write must contain a path.")

            if self.issues:
                raise ValueError("A successful proposal write must not contain issues.")

            _validate_absolute_path(
                self.path,
                field_name="path",
            )
            return

        if self.proposal is not None:
            raise ValueError("A failed proposal write must not contain a proposal.")

        if not self.issues:
            raise ValueError("A failed proposal write must contain at least one issue.")

        if self.path is not None:
            _validate_absolute_path(
                self.path,
                field_name="path",
            )


@dataclass(frozen=True, slots=True)
class ProposalReplaceResult:
    """Immutable result of atomically replacing one proposal document."""

    success: bool
    proposal: ActionProposal | None
    previous_proposal: ActionProposal | None
    path: Path | None
    issues: tuple[ProposalRepositoryIssue, ...]

    def __post_init__(self) -> None:
        """Validate proposal-replacement result consistency."""
        if self.success:
            if self.proposal is None:
                raise ValueError(
                    "A successful proposal replacement must contain a proposal."
                )

            if self.previous_proposal is None:
                raise ValueError(
                    "A successful proposal replacement must contain "
                    "the previous proposal."
                )

            if self.path is None:
                raise ValueError(
                    "A successful proposal replacement must contain a path."
                )

            if self.issues:
                raise ValueError(
                    "A successful proposal replacement must not contain issues."
                )

            _validate_absolute_path(
                self.path,
                field_name="path",
            )
            return

        if self.proposal is not None:
            raise ValueError(
                "A failed proposal replacement must not contain a proposal."
            )

        if not self.issues:
            raise ValueError(
                "A failed proposal replacement must contain at least one issue."
            )

        if self.path is not None:
            _validate_absolute_path(
                self.path,
                field_name="path",
            )


@dataclass(frozen=True, slots=True)
class ProposalReadResult:
    """Immutable result of reading one proposal document."""

    success: bool
    proposal: ActionProposal | None
    path: Path | None
    issues: tuple[ProposalRepositoryIssue, ...]

    def __post_init__(self) -> None:
        """Validate proposal-read result consistency."""
        if self.success:
            if self.proposal is None:
                raise ValueError("A successful proposal read must contain a proposal.")

            if self.path is None:
                raise ValueError("A successful proposal read must contain a path.")

            if self.issues:
                raise ValueError("A successful proposal read must not contain issues.")

            _validate_absolute_path(
                self.path,
                field_name="path",
            )
            return

        if self.proposal is not None:
            raise ValueError("A failed proposal read must not contain a proposal.")

        if not self.issues:
            raise ValueError("A failed proposal read must contain at least one issue.")

        if self.path is not None:
            _validate_absolute_path(
                self.path,
                field_name="path",
            )


@dataclass(frozen=True, slots=True)
class ProposalListResult:
    """Immutable result of listing proposal documents."""

    success: bool
    proposals: tuple[ActionProposal, ...]
    issues: tuple[ProposalRepositoryIssue, ...]

    def __post_init__(self) -> None:
        """Validate proposal-list result consistency."""
        if self.success and self.issues:
            raise ValueError("A successful proposal list must not contain issues.")

        if not self.success:
            if self.proposals:
                raise ValueError("A failed proposal list must not contain proposals.")

            if not self.issues:
                raise ValueError(
                    "A failed proposal list must contain at least one issue."
                )


@dataclass(frozen=True, slots=True)
class ProposalVerificationResult:
    """Immutable result of read-only repository verification."""

    valid: bool
    checked_documents: int
    issues: tuple[ProposalRepositoryIssue, ...]

    def __post_init__(self) -> None:
        """Validate proposal-verification result consistency."""
        if self.checked_documents < 0:
            raise ValueError("checked_documents must not be negative.")

        if self.valid and self.issues:
            raise ValueError("A valid proposal repository must not contain issues.")

        if not self.valid and not self.issues:
            raise ValueError(
                "An invalid proposal repository must contain at least one issue."
            )


def _validate_proposal_id(
    proposal_id: str,
) -> None:
    """Reuse the canonical ActionProposal identifier contract."""
    ActionProposal(
        proposal_id=proposal_id,
        action="repository.validate",
        parameters={},
        source="system",
    )


def _validate_absolute_path(
    path: Path,
    *,
    field_name: str,
) -> None:
    """Validate one absolute pathlib path."""
    if not isinstance(path, Path):
        raise TypeError(f"{field_name} must be a pathlib.Path value.")

    if not path.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path.")

    if "\x00" in str(path):
        raise ValueError(f"{field_name} must not contain a null byte.")
