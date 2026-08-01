"""Tests for deterministic calendar read proposal builders."""

from datetime import UTC, date, datetime

import pytest

from lea.actions import (
    ActionStatus,
    ConfirmationPolicy,
    RiskLevel,
)
from lea.calendars import (
    CalendarEventQuery,
    build_calendar_list_calendars_proposal,
    build_calendar_list_events_proposal,
    build_calendar_show_event_proposal,
)

PROPOSAL_ID = "11111111-1111-4111-8111-111111111111"
CREATED_AT = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)
SOURCE = "telegram:owner"


def test_list_calendars_builder_assigns_canonical_read_policy() -> None:
    """Calendar discovery should be one low-risk provider-neutral action."""
    proposal = build_calendar_list_calendars_proposal(
        proposal_id=PROPOSAL_ID,
        source=SOURCE,
        created_at=CREATED_AT,
    )

    assert proposal.action == "calendar.list_calendars"
    assert proposal.status is ActionStatus.PROPOSED
    assert proposal.risk_level is RiskLevel.LOW
    assert proposal.confirmation_policy is ConfirmationPolicy.WHEN_REQUIRED
    assert proposal.source == SOURCE
    assert proposal.created_at == CREATED_AT
    assert proposal.reason == "List available calendars."
    assert dict(proposal.parameters) == {}


def test_list_events_builder_preserves_canonical_query() -> None:
    """A provider-neutral query should become stable serialised parameters."""
    proposal = build_calendar_list_events_proposal(
        CalendarEventQuery(
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 4),
            calendar_ids=("work", "personal", "work"),
            include_cancelled=True,
        ),
        proposal_id=PROPOSAL_ID,
        source=SOURCE,
        created_at=CREATED_AT,
    )

    assert proposal.action == "calendar.list_events"
    assert proposal.risk_level is RiskLevel.LOW
    assert proposal.confirmation_policy is ConfirmationPolicy.WHEN_REQUIRED
    assert proposal.reason == "List calendar events."
    assert dict(proposal.parameters) == {
        "start_date": "2026-08-01",
        "end_date": "2026-08-04",
        "calendar_ids": ("personal", "work"),
        "include_cancelled": True,
    }


def test_list_events_builder_omits_default_optional_parameters() -> None:
    """False and empty query options should not create ambiguous proposal data."""
    proposal = build_calendar_list_events_proposal(
        CalendarEventQuery(
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
        ),
        proposal_id=PROPOSAL_ID,
        source=SOURCE,
        created_at=CREATED_AT,
    )

    assert dict(proposal.parameters) == {
        "start_date": "2026-08-01",
        "end_date": "2026-08-02",
    }


def test_show_event_builder_preserves_composite_identity() -> None:
    """Exact lookup must retain both opaque identity components unchanged."""
    proposal = build_calendar_show_event_proposal(
        "personal",
        "event-uid",
        proposal_id=PROPOSAL_ID,
        source=SOURCE,
        created_at=CREATED_AT,
    )

    assert proposal.action == "calendar.show_event"
    assert proposal.risk_level is RiskLevel.LOW
    assert proposal.confirmation_policy is ConfirmationPolicy.WHEN_REQUIRED
    assert proposal.reason == "Show one exact calendar event."
    assert dict(proposal.parameters) == {
        "calendar_id": "personal",
        "event_uid": "event-uid",
    }


@pytest.mark.parametrize(
    ("calendar_id", "event_uid", "message"),
    [
        ("", "event-uid", "calendar_id"),
        (" personal", "event-uid", "calendar_id"),
        ("personal", " ", "event_uid"),
        ("personal", "event\nuid", "event_uid"),
    ],
)
def test_show_event_builder_rejects_invalid_identifiers(
    calendar_id: str,
    event_uid: str,
    message: str,
) -> None:
    """Untrusted provider identities should fail before proposal creation."""
    with pytest.raises(ValueError, match=message):
        build_calendar_show_event_proposal(
            calendar_id,
            event_uid,
            proposal_id=PROPOSAL_ID,
            source=SOURCE,
            created_at=CREATED_AT,
        )


def test_list_events_builder_rejects_invalid_query_type() -> None:
    """Programming errors should fail before constructing an action."""
    with pytest.raises(TypeError, match="CalendarEventQuery"):
        build_calendar_list_events_proposal(
            object(),  # type: ignore[arg-type]
            proposal_id=PROPOSAL_ID,
            source=SOURCE,
            created_at=CREATED_AT,
        )


@pytest.mark.parametrize(
    "created_at",
    [
        datetime(2026, 8, 1, 8, 0),
        datetime.fromisoformat("2026-08-01T10:00:00+02:00"),
    ],
)
def test_builders_reject_non_canonical_proposal_timestamp(
    created_at: datetime,
) -> None:
    """Proposal creation time must be timezone-aware canonical UTC."""
    with pytest.raises(ValueError, match="Calendar proposal timestamps"):
        build_calendar_list_calendars_proposal(
            proposal_id=PROPOSAL_ID,
            source=SOURCE,
            created_at=created_at,
        )
