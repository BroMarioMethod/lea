"""Regression checks for the Milestone 4.1 planning documents."""

from pathlib import Path

_ROOT = Path(__file__).parents[1]


def test_milestone_4_1_documents_define_mvp_and_beta_boundary() -> None:
    """The MVP scope must remain distinct from experimental providers."""
    specification = (
        _ROOT / "docs/specifications/LEA-SPEC-0018_CALENDAR_COLLABORATION.md"
    ).read_text(encoding="utf-8")
    checklist = (
        _ROOT / "docs/development/RELEASE_CHECKLIST_MILESTONE_4.1.md"
    ).read_text(encoding="utf-8")
    test_card = (_ROOT / "docs/development/MILESTONE_4_1_TEST_CARD.md").read_text(
        encoding="utf-8"
    )

    assert "Google Calendar OAuth" in specification
    assert "not part of the 4.1 MVP acceptance gate" in specification
    assert "free/busy federation" in specification
    assert "Google OAuth and additional providers" in checklist
    assert "Do not use experimental OAuth/provider integrations" in test_card


def test_milestone_4_1_test_card_covers_collaboration_lifecycle() -> None:
    """The test card must cover recurrence, attendees and lifecycle safety."""
    test_card = (_ROOT / "docs/development/MILESTONE_4_1_TEST_CARD.md").read_text(
        encoding="utf-8"
    )

    for phrase in (
        "recurring timed event",
        "all-day recurring event",
        "explicit instance",
        "attendee response",
        "Synchronize in both directions",
        "restore into an isolated staging root",
        "Stop on recurrence timezone drift",
    ):
        assert phrase in test_card
