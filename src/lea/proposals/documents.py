"""Deterministic Markdown documents for persistent action proposals."""

import json
from collections.abc import Mapping
from typing import cast

from lea.actions import (
    ActionContractError,
    ActionProposal,
    proposal_from_dict,
    proposal_to_dict,
)
from lea.proposals.contracts import (
    ProposalDocumentResult,
    ProposalRepositoryIssue,
)

DOCUMENT_SCHEMA_VERSION = 1

_FRONT_MATTER_FIELDS = (
    "schema_version",
    "proposal_id",
    "action",
    "status",
    "risk_level",
    "confirmation_policy",
    "source",
    "created_at",
)

_FRONT_MATTER_FIELD_SET = frozenset(_FRONT_MATTER_FIELDS)

_TITLE = "# Action Proposal"
_REASON_HEADING = "## Reason"
_PARAMETERS_HEADING = "## Parameters"
_JSON_OPENING = "```json"
_FENCE_CLOSING = "```"
_NO_REASON = "Not provided."
_REASON_METADATA_PREFIX = "<!-- lea-reason-json: "
_REASON_METADATA_SUFFIX = " -->"


def render_proposal_document(
    proposal: ActionProposal,
) -> str:
    """Render one proposal as canonical deterministic Markdown."""
    data = proposal_to_dict(proposal)

    parameters = data["parameters"]
    assert isinstance(parameters, Mapping)

    parameter_json = json.dumps(
        parameters,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    reason_lines = _render_reason_lines(proposal.reason)

    lines = [
        "---",
        f"schema_version: {DOCUMENT_SCHEMA_VERSION}",
        f"proposal_id: {proposal.proposal_id}",
        f"action: {proposal.action}",
        f"status: {proposal.status.value}",
        f"risk_level: {proposal.risk_level.value}",
        (f"confirmation_policy: {proposal.confirmation_policy.value}"),
        f"source: {_render_front_matter_string(proposal.source)}",
        f"created_at: {proposal.created_at.isoformat()}",
        "---",
        "",
        _TITLE,
        "",
        _REASON_HEADING,
        "",
        *reason_lines,
        "",
        _PARAMETERS_HEADING,
        "",
        _JSON_OPENING,
        parameter_json,
        _FENCE_CLOSING,
    ]

    return "\n".join(lines) + "\n"


def parse_proposal_document(
    document: str,
) -> ProposalDocumentResult:
    """Parse one untrusted Markdown proposal document."""
    if not isinstance(document, str):
        raise TypeError("document must be a string.")

    if not document.endswith("\n"):
        return _failure(
            code="proposal_malformed_document",
            message="The proposal document must end with a newline.",
        )

    lines = document.splitlines()

    front_matter_result = _parse_front_matter(lines)

    if isinstance(front_matter_result, ProposalDocumentResult):
        return front_matter_result

    front_matter, body_start = front_matter_result

    body_result = _parse_body(
        lines,
        start_index=body_start,
    )

    if isinstance(body_result, ProposalDocumentResult):
        return body_result

    reason, parameters = body_result

    data: dict[str, object] = {
        "schema_version": front_matter["schema_version"],
        "proposal_id": front_matter["proposal_id"],
        "action": front_matter["action"],
        "parameters": parameters,
        "status": front_matter["status"],
        "risk_level": front_matter["risk_level"],
        "confirmation_policy": front_matter["confirmation_policy"],
        "source": front_matter["source"],
        "created_at": front_matter["created_at"],
        "reason": reason,
    }

    try:
        proposal = proposal_from_dict(data)
    except ActionContractError as error:
        return _failure(
            code="proposal_invalid_contract",
            message=str(error),
        )

    canonical = render_proposal_document(proposal)

    if document != canonical:
        return _failure(
            code="proposal_non_canonical_document",
            message="The proposal document is valid but is not in canonical form.",
            proposal_id=proposal.proposal_id,
        )

    return ProposalDocumentResult(
        success=True,
        proposal=proposal,
        issues=(),
    )


def _parse_front_matter(
    lines: list[str],
) -> tuple[dict[str, object], int] | ProposalDocumentResult:
    """Parse strict deterministic front matter."""
    if not lines or lines[0] != "---":
        return _failure(
            code="proposal_malformed_document",
            message="The proposal document must begin with front matter.",
            line_number=1,
        )

    try:
        closing_index = lines.index("---", 1)
    except ValueError:
        return _failure(
            code="proposal_malformed_document",
            message="The proposal front matter is not closed.",
            line_number=1,
        )

    front_matter_lines = lines[1:closing_index]
    values: dict[str, object] = {}

    for offset, line in enumerate(
        front_matter_lines,
        start=2,
    ):
        if ": " not in line:
            return _failure(
                code="proposal_malformed_document",
                message="Front-matter fields must use 'name: value'.",
                line_number=offset,
            )

        field, value = line.split(": ", 1)

        if field in values:
            return _failure(
                code="proposal_malformed_document",
                message=f"Front-matter field '{field}' is duplicated.",
                line_number=offset,
                field=field,
            )

        if field not in _FRONT_MATTER_FIELD_SET:
            return _failure(
                code="proposal_unknown_field",
                message=f"Unknown front-matter field '{field}' is not permitted.",
                line_number=offset,
                field=field,
            )

        values[field] = _parse_front_matter_value(
            field,
            value,
        )

    missing = [field for field in _FRONT_MATTER_FIELDS if field not in values]

    if missing:
        return _failure(
            code="proposal_missing_field",
            message=f"Required front-matter field '{missing[0]}' is missing.",
            field=missing[0],
        )

    if tuple(values) != _FRONT_MATTER_FIELDS:
        return _failure(
            code="proposal_non_canonical_document",
            message="Proposal front-matter fields are not in canonical order.",
        )

    schema_version = values["schema_version"]

    if schema_version != DOCUMENT_SCHEMA_VERSION:
        return _failure(
            code="proposal_unsupported_schema_version",
            message="The proposal document schema version is unsupported.",
            field="schema_version",
        )

    return values, closing_index + 1


def _parse_front_matter_value(
    field: str,
    value: str,
) -> object:
    """Parse one scalar front-matter value."""
    if field == "schema_version":
        try:
            return int(value)
        except ValueError:
            return value

    if field == "source":
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value

        return parsed

    return value


def _parse_body(
    lines: list[str],
    *,
    start_index: int,
) -> tuple[str | None, Mapping[str, object]] | ProposalDocumentResult:
    """Parse the strict canonical Markdown body."""
    expected_prefix = [
        "",
        _TITLE,
        "",
        _REASON_HEADING,
        "",
    ]

    actual_prefix = lines[start_index : start_index + len(expected_prefix)]

    if actual_prefix != expected_prefix:
        return _failure(
            code="proposal_malformed_document",
            message=(
                "The proposal document body does not use the "
                "required heading structure."
            ),
            line_number=start_index + 1,
        )

    reason_start = start_index + len(expected_prefix)
    suffix_length = 6

    if len(lines) < reason_start + 1 + suffix_length:
        return _failure(
            code="proposal_malformed_document",
            message="The proposal parameters section is malformed.",
        )

    suffix_start = len(lines) - suffix_length
    expected_suffix_prefix = [
        "",
        _PARAMETERS_HEADING,
        "",
        _JSON_OPENING,
    ]

    if lines[suffix_start : suffix_start + 4] != expected_suffix_prefix:
        return _failure(
            code="proposal_malformed_document",
            message="The proposal parameters section is malformed.",
            line_number=suffix_start + 1,
        )

    json_index = suffix_start + 4
    closing_index = suffix_start + 5

    if lines[closing_index] != _FENCE_CLOSING:
        return _failure(
            code="proposal_malformed_document",
            message="The parameters JSON fence is not closed.",
            line_number=closing_index + 1,
        )

    reason_lines = lines[reason_start:suffix_start]

    reason_result = _parse_reason_lines(
        reason_lines,
        line_number=reason_start + 1,
    )

    if isinstance(reason_result, ProposalDocumentResult):
        return reason_result

    try:
        parameters = json.loads(lines[json_index])
    except json.JSONDecodeError:
        return _failure(
            code="proposal_invalid_parameters",
            message="The parameters section does not contain valid JSON.",
            line_number=json_index + 1,
            field="parameters",
        )

    if not isinstance(parameters, Mapping):
        return _failure(
            code="proposal_invalid_parameters",
            message="The parameters JSON value must be an object.",
            line_number=json_index + 1,
            field="parameters",
        )

    return reason_result, cast(Mapping[str, object], parameters)


def _parse_reason_lines(
    lines: list[str],
    *,
    line_number: int,
) -> str | None | ProposalDocumentResult:
    """Parse canonical reason text, including lossless edge cases."""
    if not lines:
        return _failure(
            code="proposal_malformed_document",
            message="The proposal reason is missing.",
            line_number=line_number,
            field="reason",
        )

    first_line = lines[0]

    if first_line.startswith(_REASON_METADATA_PREFIX):
        if not first_line.endswith(_REASON_METADATA_SUFFIX):
            return _failure(
                code="proposal_malformed_document",
                message="The proposal reason metadata is malformed.",
                line_number=line_number,
                field="reason",
            )

        encoded = first_line[
            len(_REASON_METADATA_PREFIX) : -len(_REASON_METADATA_SUFFIX)
        ]

        try:
            reason = json.loads(encoded)
        except json.JSONDecodeError:
            return _failure(
                code="proposal_malformed_document",
                message="The proposal reason metadata is malformed.",
                line_number=line_number,
                field="reason",
            )

        if not isinstance(reason, str):
            return _failure(
                code="proposal_malformed_document",
                message="The proposal reason metadata must contain a string.",
                line_number=line_number,
                field="reason",
            )

        return reason

    if len(lines) != 1:
        return _failure(
            code="proposal_non_canonical_document",
            message=(
                "Multiline proposal reasons must include canonical reason metadata."
            ),
            line_number=line_number,
            field="reason",
        )

    reason = first_line

    if not reason:
        return _failure(
            code="proposal_malformed_document",
            message="The proposal reason must not be blank.",
            line_number=line_number,
            field="reason",
        )

    if reason == _NO_REASON:
        return None

    return reason


def _render_reason_lines(
    reason: str | None,
) -> list[str]:
    """Render reason text while preserving legacy simple documents."""
    if reason is None:
        return [_NO_REASON]

    needs_metadata = (
        "\n" in reason
        or reason == _NO_REASON
        or reason.startswith(_REASON_METADATA_PREFIX)
    )

    if not needs_metadata:
        return [reason]

    encoded = json.dumps(
        reason,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return [
        f"{_REASON_METADATA_PREFIX}{encoded}{_REASON_METADATA_SUFFIX}",
        reason,
    ]


def _render_front_matter_string(
    value: str,
) -> str:
    """Render one unambiguous front-matter string."""
    return json.dumps(
        value,
        ensure_ascii=False,
    )


def _failure(
    *,
    code: str,
    message: str,
    proposal_id: str | None = None,
    line_number: int | None = None,
    field: str | None = None,
) -> ProposalDocumentResult:
    """Construct one deterministic failed document result."""
    return ProposalDocumentResult(
        success=False,
        proposal=None,
        issues=(
            ProposalRepositoryIssue(
                code=code,
                message=message,
                proposal_id=proposal_id,
                line_number=line_number,
                field=field,
            ),
        ),
    )
