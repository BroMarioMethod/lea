"""Append-only JSON Lines persistence for LEA audit events."""

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import cast
from uuid import UUID

from lea.actions.errors import ActionContractError
from lea.audit.errors import AuditStoreError
from lea.audit.events import AuditEvent, AuditSubjectType


class JsonlAuditStore:
    """Append-only JSONL storage for immutable audit events."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        create_parents: bool = False,
        fsync: bool = False,
    ) -> None:
        """Initialise an audit store using an explicitly supplied path."""
        self._path = Path(path)
        self._create_parents = create_parents
        self._fsync = fsync

    @property
    def path(self) -> Path:
        """Return the configured audit-file path."""
        return self._path

    def append(self, event: AuditEvent) -> None:
        """Append one complete deterministic JSON event line."""
        line = self._serialise_event(event)

        try:
            if self._create_parents:
                self._path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

            with self._path.open(
                "a",
                encoding="utf-8",
                newline="\n",
            ) as audit_file:
                audit_file.write(line)
                audit_file.write("\n")
                audit_file.flush()

                if self._fsync:
                    os.fsync(audit_file.fileno())
        except OSError as error:
            raise AuditStoreError(
                "Could not append the audit event.",
                path=self._path,
            ) from error

    def read_all(self) -> tuple[AuditEvent, ...]:
        """Read every audit event in physical file order."""
        if not self._path.exists():
            return ()

        events: list[AuditEvent] = []

        try:
            with self._path.open(
                "r",
                encoding="utf-8",
                newline="",
            ) as audit_file:
                for line_number, line in enumerate(
                    audit_file,
                    start=1,
                ):
                    events.append(
                        self._parse_line(
                            line,
                            line_number=line_number,
                        )
                    )
        except AuditStoreError:
            raise
        except (OSError, UnicodeError) as error:
            raise AuditStoreError(
                "Could not read the audit file.",
                path=self._path,
            ) from error

        return tuple(events)

    def read_for_proposal(
        self,
        proposal_id: str,
    ) -> tuple[AuditEvent, ...]:
        """Read events matching one exact canonical proposal identifier."""
        _validate_proposal_id(proposal_id)

        return tuple(
            event for event in self.read_all() if event.proposal_id == proposal_id
        )

    def read_for_subject(
        self,
        subject_type: AuditSubjectType,
        subject_id: str,
    ) -> tuple[AuditEvent, ...]:
        """Read events matching one exact generic audit subject."""
        _validate_subject_id(subject_id)
        return tuple(
            event
            for event in self.read_all()
            if event.subject_type is subject_type and event.subject_id == subject_id
        )

    def _serialise_event(
        self,
        event: AuditEvent,
    ) -> str:
        """Serialise an event completely before opening the audit file."""
        try:
            return json.dumps(
                event.to_dict(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError) as error:
            raise AuditStoreError(
                "Could not serialise the audit event.",
                path=self._path,
            ) from error

    def _parse_line(
        self,
        line: str,
        *,
        line_number: int,
    ) -> AuditEvent:
        """Parse and validate one physical audit-file line."""
        if not line.endswith("\n"):
            raise AuditStoreError(
                "Audit event line is not newline-terminated.",
                path=self._path,
                line_number=line_number,
            )

        if not line.strip():
            raise AuditStoreError(
                "Blank audit lines are not permitted.",
                path=self._path,
                line_number=line_number,
            )

        try:
            data = json.loads(line)
        except json.JSONDecodeError as error:
            raise AuditStoreError(
                "Audit line does not contain valid JSON.",
                path=self._path,
                line_number=line_number,
            ) from error

        if not isinstance(data, Mapping):
            raise AuditStoreError(
                "Audit line must contain a JSON object.",
                path=self._path,
                line_number=line_number,
            )

        try:
            return AuditEvent.from_dict(cast(Mapping[str, object], data))
        except ActionContractError as error:
            raise AuditStoreError(
                "Audit line violates the audit-event contract.",
                path=self._path,
                line_number=line_number,
            ) from error


def _validate_proposal_id(proposal_id: str) -> None:
    """Validate a canonical lower-case proposal UUID."""
    try:
        parsed_identifier = UUID(proposal_id)
    except (TypeError, ValueError) as error:
        raise ActionContractError("proposal_id must be a valid UUID.") from error

    if str(parsed_identifier) != proposal_id:
        raise ActionContractError(
            "proposal_id must use canonical lower-case UUID format."
        )


def _validate_subject_id(subject_id: str) -> None:
    """Validate one canonical generic audit subject UUID."""
    try:
        parsed_identifier = UUID(subject_id)
    except (TypeError, ValueError) as error:
        raise ActionContractError("subject_id must be a valid UUID.") from error
    if str(parsed_identifier) != subject_id:
        raise ActionContractError(
            "subject_id must use canonical lower-case UUID format."
        )
