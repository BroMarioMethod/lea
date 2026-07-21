"""Tests for deterministic Markdown proposal documents."""

from datetime import UTC, datetime

import pytest

from lea.actions import (
    ActionProposal,
    ActionStatus,
    ConfirmationPolicy,
    RiskLevel,
)
from lea.proposals import (
    DOCUMENT_SCHEMA_VERSION,
    parse_proposal_document,
    render_proposal_document,
)

PROPOSAL_ID = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"


def create_proposal(
    *,
    reason: str | None = "Create a test task.",
) -> ActionProposal:
    """Return one deterministic proposal."""
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={
            "description": "Test task",
            "metadata": {
                "priority": 2,
                "labels": ["test", "local"],
            },
        },
        status=ActionStatus.PROPOSED,
        risk_level=RiskLevel.MEDIUM,
        confirmation_policy=(ConfirmationPolicy.WHEN_REQUIRED),
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


def test_document_schema_version() -> None:
    """The document format should expose a stable schema version."""
    assert DOCUMENT_SCHEMA_VERSION == 1


def test_rendered_document_has_canonical_front_matter() -> None:
    """Proposal metadata should use stable field ordering."""
    rendered = render_proposal_document(create_proposal())

    assert rendered.startswith(
        "---\n"
        "schema_version: 1\n"
        f"proposal_id: {PROPOSAL_ID}\n"
        "action: task.create\n"
        "status: proposed\n"
        "risk_level: medium\n"
        "confirmation_policy: when_required\n"
        'source: "user"\n'
        "created_at: 2026-07-21T12:00:00+00:00\n"
        "---\n"
    )


def test_rendered_parameters_are_compact_and_sorted() -> None:
    """Parameter JSON should be deterministic."""
    rendered = render_proposal_document(create_proposal())

    assert (
        '{"description":"Test task","metadata":'
        '{"labels":["test","local"],"priority":2}}'
    ) in rendered


def test_rendered_document_ends_with_one_newline() -> None:
    """Documents should use one stable trailing newline."""
    rendered = render_proposal_document(create_proposal())

    assert rendered.endswith("\n")
    assert not rendered.endswith("\n\n")


def test_rendering_is_deterministic() -> None:
    """Identical proposals should render identically."""
    proposal = create_proposal()

    assert render_proposal_document(proposal) == render_proposal_document(proposal)


def test_missing_reason_is_rendered_explicitly() -> None:
    """Absent reasons should remain human-readable."""
    rendered = render_proposal_document(create_proposal(reason=None))

    assert "## Reason\n\nNot provided.\n" in rendered


def test_document_round_trip() -> None:
    """Canonical Markdown should reconstruct the proposal."""
    proposal = create_proposal()

    result = parse_proposal_document(render_proposal_document(proposal))

    assert result.success is True
    assert result.proposal == proposal
    assert result.issues == ()


def test_document_without_reason_round_trips() -> None:
    """The explicit placeholder should restore a null reason."""
    proposal = create_proposal(reason=None)

    result = parse_proposal_document(render_proposal_document(proposal))

    assert result.success is True
    assert result.proposal == proposal
    assert result.proposal is not None
    assert result.proposal.reason is None


def test_missing_final_newline_is_rejected() -> None:
    """Canonical documents must be newline terminated."""
    rendered = render_proposal_document(create_proposal())

    result = parse_proposal_document(rendered.rstrip("\n"))

    assert result.success is False
    assert result.issues[0].code == "proposal_malformed_document"


def test_missing_front_matter_is_rejected() -> None:
    """Documents must begin with deterministic front matter."""
    result = parse_proposal_document("# Action Proposal\n")

    assert result.success is False
    assert result.issues[0].code == "proposal_malformed_document"


def test_unclosed_front_matter_is_rejected() -> None:
    """Front matter must contain a closing delimiter."""
    result = parse_proposal_document("---\nschema_version: 1\n")

    assert result.success is False
    assert result.issues[0].code == "proposal_malformed_document"


def test_unknown_front_matter_field_is_rejected() -> None:
    """Unknown metadata must fail closed."""
    rendered = render_proposal_document(create_proposal())
    changed = rendered.replace(
        "action: task.create\n",
        "action: task.create\nunexpected: value\n",
    )

    result = parse_proposal_document(changed)

    assert result.success is False
    assert result.issues[0].code == "proposal_unknown_field"
    assert result.issues[0].field == "unexpected"


def test_missing_front_matter_field_is_rejected() -> None:
    """Every required metadata field must be present."""
    rendered = render_proposal_document(create_proposal())
    changed = rendered.replace(
        "risk_level: medium\n",
        "",
    )

    result = parse_proposal_document(changed)

    assert result.success is False
    assert result.issues[0].code == "proposal_missing_field"
    assert result.issues[0].field == "risk_level"


def test_unsupported_document_schema_is_rejected() -> None:
    """Unknown document versions must fail explicitly."""
    rendered = render_proposal_document(create_proposal())
    changed = rendered.replace(
        "schema_version: 1",
        "schema_version: 2",
    )

    result = parse_proposal_document(changed)

    assert result.success is False
    assert result.issues[0].code == "proposal_unsupported_schema_version"


def test_front_matter_order_is_canonical() -> None:
    """Valid fields in another order should be rejected."""
    rendered = render_proposal_document(create_proposal())
    changed = rendered.replace(
        f"proposal_id: {PROPOSAL_ID}\naction: task.create\n",
        f"action: task.create\nproposal_id: {PROPOSAL_ID}\n",
    )

    result = parse_proposal_document(changed)

    assert result.success is False
    assert result.issues[0].code == "proposal_non_canonical_document"


def test_malformed_parameter_json_is_rejected() -> None:
    """The fenced parameters value must contain valid JSON."""
    rendered = render_proposal_document(create_proposal())
    changed = rendered.replace(
        '{"description":"Test task","metadata":'
        '{"labels":["test","local"],"priority":2}}',
        '{"description":',
    )

    result = parse_proposal_document(changed)

    assert result.success is False
    assert result.issues[0].code == "proposal_invalid_parameters"


def test_non_object_parameters_are_rejected() -> None:
    """Parameters must remain a JSON object."""
    rendered = render_proposal_document(create_proposal())
    changed = rendered.replace(
        '{"description":"Test task","metadata":'
        '{"labels":["test","local"],"priority":2}}',
        '["invalid"]',
    )

    result = parse_proposal_document(changed)

    assert result.success is False
    assert result.issues[0].code == "proposal_invalid_parameters"


def test_invalid_proposal_contract_is_rejected() -> None:
    """Parsed fields must pass the existing action contract."""
    rendered = render_proposal_document(create_proposal())
    changed = rendered.replace(
        "action: task.create",
        "action: INVALID",
    )

    result = parse_proposal_document(changed)

    assert result.success is False
    assert result.issues[0].code == "proposal_invalid_contract"


def test_non_canonical_parameter_spacing_is_rejected() -> None:
    """Semantically valid but non-canonical JSON should fail."""
    rendered = render_proposal_document(create_proposal())
    changed = rendered.replace(
        '{"description":"Test task","metadata":'
        '{"labels":["test","local"],"priority":2}}',
        '{"description": "Test task", "metadata": '
        '{"labels": ["test", "local"], "priority": 2}}',
    )

    result = parse_proposal_document(changed)

    assert result.success is False
    assert result.issues[0].code == "proposal_non_canonical_document"


def test_unexpected_content_after_parameters_is_rejected() -> None:
    """Content after the canonical JSON fence is forbidden."""
    rendered = render_proposal_document(create_proposal())
    changed = rendered + "Unexpected\n"

    result = parse_proposal_document(changed)

    assert result.success is False
    assert result.issues[0].code == "proposal_malformed_document"


def test_blank_reason_is_rejected() -> None:
    """Reason content must be explicit or use the placeholder."""
    rendered = render_proposal_document(create_proposal())
    changed = rendered.replace(
        "Create a test task.",
        "",
    )

    result = parse_proposal_document(changed)

    assert result.success is False
    assert result.issues[0].code == "proposal_malformed_document"


def test_non_string_document_is_rejected() -> None:
    """The parser boundary should require text."""
    with pytest.raises(
        TypeError,
        match="document must be a string",
    ):
        parse_proposal_document(123)  # type: ignore[arg-type]
