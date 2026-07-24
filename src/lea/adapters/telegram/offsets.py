"""Durable Telegram update-offset persistence."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast, runtime_checkable

from lea.adapters.telegram.contracts import TelegramUpdate

TELEGRAM_OFFSET_SCHEMA_VERSION = 1
_STATE_FIELDS = frozenset({"schema_version", "next_update_id"})


@dataclass(frozen=True, slots=True)
class TelegramOffsetIssue:
    """One deterministic Telegram offset-state problem."""

    code: str
    message: str
    field: str | None = None
    source_path: Path | None = None

    def __post_init__(self) -> None:
        """Validate safe issue fields."""
        if not self.code.strip():
            raise ValueError("Telegram offset issue code must be non-empty.")

        if not self.message.strip():
            raise ValueError("Telegram offset issue message must be non-empty.")

        if self.field is not None and not self.field.strip():
            raise ValueError(
                "Telegram offset issue field must be non-empty when provided."
            )

        if self.source_path is not None and not self.source_path.is_absolute():
            raise ValueError("Telegram offset issue source_path must be absolute.")


@dataclass(frozen=True, slots=True)
class TelegramOffsetState:
    """One validated next-update checkpoint."""

    next_update_id: int
    schema_version: int = TELEGRAM_OFFSET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Validate one canonical Telegram offset state."""
        if self.schema_version != TELEGRAM_OFFSET_SCHEMA_VERSION:
            raise ValueError("Unsupported Telegram offset schema version.")

        _validate_non_negative_integer(
            self.next_update_id,
            field_name="next_update_id",
        )

    def is_stale(self, update: TelegramUpdate) -> bool:
        """Return whether an update predates this checkpoint."""
        return update.update_id < self.next_update_id


@dataclass(frozen=True, slots=True)
class TelegramOffsetLoadResult:
    """Immutable result of loading Telegram offset state."""

    success: bool
    state: TelegramOffsetState | None
    issues: tuple[TelegramOffsetIssue, ...]

    def __post_init__(self) -> None:
        """Enforce load-result consistency."""
        if self.success:
            if self.issues:
                raise ValueError(
                    "A successful Telegram offset load must not contain issues."
                )
            return

        if self.state is not None:
            raise ValueError("A failed Telegram offset load must not contain state.")

        if not self.issues:
            raise ValueError(
                "A failed Telegram offset load must contain at least one issue."
            )


@dataclass(frozen=True, slots=True)
class TelegramOffsetStoreResult:
    """Immutable result of storing Telegram offset state."""

    success: bool
    state: TelegramOffsetState | None
    issues: tuple[TelegramOffsetIssue, ...]

    def __post_init__(self) -> None:
        """Enforce store-result consistency."""
        if self.success:
            if self.state is None:
                raise ValueError(
                    "A successful Telegram offset store must contain state."
                )

            if self.issues:
                raise ValueError(
                    "A successful Telegram offset store must not contain issues."
                )
            return

        if self.state is not None:
            raise ValueError("A failed Telegram offset store must not contain state.")

        if not self.issues:
            raise ValueError(
                "A failed Telegram offset store must contain at least one issue."
            )


@runtime_checkable
class TelegramOffsetStore(Protocol):
    """Persistence boundary for Telegram update checkpoints."""

    def load(self) -> TelegramOffsetLoadResult:
        """Load the current next-update checkpoint."""
        ...

    def advance(self, processed_update_id: int) -> TelegramOffsetStoreResult:
        """Persist processed_update_id plus one without decreasing state."""
        ...


class FileTelegramOffsetStore(TelegramOffsetStore):
    """Strict atomic file-backed Telegram offset store."""

    def __init__(
        self,
        path: Path,
        *,
        create_parent: bool = False,
        fsync: bool = True,
    ) -> None:
        """Configure one explicit absolute state-file path."""
        if not path.is_absolute():
            raise ValueError("Telegram offset path must be absolute.")

        self._path = path
        self._create_parent = create_parent
        self._fsync = fsync

    @property
    def path(self) -> Path:
        """Return the configured state-file path."""
        return self._path

    def load(self) -> TelegramOffsetLoadResult:
        """Load strict UTF-8 JSON offset state."""
        if self._path.is_symlink():
            return self._load_failure(
                code="telegram_offset_symlink_rejected",
                message="Symbolic links are not permitted for Telegram offset state.",
            )

        try:
            metadata = self._path.stat()
        except FileNotFoundError:
            return TelegramOffsetLoadResult(
                success=True,
                state=None,
                issues=(),
            )
        except OSError:
            return self._load_failure(
                code="telegram_offset_stat_failed",
                message="Telegram offset state metadata could not be read.",
            )

        if not self._path.is_file():
            return self._load_failure(
                code="telegram_offset_not_regular_file",
                message="Telegram offset state path is not a regular file.",
            )

        if metadata.st_mode & 0o022:
            return self._load_failure(
                code="telegram_offset_insecure_permissions",
                message=(
                    "Telegram offset state must not be writable by the group "
                    "or other users."
                ),
            )

        try:
            contents = self._path.read_text(encoding="utf-8")
        except UnicodeError:
            return self._load_failure(
                code="telegram_offset_invalid_utf8",
                message="Telegram offset state is not valid UTF-8.",
            )
        except OSError:
            return self._load_failure(
                code="telegram_offset_read_failed",
                message="Telegram offset state could not be read.",
            )

        return _parse_state(contents, source_path=self._path)

    def advance(self, processed_update_id: int) -> TelegramOffsetStoreResult:
        """Atomically persist processed_update_id plus one."""
        try:
            _validate_positive_integer(
                processed_update_id,
                field_name="processed_update_id",
            )
        except (TypeError, ValueError):
            return self._store_failure(
                code="telegram_processed_update_id_invalid",
                message="processed_update_id must be a positive integer.",
                field="processed_update_id",
            )

        loaded = self.load()

        if not loaded.success:
            return TelegramOffsetStoreResult(
                success=False,
                state=None,
                issues=loaded.issues,
            )

        candidate = processed_update_id + 1
        current = loaded.state.next_update_id if loaded.state is not None else None

        if current is not None and candidate < current:
            return self._store_failure(
                code="telegram_offset_decrease_rejected",
                message="Telegram offset state must not decrease.",
                field="next_update_id",
            )

        state = TelegramOffsetState(
            next_update_id=current if current == candidate else candidate
        )

        if current == candidate:
            return TelegramOffsetStoreResult(
                success=True,
                state=state,
                issues=(),
            )

        return self._write_state(state)

    def _write_state(
        self,
        state: TelegramOffsetState,
    ) -> TelegramOffsetStoreResult:
        parent = self._path.parent

        try:
            if self._create_parent:
                parent.mkdir(parents=True, exist_ok=True)

            if not parent.is_dir():
                return self._store_failure(
                    code="telegram_offset_parent_missing",
                    message="Telegram offset state parent directory is unavailable.",
                )

            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                dir=parent,
                text=True,
            )
            temporary_path = Path(temporary_name)

            try:
                with os.fdopen(
                    descriptor,
                    "w",
                    encoding="utf-8",
                    newline="\n",
                ) as stream:
                    stream.write(_serialise_state(state))
                    stream.flush()

                    if self._fsync:
                        os.fsync(stream.fileno())

                os.chmod(temporary_path, 0o600)
                os.replace(temporary_path, self._path)

                if self._fsync:
                    _fsync_directory(parent)
            except BaseException:
                temporary_path.unlink(missing_ok=True)
                raise
        except OSError:
            return self._store_failure(
                code="telegram_offset_atomic_write_failed",
                message="Telegram offset state could not be stored atomically.",
            )

        return TelegramOffsetStoreResult(
            success=True,
            state=state,
            issues=(),
        )

    def _load_failure(
        self,
        *,
        code: str,
        message: str,
        field: str | None = None,
    ) -> TelegramOffsetLoadResult:
        return TelegramOffsetLoadResult(
            success=False,
            state=None,
            issues=(
                TelegramOffsetIssue(
                    code=code,
                    message=message,
                    field=field,
                    source_path=self._path,
                ),
            ),
        )

    def _store_failure(
        self,
        *,
        code: str,
        message: str,
        field: str | None = None,
    ) -> TelegramOffsetStoreResult:
        return TelegramOffsetStoreResult(
            success=False,
            state=None,
            issues=(
                TelegramOffsetIssue(
                    code=code,
                    message=message,
                    field=field,
                    source_path=self._path,
                ),
            ),
        )


def _parse_state(
    contents: str,
    *,
    source_path: Path,
) -> TelegramOffsetLoadResult:
    try:
        raw = json.loads(contents)
    except json.JSONDecodeError:
        return _parse_failure(
            source_path,
            code="telegram_offset_invalid_json",
            message="Telegram offset state does not contain valid JSON.",
        )

    if not isinstance(raw, Mapping):
        return _parse_failure(
            source_path,
            code="telegram_offset_invalid_shape",
            message="Telegram offset state must contain a JSON object.",
        )

    data = cast(Mapping[str, object], raw)

    if set(data) != _STATE_FIELDS:
        return _parse_failure(
            source_path,
            code="telegram_offset_fields_invalid",
            message="Telegram offset state contains missing or unknown fields.",
        )

    schema_version = data.get("schema_version")
    next_update_id = data.get("next_update_id")

    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != TELEGRAM_OFFSET_SCHEMA_VERSION
    ):
        return _parse_failure(
            source_path,
            code="telegram_offset_schema_unsupported",
            message="Telegram offset state uses an unsupported schema version.",
            field="schema_version",
        )

    try:
        _validate_non_negative_integer(
            next_update_id,
            field_name="next_update_id",
        )
    except (TypeError, ValueError):
        return _parse_failure(
            source_path,
            code="telegram_offset_value_invalid",
            message="next_update_id must be a non-negative integer.",
            field="next_update_id",
        )

    assert isinstance(next_update_id, int)
    return TelegramOffsetLoadResult(
        success=True,
        state=TelegramOffsetState(next_update_id=next_update_id),
        issues=(),
    )


def _serialise_state(state: TelegramOffsetState) -> str:
    return (
        json.dumps(
            {
                "next_update_id": state.next_update_id,
                "schema_version": state.schema_version,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


def _parse_failure(
    source_path: Path,
    *,
    code: str,
    message: str,
    field: str | None = None,
) -> TelegramOffsetLoadResult:
    return TelegramOffsetLoadResult(
        success=False,
        state=None,
        issues=(
            TelegramOffsetIssue(
                code=code,
                message=message,
                field=field,
                source_path=source_path,
            ),
        ),
    )


def _validate_non_negative_integer(
    value: object,
    *,
    field_name: str,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer.")

    if value < 0:
        raise ValueError(f"{field_name} must not be negative.")


def _validate_positive_integer(
    value: object,
    *,
    field_name: str,
) -> None:
    _validate_non_negative_integer(value, field_name=field_name)

    if cast(int, value) < 1:
        raise ValueError(f"{field_name} must be greater than zero.")


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)

    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
