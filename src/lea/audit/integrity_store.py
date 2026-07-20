"""Integrity-enabled JSON Lines persistence for LEA audit events."""

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, cast

from lea.actions.errors import ActionContractError
from lea.audit.errors import AuditStoreError
from lea.audit.events import (
    AUDIT_EVENT_FIELDS,
    AuditEvent,
)
from lea.audit.integrity import (
    INTEGRITY_ENVELOPE_FIELDS,
    AuditIntegrityIssue,
    AuditIntegrityVerificationResult,
    IntegrityEnvelope,
    create_integrity_envelope,
)
from lea.audit.verification import verify_integrity_chain

AuditFileFormat = Literal[
    "empty",
    "integrity",
    "legacy",
    "mixed",
]


class IntegrityJsonlAuditStore:
    """Single-writer JSONL storage for hash-chained audit events."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        create_parents: bool = False,
        fsync: bool = False,
    ) -> None:
        """Initialise the store with an explicitly supplied runtime path."""
        self._path = Path(path)
        self._create_parents = create_parents
        self._fsync = fsync

    @property
    def path(self) -> Path:
        """Return the configured integrity-file path."""
        return self._path

    def append(
        self,
        event: AuditEvent,
    ) -> IntegrityEnvelope:
        """Verify the existing chain and append one linked envelope."""
        file_format, envelopes, mixed_line = self._inspect_file()

        if file_format == "legacy":
            raise AuditStoreError(
                "Legacy audit data does not contain integrity metadata.",
                path=self._path,
                line_number=1,
            )

        if file_format == "mixed":
            raise AuditStoreError(
                "Mixed plain and integrity audit formats are unsupported.",
                path=self._path,
                line_number=mixed_line,
            )

        verification = verify_integrity_chain(envelopes)

        if not verification.valid:
            issue = verification.issues[0]

            raise AuditStoreError(
                (f"The existing audit integrity chain is invalid: {issue.code}."),
                path=self._path,
                line_number=issue.line_number,
            )

        previous_event_hash = envelopes[-1].event_hash if envelopes else None

        envelope = create_integrity_envelope(
            event,
            previous_event_hash=previous_event_hash,
        )
        line = self._serialise_envelope(envelope)

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
                "Could not append the integrity envelope.",
                path=self._path,
            ) from error

        return envelope

    def read_all(
        self,
    ) -> tuple[IntegrityEnvelope, ...]:
        """Read integrity envelopes in physical file order."""
        file_format, envelopes, mixed_line = self._inspect_file()

        if file_format == "legacy":
            raise AuditStoreError(
                "Legacy audit data does not contain integrity metadata.",
                path=self._path,
                line_number=1,
            )

        if file_format == "mixed":
            raise AuditStoreError(
                "Mixed plain and integrity audit formats are unsupported.",
                path=self._path,
                line_number=mixed_line,
            )

        return envelopes

    def verify(
        self,
    ) -> AuditIntegrityVerificationResult:
        """Verify the configured file without mutating it."""
        file_format, envelopes, mixed_line = self._inspect_file()

        if file_format == "legacy":
            return _invalid_verification_result(
                code="integrity_not_present",
                message=(
                    "The audit file uses the legacy plain JSONL format "
                    "and contains no integrity metadata."
                ),
                line_number=1,
            )

        if file_format == "mixed":
            return _invalid_verification_result(
                code="mixed_audit_format",
                message=(
                    "The audit file contains both plain audit events "
                    "and integrity envelopes."
                ),
                line_number=mixed_line,
            )

        return verify_integrity_chain(envelopes)

    def _inspect_file(
        self,
    ) -> tuple[
        AuditFileFormat,
        tuple[IntegrityEnvelope, ...],
        int | None,
    ]:
        """Inspect and validate the physical audit-file format."""
        if not self._path.exists():
            return "empty", (), None

        envelopes: list[IntegrityEnvelope] = []
        detected_format: AuditFileFormat = "empty"

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
                    data = self._parse_json_object(
                        line,
                        line_number=line_number,
                    )
                    record_format = _classify_record(data)

                    if record_format == "unknown":
                        raise AuditStoreError(
                            "Audit line has no recognised audit format.",
                            path=self._path,
                            line_number=line_number,
                        )

                    if detected_format == "empty":
                        detected_format = record_format
                    elif detected_format != record_format:
                        return (
                            "mixed",
                            tuple(envelopes),
                            line_number,
                        )

                    if record_format == "integrity":
                        envelopes.append(
                            self._parse_integrity_envelope(
                                data,
                                line_number=line_number,
                            )
                        )
                    else:
                        self._validate_legacy_event(
                            data,
                            line_number=line_number,
                        )
        except AuditStoreError:
            raise
        except (OSError, UnicodeError) as error:
            raise AuditStoreError(
                "Could not read the audit integrity file.",
                path=self._path,
            ) from error

        return detected_format, tuple(envelopes), None

    def _parse_json_object(
        self,
        line: str,
        *,
        line_number: int,
    ) -> Mapping[str, object]:
        """Parse one newline-terminated JSON object."""
        if not line.endswith("\n"):
            raise AuditStoreError(
                "Audit integrity line is not newline-terminated.",
                path=self._path,
                line_number=line_number,
            )

        if not line.strip():
            raise AuditStoreError(
                "Blank audit integrity lines are not permitted.",
                path=self._path,
                line_number=line_number,
            )

        try:
            data = json.loads(line)
        except json.JSONDecodeError as error:
            raise AuditStoreError(
                "Audit integrity line does not contain valid JSON.",
                path=self._path,
                line_number=line_number,
            ) from error

        if not isinstance(data, Mapping):
            raise AuditStoreError(
                "Audit integrity line must contain a JSON object.",
                path=self._path,
                line_number=line_number,
            )

        return cast(Mapping[str, object], data)

    def _parse_integrity_envelope(
        self,
        data: Mapping[str, object],
        *,
        line_number: int,
    ) -> IntegrityEnvelope:
        """Reconstruct one validated integrity envelope."""
        try:
            return IntegrityEnvelope.from_dict(data)
        except ActionContractError as error:
            raise AuditStoreError(
                "Audit line violates the integrity-envelope contract.",
                path=self._path,
                line_number=line_number,
            ) from error

    def _validate_legacy_event(
        self,
        data: Mapping[str, object],
        *,
        line_number: int,
    ) -> None:
        """Validate a recognised legacy event without upgrading it."""
        try:
            AuditEvent.from_dict(data)
        except ActionContractError as error:
            raise AuditStoreError(
                "Legacy audit line violates the audit-event contract.",
                path=self._path,
                line_number=line_number,
            ) from error

    def _serialise_envelope(
        self,
        envelope: IntegrityEnvelope,
    ) -> str:
        """Serialise an envelope before opening the output file."""
        try:
            return json.dumps(
                envelope.to_dict(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError) as error:
            raise AuditStoreError(
                "Could not serialise the integrity envelope.",
                path=self._path,
            ) from error


def _classify_record(
    data: Mapping[str, object],
) -> Literal[
    "integrity",
    "legacy",
    "unknown",
]:
    """Classify one JSON object by its recognised contract fields."""
    supplied_fields = set(data)

    integrity_markers = supplied_fields & INTEGRITY_ENVELOPE_FIELDS
    legacy_markers = supplied_fields & AUDIT_EVENT_FIELDS

    if integrity_markers and not legacy_markers:
        return "integrity"

    if legacy_markers and not integrity_markers:
        return "legacy"

    return "unknown"


def _invalid_verification_result(
    *,
    code: str,
    message: str,
    line_number: int | None,
) -> AuditIntegrityVerificationResult:
    """Construct one deterministic failed verification result."""
    return AuditIntegrityVerificationResult(
        valid=False,
        checked_events=0,
        last_valid_line=None,
        final_event_hash=None,
        issues=(
            AuditIntegrityIssue(
                code=code,
                message=message,
                line_number=line_number,
            ),
        ),
    )
