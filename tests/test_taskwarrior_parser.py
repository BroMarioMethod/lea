"""Tests for strict Taskwarrior JSON export parsing."""

from datetime import UTC, datetime

import pytest

from lea.adapters.taskwarrior import parse_taskwarrior_export
from lea.tasks import TaskStatus

FIRST_UUID = "11111111-1111-4111-8111-111111111111"
SECOND_UUID = "22222222-2222-4222-8222-222222222222"


def test_empty_export_succeeds() -> None:
    """An empty JSON array should produce an empty task list."""
    result = parse_taskwarrior_export("[]")

    assert result.success is True
    assert result.tasks == ()
    assert result.issues == ()


def test_valid_task_is_parsed() -> None:
    """Known Taskwarrior fields should reconstruct one task."""
    payload = f"""
    [
      {{
        "id": 1,
        "description": "Test task",
        "entry": "20260721T172608Z",
        "modified": "20260721T172700Z",
        "due": "20260722T120000Z",
        "project": "lea",
        "priority": "H",
        "status": "pending",
        "tags": ["beta", "alpha", "beta"],
        "uuid": "{FIRST_UUID}"
      }}
    ]
    """

    result = parse_taskwarrior_export(payload)

    assert result.success is True
    task = result.tasks[0]
    assert task.uuid == FIRST_UUID
    assert task.description == "Test task"
    assert task.status is TaskStatus.PENDING
    assert task.entry == datetime(
        2026,
        7,
        21,
        17,
        26,
        8,
        tzinfo=UTC,
    )
    assert task.modified == datetime(
        2026,
        7,
        21,
        17,
        27,
        tzinfo=UTC,
    )
    assert task.due == datetime(
        2026,
        7,
        22,
        12,
        0,
        tzinfo=UTC,
    )
    assert task.project == "lea"
    assert task.priority == "H"
    assert task.tags == ("alpha", "beta")


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("pending", TaskStatus.PENDING),
        ("completed", TaskStatus.COMPLETED),
        ("deleted", TaskStatus.DELETED),
    ],
)
def test_supported_statuses(
    status: str,
    expected: TaskStatus,
) -> None:
    """Supported Taskwarrior statuses should map explicitly."""
    payload = (
        "[{"
        f'"uuid":"{FIRST_UUID}",'
        '"description":"Test",'
        f'"status":"{status}",'
        '"entry":"20260721T172608Z"'
        "}]"
    )

    result = parse_taskwarrior_export(payload)

    assert result.success is True
    assert result.tasks[0].status is expected


def test_tasks_are_ordered_by_entry_then_uuid() -> None:
    """Parser output should not depend on export insertion order."""
    payload = f"""
    [
      {{
        "uuid": "{SECOND_UUID}",
        "description": "Second",
        "status": "pending",
        "entry": "20260721T172608Z"
      }},
      {{
        "uuid": "{FIRST_UUID}",
        "description": "First",
        "status": "pending",
        "entry": "20260721T172608Z"
      }}
    ]
    """

    result = parse_taskwarrior_export(payload)

    assert result.success is True
    assert tuple(task.uuid for task in result.tasks) == (
        FIRST_UUID,
        SECOND_UUID,
    )


def test_invalid_json_fails() -> None:
    """Malformed JSON should return a structured failure."""
    result = parse_taskwarrior_export("{not json}")

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_export_invalid_json"


@pytest.mark.parametrize(
    "payload",
    [
        "{}",
        '"task"',
        "null",
        "1",
    ],
)
def test_invalid_top_level_shape_fails(
    payload: str,
) -> None:
    """Export payload must be an array."""
    result = parse_taskwarrior_export(payload)

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_export_invalid_shape"


def test_non_object_item_fails() -> None:
    """Every export item must be an object."""
    result = parse_taskwarrior_export("[1]")

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_task_invalid"
    assert result.issues[0].field == "items[0]"


@pytest.mark.parametrize(
    "field",
    [
        "uuid",
        "description",
        "status",
        "entry",
    ],
)
def test_missing_required_field_fails(
    field: str,
) -> None:
    """Required task fields must be present."""
    data = {
        "uuid": FIRST_UUID,
        "description": "Test",
        "status": "pending",
        "entry": "20260721T172608Z",
    }
    del data[field]

    import json

    result = parse_taskwarrior_export(json.dumps([data]))

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_task_invalid"
    assert result.issues[0].field == f"items[0].{field}"


def test_invalid_uuid_fails() -> None:
    """Task UUIDs must satisfy the canonical task contract."""
    payload = (
        "[{"
        '"uuid":"not-a-uuid",'
        '"description":"Test",'
        '"status":"pending",'
        '"entry":"20260721T172608Z"'
        "}]"
    )

    result = parse_taskwarrior_export(payload)

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_task_invalid"
    assert result.issues[0].task_uuid is None
    assert result.issues[0].field == "items[0].uuid"


def test_blank_description_fails() -> None:
    """Task descriptions must not be blank."""
    payload = (
        "[{"
        f'"uuid":"{FIRST_UUID}",'
        '"description":"   ",'
        '"status":"pending",'
        '"entry":"20260721T172608Z"'
        "}]"
    )

    result = parse_taskwarrior_export(payload)

    assert result.success is False
    assert result.issues[0].code == "taskwarrior_task_invalid"


def test_unsupported_status_fails() -> None:
    """Unknown Taskwarrior status values should fail closed."""
    payload = (
        "[{"
        f'"uuid":"{FIRST_UUID}",'
        '"description":"Test",'
        '"status":"waiting",'
        '"entry":"20260721T172608Z"'
        "}]"
    )

    result = parse_taskwarrior_export(payload)

    assert result.success is False
    assert result.issues[0].field == "items[0].status"


def test_invalid_timestamp_fails() -> None:
    """Malformed Taskwarrior timestamps should fail closed."""
    payload = (
        "[{"
        f'"uuid":"{FIRST_UUID}",'
        '"description":"Test",'
        '"status":"pending",'
        '"entry":"2026-07-21T17:26:08Z"'
        "}]"
    )

    result = parse_taskwarrior_export(payload)

    assert result.success is False
    assert result.issues[0].field == "items[0].entry"


def test_invalid_tags_shape_fails() -> None:
    """Tags must be an array of non-empty strings."""
    payload = (
        "[{"
        f'"uuid":"{FIRST_UUID}",'
        '"description":"Test",'
        '"status":"pending",'
        '"entry":"20260721T172608Z",'
        '"tags":"urgent"'
        "}]"
    )

    result = parse_taskwarrior_export(payload)

    assert result.success is False
    assert result.issues[0].field == "items[0].tags"


def test_unknown_fields_are_ignored() -> None:
    """Unknown Taskwarrior fields should not enter LEA contracts."""
    payload = (
        "[{"
        f'"uuid":"{FIRST_UUID}",'
        '"description":"Test",'
        '"status":"pending",'
        '"entry":"20260721T172608Z",'
        '"urgency":12.3,'
        '"custom_field":"ignored"'
        "}]"
    )

    result = parse_taskwarrior_export(payload)

    assert result.success is True
    assert result.tasks[0].description == "Test"


def test_payload_must_be_string() -> None:
    """Programmer misuse should raise rather than become data failure."""
    with pytest.raises(
        TypeError,
        match="payload must be a string",
    ):
        parse_taskwarrior_export(
            b"[]"  # type: ignore[arg-type]
        )
