---
title: Action Proposal Contract Specification
document_id: LEA-SPEC-0002
version: 0.1.3
status: Accepted
authors:
  - Marius du Preez
  - OpenAI ChatGPT
license: AGPL-3.0-only
created: 2026-07-18
last_updated: 2026-07-18
review_required: false
---

# Action Proposal Contract Specification

## Document Status

| Item | Value |
|---|---|
| Status | Accepted |
| Requires Review | No |
| Implementation | Complete |
| Test Status | Automated Tests Passing |

---

## 1. Purpose

This specification defines the deterministic contract used to represent proposed actions in LEA.

An action proposal describes a requested operation and its parameters. It does not grant permission to execute that operation.

The contract SHALL provide typed, serialisable and auditable structures for:

- action identity;
- action parameters;
- proposal state;
- risk classification;
- confirmation requirements;
- validation results;
- execution results;
- failure information.

---

## 2. Why?

LEA will receive intent from users, AI models, workflows and integrations.

Those sources must not execute tools directly.

Instead, intent SHALL be converted into a structured proposal that deterministic application code can:

1. parse;
2. validate;
3. classify;
4. approve or reject;
5. execute through an authorised handler;
6. record as an auditable result.

This boundary prevents model output from being treated as executable authority.

---

## 3. Scope

This specification defines:

- the action proposal data model;
- stable proposal identifiers;
- action naming conventions;
- proposal lifecycle states;
- risk levels;
- confirmation policies;
- validation results;
- execution results;
- serialisation requirements;
- immutability requirements;
- initial automated tests.

This specification does not define:

- AI prompt formats;
- workflow orchestration;
- plugin discovery;
- actual tool execution;
- user-interface confirmation flows;
- adaptive confidence calculations;
- persistent audit storage;
- retry scheduling;
- permissions or authentication;
- domain-specific actions.

---

## 4. Engineering Principles

### EP-001 — Proposal Is Not Authority

An action proposal SHALL describe intent only.

Creating or validating a proposal SHALL NOT execute the proposed action.

### EP-002 — Deterministic Validation

Proposal validation SHALL be implemented in deterministic code.

AI output SHALL NOT determine whether its own proposal is valid.

### EP-003 — Explicit Lifecycle

Every proposal SHALL have an explicit lifecycle state.

State transitions SHALL be deliberate and auditable.

### EP-004 — Immutable Records

Proposal, validation and execution records SHALL be immutable after creation.

A state change SHALL create a new record rather than mutating historical data in place.

### EP-005 — Stable Identity

Every proposal SHALL have a stable unique identifier suitable for logging, confirmation and audit records.

### EP-006 — Serialisable Contract

Contract objects SHALL be serialisable to standard JSON-compatible data.

### EP-007 — Domain Independence

The core proposal contract SHALL not depend on Taskwarrior, hledger, Telegram, CRM or any other specific integration.

---

## 5. Core Data Structures

The initial implementation SHALL provide:

```text
ActionProposal
ValidationIssue
ValidationResult
ExecutionError
ExecutionResult
ActionStatus
RiskLevel
ConfirmationPolicy
```

These types SHALL reside under:

```text
src/lea/actions/
```

The initial package structure SHALL be:

```text
src/lea/actions/
├── __init__.py
├── enums.py
├── models.py
└── validation.py
```

Tests SHALL reside under:

```text
tests/actions/
```

---

## 6. Requirements

### AP-001 — Action Proposal

An action proposal SHALL contain:

- `proposal_id`;
- `action`;
- `parameters`;
- `status`;
- `risk_level`;
- `confirmation_policy`;
- `source`;
- `created_at`;
- optional `reason`.

### AP-002 — Proposal Identifier

`proposal_id` SHALL be a UUID represented as a canonical lower-case string.

Example:

```text
4b10f26d-0c54-4f3d-a14c-bce8a743116f
```

The contract SHALL allow callers to provide a proposal identifier for deterministic testing.

A helper MAY generate a UUID when one is not supplied.

### AP-003 — Action Name

The `action` field SHALL use a namespaced lower-case identifier:

```text
domain.operation
```

Examples:

```text
task.create
calendar.event_create
finance.transaction_record
crm.person_update
```

Action names SHALL:

- contain exactly one or more namespace separators using `.`;
- contain only lower-case ASCII letters, digits and underscores within each segment;
- not begin or end with `.`;
- not contain empty segments.

### AP-004 — Parameters

`parameters` SHALL be represented as a mapping of string keys to JSON-compatible values.

Supported values SHALL include:

- string;
- integer;
- finite floating-point number;
- boolean;
- null;
- lists of supported values;
- nested mappings with string keys.

Parameters SHALL NOT contain:

- arbitrary Python objects;
- functions;
- bytes;
- sets;
- non-finite numbers;
- open file handles;
- executable code.

### AP-005 — Proposal Source

The `source` field SHALL identify where the proposal originated.

Initial examples include:

```text
user
ai
workflow
system
plugin
```

The core contract SHALL store the source as a non-empty string without assigning execution authority to it.

### AP-006 — Creation Timestamp

`created_at` SHALL be timezone-aware.

New timestamps SHALL default to UTC.

Naive datetime values SHALL be rejected.

### AP-007 — Proposal Reason

`reason` MAY contain a concise human-readable explanation of why the action was proposed.

The reason SHALL NOT be used as executable input.

### AP-008 — Action Status

The initial lifecycle states SHALL be:

```text
proposed
validated
awaiting_confirmation
approved
rejected
executing
succeeded
failed
cancelled
```

### AP-009 — Initial State

A newly created proposal SHALL use the `proposed` state unless an explicitly authorised deterministic process supplies another valid state.

### AP-010 — Risk Level

The initial risk levels SHALL be:

```text
low
medium
high
critical
```

Risk level describes the potential impact of executing the action.

Risk level SHALL NOT indicate that an action has been approved.

### AP-011 — Confirmation Policy

The initial confirmation policies SHALL be:

```text
never
when_required
always
```

Their meanings SHALL be:

| Policy | Meaning |
|---|---|
| `never` | The action may proceed without interactive confirmation when all other policies allow it |
| `when_required` | Confirmation depends on risk, confidence and future policy evaluation |
| `always` | Explicit confirmation is required before execution |

### AP-012 — Safe Defaults

A proposal SHALL default to:

```text
status=proposed
risk_level=medium
confirmation_policy=when_required
```

Safe defaults SHALL favour review rather than silent execution.

### AP-013 — Immutability

Core contract records SHALL be immutable.

The implementation SHOULD use frozen, slotted dataclasses unless another standard typed structure provides equivalent guarantees.

### AP-014 — Validation Issue

A validation issue SHALL contain:

- a stable machine-readable `code`;
- a human-readable `message`;
- optional `field`.

Example:

```text
code=invalid_action_name
field=action
message=Action names must use the domain.operation format.
```

### AP-015 — Validation Result

A validation result SHALL contain:

- `valid`;
- zero or more validation issues.

A valid result SHALL contain no issues.

An invalid result SHALL contain at least one issue.

### AP-016 — Proposal Data Validation

The initial validator SHALL accept an untrusted mapping representing proposed
action data.

It SHALL check, where applicable:

- proposal identifier format;
- action-name format;
- non-empty source;
- timezone-aware creation timestamp;
- JSON compatibility of all parameters;
- recognised enum values;
- required fields;
- unknown fields;
- supported schema version.

Validation SHALL collect all independently detectable issues rather than
stopping after the first issue where practical.

A successfully constructed `ActionProposal` SHALL represent data that has
already satisfied the contract’s construction invariants.

### AP-017 — Validation Purity

Validation of proposal data SHALL NOT:

- modify the supplied mapping or its nested values;
- construct or execute an action handler;
- access the network;
- write files;
- execute plugins;
- obtain user confirmation;
- generate replacement parameters using AI.

### AP-018 — Execution Result

An execution result SHALL contain:

- `proposal_id`;
- `success`;
- final `status`;
- optional JSON-compatible `output`;
- optional execution error;
- `started_at`;
- `completed_at`.

### AP-019 — Execution Error

An execution error SHALL contain:

- machine-readable `code`;
- human-readable `message`;
- optional JSON-compatible `details`.

It SHALL NOT require a Python traceback to be serialised.

### AP-020 — Execution Result Consistency

A successful execution result SHALL:

- use `success=true`;
- use final status `succeeded`;
- contain no execution error.

A failed execution result SHALL:

- use `success=false`;
- use final status `failed`;
- contain an execution error.

### AP-021 — Execution Timestamps

Execution timestamps SHALL be timezone-aware.

`completed_at` SHALL not occur before `started_at`.

### AP-022 — JSON Conversion

Every core contract object SHALL provide a deterministic conversion to a JSON-compatible dictionary.

The conversion SHALL:

- represent enums by their string values;
- represent timestamps in ISO 8601 form;
- represent UUIDs as canonical strings;
- preserve nested JSON-compatible parameters;
- not include Python implementation details.

### AP-023 — JSON Round Trip

The initial implementation SHOULD support reconstructing an `ActionProposal` from its JSON-compatible dictionary representation.

Round-trip conversion SHALL preserve all proposal values.

### AP-024 — Unknown Fields

Proposal reconstruction SHALL reject unknown top-level fields unless a future schema-versioning standard explicitly permits them.

Silent acceptance of misspelt fields SHALL NOT occur.

### AP-025 — Schema Version

The serialised proposal representation SHALL contain:

```text
schema_version
```

The initial value SHALL be:

```text
1
```

Unsupported schema versions SHALL be rejected.

### AP-026 — Exceptions

Invalid construction or reconstruction SHALL raise a contract-specific exception derived from `LeaError`.

The initial exception SHALL be:

```text
ActionContractError
```

### AP-027 — Error Messages

Contract errors SHALL use concise UK English messages suitable for logs and user-facing diagnostics.

### AP-028 — Import Safety

Importing action-contract modules SHALL NOT:

- generate proposal identifiers;
- read configuration;
- configure logging;
- access the network;
- execute actions;
- write files.

### AP-029 — Type Safety

All public and internal functions SHALL use type annotations and pass strict mypy checks.

### AP-030 — Tests

Automated tests SHALL cover at least:

1. creation using safe defaults;
2. caller-supplied proposal identifier;
3. generated proposal identifier;
4. valid action names;
5. invalid action names;
6. valid nested JSON-compatible parameters;
7. rejection of unsupported parameter values;
8. rejection of non-finite numbers;
9. rejection of naive timestamps;
10. validation result consistency;
11. successful execution result consistency;
12. failed execution result consistency;
13. execution timestamp ordering;
14. proposal serialisation;
15. proposal round-trip reconstruction;
16. rejection of unknown fields;
17. rejection of unsupported schema versions;
18. immutability of contract records;
19. collection of multiple proposal-data issues;
20. absence of mutation or execution side effects during validation.

---

## 7. Proposal Lifecycle

The initial conceptual lifecycle is:

```text
proposed
    ↓
validated
    ↓
awaiting_confirmation
    ↓
approved
    ↓
executing
    ↓
succeeded
```

Alternative terminal paths include:

```text
proposed → rejected
approved → cancelled
executing → failed
```

This specification defines the states but does not yet implement a state-transition engine.

A future workflow specification SHALL define which transitions are permitted and who may authorise them.

Validation operates on untrusted proposal data before creation of the immutable `ActionProposal` record.

---

## 8. Example Proposal

```json
{
  "schema_version": 1,
  "proposal_id": "4b10f26d-0c54-4f3d-a14c-bce8a743116f",
  "action": "task.create",
  "parameters": {
    "description": "Call John",
    "due": "2026-07-20"
  },
  "status": "proposed",
  "risk_level": "medium",
  "confirmation_policy": "when_required",
  "source": "user",
  "created_at": "2026-07-18T20:00:00+00:00",
  "reason": "The user requested a follow-up task."
}
```

This object is a proposal only. It does not create a task.

---

## 9. Example Validation Result

```json
{
  "valid": false,
  "issues": [
    {
      "code": "invalid_action_name",
      "field": "action",
      "message": "Action names must use the domain.operation format."
    }
  ]
}
```

---

## 10. Example Execution Result

```json
{
  "proposal_id": "4b10f26d-0c54-4f3d-a14c-bce8a743116f",
  "success": true,
  "status": "succeeded",
  "output": {
    "external_id": "42"
  },
  "error": null,
  "started_at": "2026-07-18T20:01:00+00:00",
  "completed_at": "2026-07-18T20:01:01+00:00"
}
```

---

## 11. Security Considerations

Proposal parameters SHALL be treated as untrusted input.

Validation of JSON compatibility does not prove that a domain action is safe or semantically valid.

Future action handlers SHALL perform domain-specific validation before execution.

Logs SHOULD avoid recording sensitive parameter values unless a future redaction policy explicitly permits them.

A proposal identifier SHALL not be treated as authentication or authorisation.

Confirmation state SHALL not replace permission checks.

---

## 12. Out of Scope

This specification does not define:

- which actions exist;
- domain-specific parameter schemas;
- plugin handlers;
- action execution;
- confirmation user interfaces;
- confidence thresholds;
- role-based permissions;
- audit database storage;
- retries;
- idempotency keys;
- compensation or rollback;
- workflow graphs;
- AI parsing.

---

## 13. Success Criteria

This specification is satisfied when:

- immutable typed contract objects exist;
- proposals use stable UUID identifiers;
- action names are validated;
- parameters are restricted to JSON-compatible values;
- timestamps are timezone-aware;
- validation is deterministic and side-effect free;
- validation and execution-result invariants are enforced;
- proposal serialisation is deterministic;
- proposal round-trip reconstruction succeeds;
- invalid schemas and fields are rejected;
- all automated tests pass;
- Ruff, mypy and pytest pass through `scripts/check.sh`;
- no action execution is introduced.

---

## 14. Future Considerations

Future specifications MAY introduce:

- permitted state-transition rules;
- action schema registries;
- idempotency keys;
- proposal expiration;
- proposal supersession;
- cryptographic signatures;
- confirmation records;
- adaptive confidence;
- redaction metadata;
- audit persistence;
- workflow correlation identifiers;
- retry and compensation records;
- action-handler protocols.

---

## 15. References

- LEA-SPEC-0001 — Core Application Skeleton Specification
- LEA-STD-0001 — Repository Layout Standard
- RFC 2119 — Key words for use in RFCs to Indicate Requirement Levels
- RFC 8174 — Ambiguity of Uppercase vs Lowercase in RFC 2119 Key Words
- RFC 8259 — The JavaScript Object Notation Data Interchange Format
- RFC 4122 — A Universally Unique Identifier URN Namespace
