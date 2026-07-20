"""Tests for integrity-enabled LEA JSONL audit storage."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lea.audit import (
    AuditEvent,
    AuditEventType,
    AuditStoreError,
    IntegrityJsonlAuditStore,
    JsonlAuditStore,
    create_integrity_envelope,
)

EVENT_ID_1 = "11111111-1111-4111-8111-111111111111"
EVENT_ID_2 = "22222222-2222-4222-8222-222222222222"
EVENT_ID_3 = "33333333-3333-4333-8333-333333333333"

PROPOSAL_ID = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"

OCCURRED_AT_1 = datetime(2026, 7, 20, 18, 0, tzinfo=UTC)
OCCURRED_AT_2 = datetime(2026, 7, 20, 18, 5, tzinfo=UTC)
OCCURRED_AT_3 = datetime(2026, 7, 20, 18, 10, tzinfo=UTC)


def create_event(
    *,
    event_id: str = EVENT_ID_1,
    occurred_at: datetime = OCCURRED_AT_1,
    message: str = "First event",
) -> AuditEvent:
    """Create one deterministic audit event."""
    return AuditEvent(
        event_id=event_id,
        proposal_id=PROPOSAL_ID,
        event_type=AuditEventType.PROPOSAL_CREATED,
        occurred_at=occurred_at,
        payload={
            "message": message,
            "amount": "£10",
        },
    )


def test_missing_integrity_store_is_empty(
    tmp_path: Path,
) -> None:
    """A missing file should represent an empty valid chain."""
    store = IntegrityJsonlAuditStore(tmp_path / "missing.jsonl")

    assert store.read_all() == ()

    verification = store.verify()

    assert verification.valid is True
    assert verification.checked_events == 0
    assert verification.final_event_hash is None


def test_append_creates_genesis_envelope(
    tmp_path: Path,
) -> None:
    """The first append should create a genesis envelope."""
    store = IntegrityJsonlAuditStore(tmp_path / "actions.jsonl")
    event = create_event()

    envelope = store.append(event)

    assert envelope.event == event
    assert envelope.previous_event_hash is None
    assert store.read_all() == (envelope,)
    assert store.verify().valid is True


def test_second_append_links_to_first_hash(
    tmp_path: Path,
) -> None:
    """Subsequent events should link to the preceding hash."""
    store = IntegrityJsonlAuditStore(tmp_path / "actions.jsonl")

    first = store.append(create_event())
    second = store.append(
        create_event(
            event_id=EVENT_ID_2,
            occurred_at=OCCURRED_AT_2,
            message="Second event",
        )
    )

    assert second.previous_event_hash == first.event_hash
    assert store.read_all() == (first, second)
    assert store.verify().valid is True


def test_append_writes_compact_deterministic_json(
    tmp_path: Path,
) -> None:
    """Each envelope should occupy one deterministic JSON line."""
    path = tmp_path / "actions.jsonl"
    store = IntegrityJsonlAuditStore(path)

    envelope = store.append(create_event())

    expected = json.dumps(
        envelope.to_dict(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    assert path.read_text(encoding="utf-8") == f"{expected}\n"


def test_append_uses_utf8_without_ascii_escaping(
    tmp_path: Path,
) -> None:
    """Unicode event data should remain direct UTF-8."""
    path = tmp_path / "actions.jsonl"
    store = IntegrityJsonlAuditStore(path)

    store.append(create_event())

    contents = path.read_text(encoding="utf-8")

    assert "£10" in contents
    assert "\\u00a3" not in contents


def test_parent_creation_is_explicit(
    tmp_path: Path,
) -> None:
    """Missing parent directories should require permission."""
    path = tmp_path / "runtime" / "audit" / "actions.jsonl"

    disabled = IntegrityJsonlAuditStore(path)

    with pytest.raises(
        AuditStoreError,
        match="Could not append",
    ):
        disabled.append(create_event())

    enabled = IntegrityJsonlAuditStore(
        path,
        create_parents=True,
    )

    enabled.append(create_event())

    assert path.is_file()


def test_optional_fsync_is_called(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Durable mode should explicitly request synchronisation."""
    calls: list[int] = []

    def record_fsync(file_descriptor: int) -> None:
        calls.append(file_descriptor)

    monkeypatch.setattr(
        "lea.audit.integrity_store.os.fsync",
        record_fsync,
    )

    store = IntegrityJsonlAuditStore(
        tmp_path / "actions.jsonl",
        fsync=True,
    )

    store.append(create_event())

    assert len(calls) == 1


def test_plain_legacy_file_is_detected(
    tmp_path: Path,
) -> None:
    """A Milestone 1.5 file should not be reported as verified."""
    path = tmp_path / "legacy.jsonl"
    legacy_store = JsonlAuditStore(path)
    legacy_store.append(create_event())

    store = IntegrityJsonlAuditStore(path)
    verification = store.verify()

    assert verification.valid is False
    assert verification.issues[0].code == "integrity_not_present"
    assert verification.issues[0].line_number == 1


def test_plain_legacy_file_cannot_be_read_as_envelopes(
    tmp_path: Path,
) -> None:
    """Legacy events should not be silently upgraded."""
    path = tmp_path / "legacy.jsonl"
    JsonlAuditStore(path).append(create_event())

    store = IntegrityJsonlAuditStore(path)

    with pytest.raises(
        AuditStoreError,
        match="does not contain integrity metadata",
    ):
        store.read_all()


def test_plain_legacy_file_cannot_be_extended(
    tmp_path: Path,
) -> None:
    """Appending must not silently convert a legacy file."""
    path = tmp_path / "legacy.jsonl"
    JsonlAuditStore(path).append(create_event())

    original = path.read_bytes()
    store = IntegrityJsonlAuditStore(path)

    with pytest.raises(
        AuditStoreError,
        match="does not contain integrity metadata",
    ):
        store.append(
            create_event(
                event_id=EVENT_ID_2,
                occurred_at=OCCURRED_AT_2,
            )
        )

    assert path.read_bytes() == original


def test_mixed_format_is_rejected(
    tmp_path: Path,
) -> None:
    """Plain events and integrity envelopes must not coexist."""
    path = tmp_path / "mixed.jsonl"
    event = create_event()
    envelope = create_integrity_envelope(
        create_event(
            event_id=EVENT_ID_2,
            occurred_at=OCCURRED_AT_2,
        ),
        previous_event_hash=None,
    )

    path.write_text(
        (
            json.dumps(
                event.to_dict(),
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
            + json.dumps(
                envelope.to_dict(),
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ),
        encoding="utf-8",
    )

    store = IntegrityJsonlAuditStore(path)
    verification = store.verify()

    assert verification.valid is False
    assert verification.issues[0].code == "mixed_audit_format"
    assert verification.issues[0].line_number == 2


def test_invalid_chain_cannot_be_extended(
    tmp_path: Path,
) -> None:
    """The store should refuse to append after detected tampering."""
    path = tmp_path / "actions.jsonl"
    store = IntegrityJsonlAuditStore(path)

    first = store.append(create_event())
    second = store.append(
        create_event(
            event_id=EVENT_ID_2,
            occurred_at=OCCURRED_AT_2,
            message="Second event",
        )
    )

    data = second.to_dict()
    event_data = data["event"]
    assert isinstance(event_data, dict)

    payload = event_data["payload"]
    assert isinstance(payload, dict)
    payload["message"] = "Tampered event"

    path.write_text(
        (
            json.dumps(
                first.to_dict(),
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
            + json.dumps(
                data,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ),
        encoding="utf-8",
    )

    original = path.read_bytes()

    with pytest.raises(
        AuditStoreError,
        match="existing audit integrity chain is invalid",
    ):
        store.append(
            create_event(
                event_id=EVENT_ID_3,
                occurred_at=OCCURRED_AT_3,
                message="Third event",
            )
        )

    assert path.read_bytes() == original


def test_read_all_preserves_physical_order(
    tmp_path: Path,
) -> None:
    """Reading should retain append order."""
    store = IntegrityJsonlAuditStore(tmp_path / "actions.jsonl")

    first = store.append(
        create_event(
            event_id=EVENT_ID_1,
            occurred_at=OCCURRED_AT_3,
            message="Later timestamp first",
        )
    )
    second = store.append(
        create_event(
            event_id=EVENT_ID_2,
            occurred_at=OCCURRED_AT_1,
            message="Earlier timestamp second",
        )
    )

    assert store.read_all() == (
        first,
        second,
    )


def test_malformed_json_reports_line_number(
    tmp_path: Path,
) -> None:
    """Malformed JSON should expose its physical line number."""
    path = tmp_path / "actions.jsonl"
    path.write_text("{invalid-json}\n", encoding="utf-8")

    store = IntegrityJsonlAuditStore(path)

    with pytest.raises(AuditStoreError) as error:
        store.verify()

    assert error.value.line_number == 1


def test_blank_line_is_rejected(
    tmp_path: Path,
) -> None:
    """Blank lines should not be silently skipped."""
    path = tmp_path / "actions.jsonl"
    path.write_text("\n", encoding="utf-8")

    store = IntegrityJsonlAuditStore(path)

    with pytest.raises(
        AuditStoreError,
        match="Blank audit integrity lines",
    ) as error:
        store.verify()

    assert error.value.line_number == 1


def test_unterminated_final_line_is_rejected(
    tmp_path: Path,
) -> None:
    """Every integrity record must end with a newline."""
    path = tmp_path / "actions.jsonl"
    envelope = create_integrity_envelope(
        create_event(),
        previous_event_hash=None,
    )

    path.write_text(
        json.dumps(
            envelope.to_dict(),
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    store = IntegrityJsonlAuditStore(path)

    with pytest.raises(
        AuditStoreError,
        match="not newline-terminated",
    ) as error:
        store.verify()

    assert error.value.line_number == 1


def test_non_object_json_is_rejected(
    tmp_path: Path,
) -> None:
    """Every physical line must contain one JSON object."""
    path = tmp_path / "actions.jsonl"
    path.write_text('["invalid"]\n', encoding="utf-8")

    store = IntegrityJsonlAuditStore(path)

    with pytest.raises(
        AuditStoreError,
        match="must contain a JSON object",
    ):
        store.verify()


def test_store_exposes_no_destructive_or_repair_api(
    tmp_path: Path,
) -> None:
    """The integrity store should remain append-only."""
    store = IntegrityJsonlAuditStore(tmp_path / "actions.jsonl")

    for method_name in (
        "update",
        "replace",
        "delete",
        "truncate",
        "clear",
        "repair",
    ):
        assert not hasattr(store, method_name)
