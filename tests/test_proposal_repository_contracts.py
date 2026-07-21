"""Tests for immutable proposal-repository result contracts."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lea.actions import ActionContractError, ActionProposal
from lea.proposals import (
    ProposalListResult,
    ProposalReadResult,
    ProposalRepositoryIssue,
    ProposalVerificationResult,
    ProposalWriteResult,
)

PROPOSAL_ID = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"


def create_proposal() -> ActionProposal:
    """Return one deterministic action proposal."""
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={"description": "Test task"},
        source="user",
        created_at=datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
        reason="Create a test task.",
    )


def create_issue() -> ProposalRepositoryIssue:
    """Return one deterministic repository issue."""
    return ProposalRepositoryIssue(
        code="proposal_not_found",
        message="The proposal document was not found.",
        proposal_id=PROPOSAL_ID,
        path=Path(f"/var/lib/lea/proposals/{PROPOSAL_ID}.md"),
    )


def test_repository_issue_accepts_structured_context() -> None:
    """Repository issues should preserve diagnostic context."""
    issue = ProposalRepositoryIssue(
        code="proposal_malformed_document",
        message="The proposal document is malformed.",
        proposal_id=PROPOSAL_ID,
        path=Path(f"/var/lib/lea/proposals/{PROPOSAL_ID}.md"),
        line_number=4,
        field="proposal_id",
    )
    assert issue.code == "proposal_malformed_document"
    assert issue.proposal_id == PROPOSAL_ID
    assert issue.line_number == 4
    assert issue.field == "proposal_id"


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("   ", "Repository failure."),
        ("proposal_read_failed", "   "),
    ],
)
def test_repository_issue_rejects_blank_required_fields(
    code: str,
    message: str,
) -> None:
    """Issue codes and messages must contain useful text."""
    with pytest.raises(ValueError, match="must be non-empty"):
        ProposalRepositoryIssue(code=code, message=message)


def test_repository_issue_rejects_relative_path() -> None:
    """Issue paths must be independent of the working directory."""
    with pytest.raises(ValueError, match="path must be an absolute path"):
        ProposalRepositoryIssue(
            code="proposal_read_failed",
            message="The proposal could not be read.",
            path=Path("proposal.md"),
        )


def test_repository_issue_rejects_invalid_line_number() -> None:
    """Physical line numbers must begin at one."""
    with pytest.raises(ValueError, match="line_number must be greater than zero"):
        ProposalRepositoryIssue(
            code="proposal_malformed_document",
            message="The proposal document is malformed.",
            line_number=0,
        )


def test_repository_issue_rejects_invalid_proposal_id() -> None:
    """Issue proposal identifiers must use the action contract."""
    with pytest.raises(ActionContractError, match="proposal_id must be a valid UUID"):
        ProposalRepositoryIssue(
            code="proposal_not_found",
            message="The proposal document was not found.",
            proposal_id="not-a-uuid",
        )


def test_repository_issue_is_immutable() -> None:
    """Repository issues must not permit reassignment."""
    issue = create_issue()
    with pytest.raises(FrozenInstanceError):
        issue.code = "changed"  # type: ignore[misc]


def test_successful_write_result() -> None:
    """Successful writes should contain proposal and path."""
    proposal = create_proposal()
    path = Path(f"/var/lib/lea/proposals/{PROPOSAL_ID}.md")
    result = ProposalWriteResult(success=True, proposal=proposal, path=path, issues=())
    assert result.proposal == proposal
    assert result.path == path


def test_successful_write_requires_proposal() -> None:
    """A successful write must expose the stored proposal."""
    with pytest.raises(ValueError, match="must contain a proposal"):
        ProposalWriteResult(
            success=True,
            proposal=None,
            path=Path("/var/lib/lea/proposals/proposal.md"),
            issues=(),
        )


def test_successful_write_requires_path() -> None:
    """A successful write must expose its destination."""
    with pytest.raises(ValueError, match="must contain a path"):
        ProposalWriteResult(
            success=True, proposal=create_proposal(), path=None, issues=()
        )


def test_failed_write_requires_issue() -> None:
    """Failed writes must provide structured failure information."""
    with pytest.raises(ValueError, match="must contain at least one issue"):
        ProposalWriteResult(success=False, proposal=None, path=None, issues=())


def test_failed_write_rejects_proposal() -> None:
    """Failed writes must not imply successful persistence."""
    with pytest.raises(ValueError, match="must not contain a proposal"):
        ProposalWriteResult(
            success=False,
            proposal=create_proposal(),
            path=None,
            issues=(create_issue(),),
        )


def test_successful_read_result() -> None:
    """Successful reads should contain proposal and source path."""
    result = ProposalReadResult(
        success=True,
        proposal=create_proposal(),
        path=Path(f"/var/lib/lea/proposals/{PROPOSAL_ID}.md"),
        issues=(),
    )
    assert result.success is True
    assert result.proposal is not None


def test_failed_read_requires_issue() -> None:
    """Failed reads must contain structured issues."""
    with pytest.raises(ValueError, match="must contain at least one issue"):
        ProposalReadResult(success=False, proposal=None, path=None, issues=())


def test_successful_list_may_be_empty() -> None:
    """An empty repository is a valid successful listing."""
    result = ProposalListResult(success=True, proposals=(), issues=())
    assert result.proposals == ()


def test_failed_list_rejects_proposals() -> None:
    """Failed listing must not return a partial proposal set."""
    with pytest.raises(ValueError, match="must not contain proposals"):
        ProposalListResult(
            success=False,
            proposals=(create_proposal(),),
            issues=(create_issue(),),
        )


def test_failed_list_requires_issue() -> None:
    """Failed listing must explain its failure."""
    with pytest.raises(ValueError, match="must contain at least one issue"):
        ProposalListResult(success=False, proposals=(), issues=())


def test_valid_verification_result() -> None:
    """A valid repository may contain no documents."""
    result = ProposalVerificationResult(valid=True, checked_documents=0, issues=())
    assert result.valid is True


def test_invalid_verification_requires_issue() -> None:
    """Invalid verification must expose repository problems."""
    with pytest.raises(ValueError, match="must contain at least one issue"):
        ProposalVerificationResult(valid=False, checked_documents=0, issues=())


def test_valid_verification_rejects_issue() -> None:
    """A valid verification result cannot contain failures."""
    with pytest.raises(ValueError, match="must not contain issues"):
        ProposalVerificationResult(
            valid=True,
            checked_documents=1,
            issues=(create_issue(),),
        )


def test_verification_rejects_negative_count() -> None:
    """Checked document counts cannot be negative."""
    with pytest.raises(ValueError, match="must not be negative"):
        ProposalVerificationResult(valid=True, checked_documents=-1, issues=())


def test_write_result_is_immutable() -> None:
    """Write results must be immutable."""
    result = ProposalWriteResult(
        success=True,
        proposal=create_proposal(),
        path=Path(f"/var/lib/lea/proposals/{PROPOSAL_ID}.md"),
        issues=(),
    )
    with pytest.raises(FrozenInstanceError):
        result.success = False  # type: ignore[misc]


def test_read_result_is_immutable() -> None:
    """Read results must be immutable."""
    result = ProposalReadResult(
        success=True,
        proposal=create_proposal(),
        path=Path(f"/var/lib/lea/proposals/{PROPOSAL_ID}.md"),
        issues=(),
    )
    with pytest.raises(FrozenInstanceError):
        result.success = False  # type: ignore[misc]


def test_list_result_is_immutable() -> None:
    """List results must be immutable."""
    result = ProposalListResult(
        success=True,
        proposals=(create_proposal(),),
        issues=(),
    )
    with pytest.raises(FrozenInstanceError):
        result.success = False  # type: ignore[misc]


def test_verification_result_is_immutable() -> None:
    """Verification results must be immutable."""
    result = ProposalVerificationResult(valid=True, checked_documents=1, issues=())
    with pytest.raises(FrozenInstanceError):
        result.valid = False  # type: ignore[misc]
