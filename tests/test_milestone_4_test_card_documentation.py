"""Regression checks for the Milestone 4 physical-card procedure."""

from pathlib import Path

_DOCUMENT = (
    Path(__file__).parents[1] / "docs" / "development" / "MILESTONE_4_TEST_CARD.md"
)


def test_milestone_4_test_card_covers_every_release_gate() -> None:
    """The physical-card runbook must retain all required lifecycle gates."""
    document = _DOCUMENT.read_text(encoding="utf-8")

    required_sections = (
        "Gate 0 — Select and identify the candidate",
        "Gate 2 — Candidate self-check",
        "Gate 4 — Install through the supported entry point",
        "Gate 5 — Root ownership, mode and readability",
        "Gate 7 — Local calendar and orchestration chain",
        "Gate 8 — Radicale health and reciprocal isolation",
        "Gate 10 — DAVx⁵ and Android two-way acceptance",
        "Gate 11 — Backup and isolated restore",
        "Gate 13 — Reboot persistence",
        "Gate 14 — Repair, upgrade and rollback",
        "Gate 15 — Removal and credential revocation",
        "Gate 16 — Record results and decide",
    )

    for section in required_sections:
        assert section in document


def test_milestone_4_test_card_preserves_safety_boundaries() -> None:
    """The runbook must keep secrets out of Git and stop on partial evidence."""
    document = _DOCUMENT.read_text(encoding="utf-8")

    assert "Never record Telegram tokens, CalDAV passwords" in document
    assert "Do not skip to live Android testing" in document
    assert "approval does not itself create the event" in document
    assert "A copied archive without a successful isolated restore" in document
    assert "Do not tag a repair-only result" in document
