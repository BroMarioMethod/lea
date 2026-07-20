"""Tests for append-only LEA JSONL audit storage."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from lea.actions import ActionContractError
from lea.audit import (
    AuditEvent,
    AuditEventType,
    AuditStoreError,
    JsonlAuditStore,
)

EVENT_ID_1 = "11111111-1111-4111-8111-111111111111"
EVENT_ID_2 = "22222222-2222-4222-8222-222222222222"

PROPOSAL_ID_1 = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"
PROPOSAL_ID_2 = "93278e90-a17c-452f-863a-34b270df73d8"

OCCURRED_AT_1 = datetime(2026, 7, 20, 18, 0, tzinfo=UTC)
OCCURRED_AT_2 = datetime(2026, 7, 20, 18, 5, tzinfo=UTC)


def create_event(
    *,
    event_id: str = EVENT_ID_1,
    proposal_id: str = PROPOSAL_ID_1,
    event_type: AuditEventType = AuditEventType.PROPOSAL_CREATED,
    occurred_at: datetime = OCCURRED_AT_1,
) -> AuditEvent:
    """Create a deterministic event for audit-store tests."""
    return AuditEvent(
        event_id=event_id,
        proposal_id=proposal_id,
        event_type=event_type,
        occurred_at=occurred_at,
        payload={
            "message": "Created £10 invoice",
            "items": ["one", "two"],
        },
    )


def test_missing_store_returns_empty_tuple(
    tmp_path: Path,
) -> None:
    """A missing audit file should represent an empty store."""
    store = JsonlAuditStore(tmp_path / "missing.jsonl")

    assert store.read_all() == ()


def test_append_creates_missing_file(
    tmp_path: Path,
) -> None:
    """Appending should create the configured file when its parent exists."""
    path = tmp_path / "actions.jsonl"
    store = JsonlAuditStore(path)

    store.append(create_event())

    assert path.is_file()


def test_append_can_create_missing_parent_directories(
    tmp_path: Path,
) -> None:
    """Parent creation should occur only when explicitly enabled."""
    path = tmp_path / "runtime" / "audit" / "actions.jsonl"
    store = JsonlAuditStore(
        path,
        create_parents=True,
    )

    store.append(create_event())

    assert path.is_file()


def test_missing_parent_fails_when_creation_is_disabled(
    tmp_path: Path,
) -> None:
    """The default store should not silently create parent directories."""
    path = tmp_path / "missing" / "actions.jsonl"
    store = JsonlAuditStore(path)

    with pytest.raises(
        AuditStoreError,
        match="Could not append",
    ):
        store.append(create_event())

    assert not path.exists()


def test_append_writes_one_compact_json_object_per_line(
    tmp_path: Path,
) -> None:
    """Stored events should use deterministic compact JSON."""
    path = tmp_path / "actions.jsonl"
    store = JsonlAuditStore(path)
    event = create_event()

    store.append(event)

    expected = json.dumps(
        event.to_dict(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    assert path.read_text(encoding="utf-8") == f"{expected}\n"


def test_append_uses_utf8_without_ascii_escaping(
    tmp_path: Path,
) -> None:
    """Unicode payload text should be stored directly as UTF-8."""
    path = tmp_path / "actions.jsonl"
    store = JsonlAuditStore(path)

    store.append(create_event())

    contents = path.read_text(encoding="utf-8")

    assert "£10" in contents
    assert "\\u00a3" not in contents


def test_append_preserves_existing_events(
    tmp_path: Path,
) -> None:
    """Appending another event should preserve prior bytes."""
    path = tmp_path / "actions.jsonl"
    store = JsonlAuditStore(path)

    first = create_event()
    second = create_event(
        event_id=EVENT_ID_2,
        occurred_at=OCCURRED_AT_2,
        event_type=AuditEventType.VALIDATION_COMPLETED,
    )

    store.append(first)
    first_contents = path.read_bytes()

    store.append(second)

    assert path.read_bytes().startswith(first_contents)
    assert store.read_all() == (first, second)


def test_read_all_preserves_physical_file_order(
    tmp_path: Path,
) -> None:
    """Events should be returned in append order, not timestamp order."""
    path = tmp_path / "actions.jsonl"
    store = JsonlAuditStore(path)

    later_timestamp = create_event(
        event_id=EVENT_ID_1,
        occurred_at=OCCURRED_AT_2,
    )
    earlier_timestamp = create_event(
        event_id=EVENT_ID_2,
        occurred_at=OCCURRED_AT_1,
    )

    store.append(later_timestamp)
    store.append(earlier_timestamp)

    assert store.read_all() == (
        later_timestamp,
        earlier_timestamp,
    )


def test_read_for_proposal_filters_exactly(
    tmp_path: Path,
) -> None:
    """Proposal retrieval should return only exact identifier matches."""
    path = tmp_path / "actions.jsonl"
    store = JsonlAuditStore(path)

    first = create_event()
    second = create_event(
        event_id=EVENT_ID_2,
        proposal_id=PROPOSAL_ID_2,
        occurred_at=OCCURRED_AT_2,
    )

    store.append(first)
    store.append(second)

    assert store.read_for_proposal(PROPOSAL_ID_1) == (first,)
    assert store.read_for_proposal(PROPOSAL_ID_2) == (second,)


def test_filtered_retrieval_preserves_file_order(
    tmp_path: Path,
) -> None:
    """Filtering should not reorder matching proposal events."""
    path = tmp_path / "actions.jsonl"
    store = JsonlAuditStore(path)

    first = create_event()
    unrelated = create_event(
        event_id="33333333-3333-4333-8333-333333333333",
        proposal_id=PROPOSAL_ID_2,
    )
    second = create_event(
        event_id=EVENT_ID_2,
        occurred_at=OCCURRED_AT_2,
        event_type=AuditEventType.VALIDATION_COMPLETED,
    )

    store.append(first)
    store.append(unrelated)
    store.append(second)

    assert store.read_for_proposal(PROPOSAL_ID_1) == (
        first,
        second,
    )


@pytest.mark.parametrize(
    "proposal_id",
    [
        "not-a-uuid",
        "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
    ],
)
def test_read_for_proposal_rejects_invalid_identifier(
    tmp_path: Path,
    proposal_id: str,
) -> None:
    """Proposal filtering should require canonical UUID identifiers."""
    store = JsonlAuditStore(tmp_path / "actions.jsonl")

    with pytest.raises(ActionContractError):
        store.read_for_proposal(proposal_id)


def test_malformed_json_reports_line_number(
    tmp_path: Path,
) -> None:
    """Invalid JSON should identify its physical file line."""
    path = tmp_path / "actions.jsonl"
    store = JsonlAuditStore(path)

    store.append(create_event())
    path.write_text(
        path.read_text(encoding="utf-8") + "{invalid-json}\n",
        encoding="utf-8",
    )

    with pytest.raises(AuditStoreError) as error:
        store.read_all()

    assert error.value.path == path
    assert error.value.line_number == 2
    assert f"{path}:2" in str(error.value)


def test_non_object_json_is_rejected(
    tmp_path: Path,
) -> None:
    """Each physical line must contain one JSON object."""
    path = tmp_path / "actions.jsonl"
    path.write_text('["not", "an", "object"]\n', encoding="utf-8")

    store = JsonlAuditStore(path)

    with pytest.raises(
        AuditStoreError,
        match="must contain a JSON object",
    ) as error:
        store.read_all()

    assert error.value.line_number == 1


def test_blank_line_is_rejected(
    tmp_path: Path,
) -> None:
    """Blank lines should not be silently skipped."""
    path = tmp_path / "actions.jsonl"
    path.write_text("\n", encoding="utf-8")

    store = JsonlAuditStore(path)

    with pytest.raises(
        AuditStoreError,
        match="Blank audit lines",
    ) as error:
        store.read_all()

    assert error.value.line_number == 1


def test_invalid_event_shape_reports_line_number(
    tmp_path: Path,
) -> None:
    """Valid JSON violating the event contract should fail explicitly."""
    path = tmp_path / "actions.jsonl"
    path.write_text(
        '{"schema_version":1}\n',
        encoding="utf-8",
    )

    store = JsonlAuditStore(path)

    with pytest.raises(
        AuditStoreError,
        match="violates the audit-event contract",
    ) as error:
        store.read_all()

    assert error.value.line_number == 1


def test_unterminated_final_line_is_rejected(
    tmp_path: Path,
) -> None:
    """Every stored event must end with exactly one line terminator."""
    path = tmp_path / "actions.jsonl"
    event = create_event()

    path.write_text(
        json.dumps(
            event.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    store = JsonlAuditStore(path)

    with pytest.raises(
        AuditStoreError,
        match="not newline-terminated",
    ) as error:
        store.read_all()

    assert error.value.line_number == 1


def test_optional_fsync_is_called(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Durable mode should explicitly synchronise the appended data."""
    calls: list[int] = []

    def record_fsync(file_descriptor: int) -> None:
        calls.append(file_descriptor)

    monkeypatch.setattr(
        "lea.audit.store.os.fsync",
        record_fsync,
    )

    store = JsonlAuditStore(
        tmp_path / "actions.jsonl",
        fsync=True,
    )

    store.append(create_event())

    assert len(calls) == 1
    assert isinstance(calls[0], int)


def test_default_append_does_not_call_fsync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal append mode should not request filesystem synchronisation."""
    calls = 0

    def record_fsync(file_descriptor: int) -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(
        "lea.audit.store.os.fsync",
        record_fsync,
    )

    store = JsonlAuditStore(tmp_path / "actions.jsonl")

    store.append(create_event())

    assert calls == 0


def test_store_exposes_no_mutation_or_deletion_api(
    tmp_path: Path,
) -> None:
    """The core store should expose no destructive audit operations."""
    store = JsonlAuditStore(tmp_path / "actions.jsonl")

    for method_name in (
        "update",
        "replace",
        "delete",
        "truncate",
        "clear",
    ):
        assert not hasattr(store, method_name)


def test_generated_event_identifiers_remain_valid_after_round_trip(
    tmp_path: Path,
) -> None:
    """Reading should preserve canonical UUID event identifiers."""
    store = JsonlAuditStore(tmp_path / "actions.jsonl")
    event = AuditEvent(
        proposal_id=PROPOSAL_ID_1,
        event_type=AuditEventType.PROPOSAL_CREATED,
        occurred_at=OCCURRED_AT_1,
        payload={},
    )

    store.append(event)
    reconstructed = store.read_all()[0]

    assert UUID(reconstructed.event_id)
    assert reconstructed == event
