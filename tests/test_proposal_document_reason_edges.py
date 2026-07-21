"""Tests for proposal-document reason edge cases."""

from datetime import UTC, datetime
from pathlib import Path

from lea.actions import ActionProposal
from lea.proposals import (
    MarkdownProposalRepository,
    parse_proposal_document,
    render_proposal_document,
)

PROPOSAL_ID = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"


def create_proposal(
    *,
    reason: str | None,
) -> ActionProposal:
    """Return one deterministic proposal with the requested reason."""
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={"description": "Test task"},
        source="user",
        created_at=datetime(
            2026,
            7,
            21,
            12,
            0,
            tzinfo=UTC,
        ),
        reason=reason,
    )


def assert_round_trip(
    reason: str | None,
) -> None:
    """Assert deterministic document round-trip behaviour."""
    proposal = create_proposal(reason=reason)
    document = render_proposal_document(proposal)
    result = parse_proposal_document(document)

    assert result.success is True
    assert result.proposal == proposal
    assert result.issues == ()
    assert render_proposal_document(result.proposal) == document


def test_reason_none_round_trips() -> None:
    """An absent reason should remain distinct from literal text."""
    assert_round_trip(None)


def test_literal_not_provided_round_trips() -> None:
    """Literal placeholder text must not become a missing reason."""
    assert_round_trip("Not provided.")


def test_multiline_reason_round_trips() -> None:
    """Line breaks in a reason should be preserved exactly."""
    assert_round_trip("First line.\nSecond line.\nThird line.")


def test_reason_with_blank_lines_round_trips() -> None:
    """Paragraph breaks should survive persistence."""
    assert_round_trip("First paragraph.\n\nSecond paragraph.")


def test_reason_with_markdown_round_trips() -> None:
    """Markdown-like reason content should remain ordinary data."""
    assert_round_trip(
        "# Heading inside reason\n\n"
        "- first item\n"
        "- second item\n\n"
        "```text\n"
        "example\n"
        "```"
    )


def test_reason_resembling_parameters_section_round_trips() -> None:
    """Reason text must not terminate parsing accidentally."""
    assert_round_trip(
        "Discussion follows.\n\n"
        "## Parameters\n\n"
        "```json\n"
        '{"not":"the real parameters"}\n'
        "```"
    )


def test_reason_resembling_metadata_round_trips() -> None:
    """Reserved metadata-like text should be escaped canonically."""
    assert_round_trip('<!-- lea-reason-json: "not metadata" -->')


def test_literal_placeholder_uses_lossless_metadata() -> None:
    """Ambiguous literal text should carry deterministic metadata."""
    proposal = create_proposal(reason="Not provided.")
    document = render_proposal_document(proposal)

    assert '<!-- lea-reason-json: "Not provided." -->' in document


def test_simple_reason_keeps_existing_readable_format() -> None:
    """Ordinary single-line reasons should not gain metadata noise."""
    proposal = create_proposal(reason="Create a test task.")
    document = render_proposal_document(proposal)

    assert "<!-- lea-reason-json:" not in document
    assert "\nCreate a test task.\n" in document


def test_multiline_reason_remains_human_readable() -> None:
    """Lossless metadata should accompany visible reason prose."""
    proposal = create_proposal(reason="First paragraph.\n\nSecond paragraph.")
    document = render_proposal_document(proposal)

    assert "\nFirst paragraph.\n\nSecond paragraph.\n" in document


def test_repository_create_and_read_preserve_multiline_reason(
    tmp_path: Path,
) -> None:
    """Filesystem persistence should preserve a multiline reason."""
    repository = MarkdownProposalRepository(
        tmp_path / "proposals",
        create_parents=True,
    )
    proposal = create_proposal(reason="First paragraph.\n\nSecond paragraph.")

    write_result = repository.create(proposal)
    read_result = repository.read(PROPOSAL_ID)

    assert write_result.success is True
    assert read_result.success is True
    assert read_result.proposal == proposal


def test_repository_list_preserves_literal_placeholder(
    tmp_path: Path,
) -> None:
    """Listing must preserve literal placeholder text as data."""
    repository = MarkdownProposalRepository(
        tmp_path / "proposals",
        create_parents=True,
    )
    proposal = create_proposal(reason="Not provided.")

    assert repository.create(proposal).success is True

    result = repository.list_all()

    assert result.success is True
    assert result.proposals == (proposal,)


def test_repository_verifies_edge_case_documents(
    tmp_path: Path,
) -> None:
    """Canonical edge-case documents should verify successfully."""
    repository = MarkdownProposalRepository(
        tmp_path / "proposals",
        create_parents=True,
    )
    proposal = create_proposal(
        reason=("# Why\n\nThis reason contains Markdown and blank lines.")
    )

    assert repository.create(proposal).success is True

    result = repository.verify()

    assert result.valid is True
    assert result.checked_documents == 1
    assert result.issues == ()
