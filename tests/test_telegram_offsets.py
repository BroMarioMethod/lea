"""Tests for durable Telegram offset persistence."""

from pathlib import Path

import pytest

from lea.adapters.telegram import (
    FileTelegramOffsetStore,
    TelegramOffsetLoadResult,
    TelegramOffsetState,
    TelegramOffsetStore,
    TelegramOffsetStoreResult,
    TelegramUpdate,
)

STATE_TEXT = '{"next_update_id":43,"schema_version":1}\n'


def _store(
    tmp_path: Path,
    *,
    fsync: bool = False,
) -> FileTelegramOffsetStore:
    return FileTelegramOffsetStore(
        (tmp_path / "telegram-offset.json").resolve(),
        fsync=fsync,
    )


def test_missing_state_file_means_no_offset(tmp_path: Path) -> None:
    result = _store(tmp_path).load()

    assert result.success is True
    assert result.state is None
    assert result.issues == ()


def test_advance_persists_next_update_id(tmp_path: Path) -> None:
    store = _store(tmp_path)

    result = store.advance(42)

    assert result.success is True
    assert result.state == TelegramOffsetState(next_update_id=43)
    assert store.path.read_text(encoding="utf-8") == STATE_TEXT
    assert store.path.stat().st_mode & 0o777 == 0o600


def test_store_satisfies_protocol(tmp_path: Path) -> None:
    assert isinstance(_store(tmp_path), TelegramOffsetStore)


def test_loaded_state_detects_stale_updates(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.path.write_text(STATE_TEXT, encoding="utf-8")
    store.path.chmod(0o600)

    result = store.load()

    assert result.state is not None
    assert result.state.is_stale(TelegramUpdate(update_id=42, payload={}))
    assert not result.state.is_stale(TelegramUpdate(update_id=43, payload={}))


def test_equal_checkpoint_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.advance(42)
    before = store.path.read_bytes()
    second = store.advance(42)

    assert first.success is True
    assert second.success is True
    assert second.state == TelegramOffsetState(next_update_id=43)
    assert store.path.read_bytes() == before


def test_offset_cannot_decrease(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.advance(50).success is True

    result = store.advance(42)

    assert result.success is False
    assert result.issues[0].code == "telegram_offset_decrease_rejected"
    assert store.load().state == TelegramOffsetState(next_update_id=51)


@pytest.mark.parametrize("value", [-1, 0, True, 1.5, "1"])
def test_processed_update_id_must_be_positive(
    tmp_path: Path,
    value: object,
) -> None:
    result = _store(tmp_path).advance(value)  # type: ignore[arg-type]

    assert result.success is False
    assert result.issues[0].code == "telegram_processed_update_id_invalid"


@pytest.mark.parametrize(
    ("contents", "code"),
    [
        ("not-json", "telegram_offset_invalid_json"),
        ("[]", "telegram_offset_invalid_shape"),
        (
            '{"schema_version":1}',
            "telegram_offset_fields_invalid",
        ),
        (
            '{"next_update_id":43,"schema_version":2}',
            "telegram_offset_schema_unsupported",
        ),
        (
            '{"next_update_id":-1,"schema_version":1}',
            "telegram_offset_value_invalid",
        ),
        (
            '{"next_update_id":true,"schema_version":1}',
            "telegram_offset_value_invalid",
        ),
    ],
)
def test_invalid_state_fails_closed(
    tmp_path: Path,
    contents: str,
    code: str,
) -> None:
    store = _store(tmp_path)
    store.path.write_text(contents, encoding="utf-8")
    store.path.chmod(0o600)

    result = store.load()

    assert result.success is False
    assert result.issues[0].code == code


def test_invalid_utf8_fails_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.path.write_bytes(b"\xff")
    store.path.chmod(0o600)

    result = store.load()

    assert result.success is False
    assert result.issues[0].code == "telegram_offset_invalid_utf8"


def test_symlink_is_rejected(tmp_path: Path) -> None:
    destination = tmp_path / "real.json"
    destination.write_text(STATE_TEXT, encoding="utf-8")
    destination.chmod(0o600)
    path = tmp_path / "telegram-offset.json"
    path.symlink_to(destination)

    result = FileTelegramOffsetStore(path.resolve(strict=False)).load()

    # resolve(strict=False) follows existing symlinks, so construct the actual
    # absolute symlink path for the security check.
    result = FileTelegramOffsetStore(path.absolute()).load()

    assert result.success is False
    assert result.issues[0].code == "telegram_offset_symlink_rejected"


def test_non_regular_file_is_rejected(tmp_path: Path) -> None:
    path = (tmp_path / "telegram-offset.json").resolve()
    path.mkdir()

    result = FileTelegramOffsetStore(path).load()

    assert result.success is False
    assert result.issues[0].code == "telegram_offset_not_regular_file"


@pytest.mark.parametrize("mode", [0o620, 0o602, 0o666])
def test_insecure_permissions_are_rejected(
    tmp_path: Path,
    mode: int,
) -> None:
    store = _store(tmp_path)
    store.path.write_text(STATE_TEXT, encoding="utf-8")
    store.path.chmod(mode)

    result = store.load()

    assert result.success is False
    assert result.issues[0].code == "telegram_offset_insecure_permissions"


def test_atomic_replace_leaves_no_temporary_files(tmp_path: Path) -> None:
    store = _store(tmp_path)

    result = store.advance(42)

    assert result.success is True
    assert tuple(tmp_path.glob(".telegram-offset.json.*.tmp")) == ()


def test_create_parent_option(tmp_path: Path) -> None:
    path = (tmp_path / "state" / "telegram-offset.json").resolve()
    store = FileTelegramOffsetStore(path, create_parent=True, fsync=False)

    result = store.advance(9)

    assert result.success is True
    assert store.load().state == TelegramOffsetState(next_update_id=10)


def test_missing_parent_fails_deterministically(tmp_path: Path) -> None:
    path = (tmp_path / "missing" / "telegram-offset.json").resolve()
    result = FileTelegramOffsetStore(path, fsync=False).advance(1)

    assert result.success is False
    assert result.issues[0].code == "telegram_offset_parent_missing"


def test_fsyncs_file_and_parent_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def record_fsync(descriptor: int) -> None:
        calls.append(descriptor)

    monkeypatch.setattr("lea.adapters.telegram.offsets.os.fsync", record_fsync)

    result = _store(tmp_path, fsync=True).advance(42)

    assert result.success is True
    assert len(calls) == 2


def test_atomic_replace_failure_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_replace(source: object, destination: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(
        "lea.adapters.telegram.offsets.os.replace",
        fail_replace,
    )

    result = _store(tmp_path).advance(42)

    assert result.success is False
    assert result.issues[0].code == "telegram_offset_atomic_write_failed"
    assert tuple(tmp_path.glob(".telegram-offset.json.*.tmp")) == ()


def test_result_contracts_enforce_consistency() -> None:
    with pytest.raises(ValueError, match="must contain state"):
        TelegramOffsetStoreResult(
            success=True,
            state=None,
            issues=(),
        )

    with pytest.raises(ValueError, match="at least one issue"):
        TelegramOffsetLoadResult(
            success=False,
            state=None,
            issues=(),
        )
