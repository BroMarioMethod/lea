"""Tests for deterministic task proposal builders."""

from datetime import UTC, datetime

import pytest

from lea.actions import (
    ActionStatus,
    ConfirmationPolicy,
    RiskLevel,
)
from lea.tasks import (
    TaskCreateRequest,
    TaskModifyRequest,
    build_task_complete_proposal,
    build_task_create_proposal,
    build_task_delete_proposal,
    build_task_modify_proposal,
)

PROPOSAL_ID = "11111111-1111-4111-8111-111111111111"
TASK_UUID = "22222222-2222-4222-8222-222222222222"
CREATED_AT = datetime(2026, 7, 29, 8, 0, tzinfo=UTC)
DUE = datetime(2026, 7, 30, 15, 30, tzinfo=UTC)
SOURCE = "telegram:owner"


def test_create_builder_assigns_low_risk_and_parameters() -> None:
    """Creation should preserve supported provider-neutral fields."""
    proposal = build_task_create_proposal(
        TaskCreateRequest(
            description="Prepare acceptance evidence",
            project="lea",
            due=DUE,
            priority="M",
            tags=("telegram-test", "acceptance"),
        ),
        proposal_id=PROPOSAL_ID,
        source=SOURCE,
        created_at=CREATED_AT,
    )

    assert proposal.action == "task.create"
    assert proposal.status is ActionStatus.PROPOSED
    assert proposal.risk_level is RiskLevel.LOW
    assert proposal.confirmation_policy is ConfirmationPolicy.WHEN_REQUIRED
    assert proposal.source == SOURCE
    assert proposal.created_at == CREATED_AT
    assert dict(proposal.parameters) == {
        "description": "Prepare acceptance evidence",
        "project": "lea",
        "due": DUE.isoformat(),
        "priority": "M",
        "tags": ("acceptance", "telegram_test"),
    }


def test_modify_builder_assigns_medium_risk_and_parameters() -> None:
    """Modification should serialise all supplied changes."""
    proposal = build_task_modify_proposal(
        TaskModifyRequest(
            task_uuid=TASK_UUID,
            description="Updated description",
            project="lea",
            due=DUE,
            priority="H",
            add_tags=("new-tag",),
            remove_tags=("old-tag",),
        ),
        proposal_id=PROPOSAL_ID,
        source=SOURCE,
        created_at=CREATED_AT,
    )

    assert proposal.action == "task.modify"
    assert proposal.risk_level is RiskLevel.MEDIUM
    assert dict(proposal.parameters) == {
        "uuid": TASK_UUID,
        "description": "Updated description",
        "project": "lea",
        "due": DUE.isoformat(),
        "priority": "H",
        "add_tags": ("new_tag",),
        "remove_tags": ("old_tag",),
    }


def test_modify_builder_preserves_clear_flags() -> None:
    """Explicit clearing must survive proposal construction."""
    proposal = build_task_modify_proposal(
        TaskModifyRequest(
            task_uuid=TASK_UUID,
            clear_due=True,
            clear_priority=True,
        ),
        proposal_id=PROPOSAL_ID,
        source=SOURCE,
        created_at=CREATED_AT,
    )

    assert dict(proposal.parameters) == {
        "uuid": TASK_UUID,
        "clear_due": True,
        "clear_priority": True,
    }


@pytest.mark.parametrize(
    ("factory", "action", "risk"),
    [
        (
            build_task_complete_proposal,
            "task.complete",
            RiskLevel.MEDIUM,
        ),
        (
            build_task_delete_proposal,
            "task.delete",
            RiskLevel.HIGH,
        ),
    ],
)
def test_exact_uuid_builders_assign_canonical_policy(
    factory: object,
    action: str,
    risk: RiskLevel,
) -> None:
    """Completion and deletion should use their specified risk."""
    assert callable(factory)
    proposal = factory(
        TASK_UUID,
        proposal_id=PROPOSAL_ID,
        source=SOURCE,
        created_at=CREATED_AT,
    )

    assert proposal.action == action
    assert proposal.risk_level is risk
    assert proposal.confirmation_policy is ConfirmationPolicy.WHEN_REQUIRED
    assert dict(proposal.parameters) == {"uuid": TASK_UUID}


@pytest.mark.parametrize(
    "task_uuid",
    [
        "not-a-uuid",
        "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
    ],
)
def test_exact_uuid_builders_reject_non_canonical_uuid(
    task_uuid: str,
) -> None:
    """Untrusted task identifiers must fail before proposal creation."""
    with pytest.raises(ValueError, match="task_uuid"):
        build_task_delete_proposal(
            task_uuid,
            proposal_id=PROPOSAL_ID,
            source=SOURCE,
            created_at=CREATED_AT,
        )


def test_builder_rejects_non_utc_timestamp() -> None:
    """Proposal creation timestamps must use canonical UTC."""
    non_utc = datetime.fromisoformat("2026-07-29T10:00:00+02:00")

    with pytest.raises(ValueError, match="must use UTC"):
        build_task_complete_proposal(
            TASK_UUID,
            proposal_id=PROPOSAL_ID,
            source=SOURCE,
            created_at=non_utc,
        )
