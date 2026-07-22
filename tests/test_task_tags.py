"""Tests for provider-neutral task-tag normalisation."""

import pytest

from lea.tasks import normalise_task_tag


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("local-cli", "local_cli"),
        (" sales-followup ", "sales_followup"),
        ("urgent", "urgent"),
        ("_internal2", "_internal2"),
    ],
)
def test_normalise_task_tag_returns_canonical_values(
    raw: str,
    canonical: str,
) -> None:
    """Common safe inputs should normalise deterministically."""
    assert normalise_task_tag(raw) == canonical


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "2urgent", "+next", "client/work", "has space"],
)
def test_normalise_task_tag_rejects_unsupported_values(raw: str) -> None:
    """Unsupported values must not be silently rewritten."""
    with pytest.raises(ValueError):
        normalise_task_tag(raw)
