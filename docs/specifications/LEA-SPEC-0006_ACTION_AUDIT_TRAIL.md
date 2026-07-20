---
title: Action Audit Trail Specification
document_id: LEA-SPEC-0006
version: 0.1.2
status: Accepted
authors:
  - Marius du Preez
  - OpenAI ChatGPT
license: GPL-3.0-only
created: 2026-07-20
last_updated: 2026-07-20
review_required: false
---

# Action Audit Trail Specification

## Document Status

| Item | Value |
|---|---|
| Status | Accepted |
| Requires Review | No |
| Implementation | Complete |
| Test Status | Passed - 292 tests |

---

## 1. Purpose

This specification defines the deterministic audit-event contract and append-only storage boundary for LEA action workflows.

The audit trail SHALL provide a durable, ordered and serialisable record of workflow events without causing or controlling those events.

The central rule is:

> The audit trail records workflow events; it does not cause workflow events.

---

## 2. Why?

LEA currently produces immutable structured records for:

- action proposals;
- validation outcomes;
- proposal-state transitions;
- confirmation-policy evaluations;
- human confirmation decisions;
- execution outcomes;
- execution-boundary issues.

Those records are presently returned to callers but are not persisted as one ordered workflow history.

Without a central audit boundary:

- workflow evidence may be lost after process exit;
- different integrations may log inconsistent structures;
- event order may be unclear;
- debugging and accountability may rely on unstructured application logs;
- future SQLite indexes would lack one canonical source.

---

## 3. Scope

This specification defines:

- immutable audit events;
- canonical event types;
- deterministic event identifiers;
- proposal correlation;
- canonical UTC timestamps;
- JSON-compatible event payloads;
- deterministic JSON serialisation;
- append-only JSON Lines storage;
- ordered retrieval;
- retrieval by proposal identifier;
- malformed-record handling;
- safe filesystem behaviour;
- automated tests.

This specification does not define:

- automatic instrumentation of every workflow function;
- SQLite indexes;
- full-text search;
- audit-event deletion;
- audit-event mutation;
- log rotation;
- retention policy;
- archival;
- compression;
- encryption at rest;
- cryptographic signatures;
- hash chaining;
- remote replication;
- multi-process locking;
- network storage;
- user interfaces;
- role-based access control;
- metrics or operational application logging.

---

## 4. Engineering Principles

### AT-001 — Observation Only

Writing an audit event SHALL NOT:

- create a proposal;
- validate a proposal;
- change proposal state;
- approve or reject a proposal;
- execute an action;
- invoke a handler;
- retry a workflow operation.

### AT-002 — Append Only

The core audit API SHALL support appending and reading events.

It SHALL NOT expose mutation or deletion operations.

### AT-003 — Canonical Source

The JSONL audit file SHALL be the canonical initial audit source.

Future SQLite databases, indexes and projections SHALL be reproducible from it.

### AT-004 — Repository and Runtime Separation

Audit files SHALL be runtime data.

They SHALL NOT be stored inside or tracked by the Git repository.

### AT-005 — Deterministic Records

Audit events SHALL use deterministic field names and JSON-compatible values.

### AT-006 — Explicit Event Construction

Audit events SHALL be created explicitly from existing workflow records.

The audit layer SHALL NOT infer or reconstruct policy decisions independently.

### AT-007 — Immutable Events

Audit events SHALL be immutable after construction.

### AT-008 — Conservative Failure

Invalid or unsupported audit data SHALL fail before being appended.

Malformed stored records SHALL be reported explicitly rather than silently ignored.

---

## 5. Runtime Location

### AT-009 — Configurable Path

The audit store SHALL receive its file path explicitly.

The store SHALL NOT discover a path through hidden global state.

### AT-010 — Initial Deployment Default

A deployment MAY configure the initial audit file at:

```text
/var/lib/lea/audit/actions.jsonl
```

This path is a deployment default, not a repository path.

### AT-011 — Parent Directory

The store MAY create a missing parent directory when explicitly permitted by its caller.

The initial implementation SHOULD make this behaviour explicit through a constructor option.

### AT-012 — Tests

Automated tests SHALL use isolated temporary directories.

Tests SHALL NOT write to `/var/lib/lea`.

---

## 6. Audit Event Contract

### AT-013 — Core Type

The initial implementation SHALL provide an immutable record resembling:

```python
AuditEvent(
    event_id: str,
    proposal_id: str,
    event_type: AuditEventType,
    occurred_at: datetime,
    payload: Mapping[str, object],
)
```

Names MAY be refined during implementation provided the observable contract remains unchanged.

### AT-014 — Event Identifier

`event_id` SHALL be a canonical lower-case UUID string.

### AT-015 — Proposal Identifier

`proposal_id` SHALL be the canonical lower-case UUID of the related proposal.

### AT-016 — Event Timestamp

`occurred_at` SHALL be timezone-aware and canonicalised to UTC.

Naive timestamps SHALL be rejected.

### AT-017 — Payload

`payload` SHALL contain JSON-compatible data only.

It SHALL be deeply immutable inside the event.

### AT-018 — Payload Ownership

The payload SHALL contain the serialised workflow record relevant to the event.

The audit layer SHALL reuse existing serializers wherever available.

### AT-019 — No Executable Values

An audit payload SHALL not contain:

- callable objects;
- handlers;
- registries;
- exception objects;
- tracebacks;
- open files;
- database connections;
- arbitrary Python object representations.

---

## 7. Canonical Event Types

### AT-020 — Event Enum

The initial canonical event types SHALL include:

```text
proposal_created
validation_completed
transition_completed
transition_rejected
confirmation_evaluated
confirmation_recorded
confirmation_policy_applied
confirmation_decision_applied
execution_completed
execution_boundary_rejected
```

### AT-021 — Proposal Created

`proposal_created` SHALL contain the serialised `ActionProposal`.

### AT-022 — Validation Completed

`validation_completed` SHALL contain the serialised `ValidationResult`.

### AT-023 — Transition Completed

`transition_completed` SHALL contain a successful serialised `TransitionResult`.

### AT-024 — Transition Rejected

`transition_rejected` SHALL contain a failed serialised `TransitionResult`.

### AT-025 — Confirmation Evaluated

`confirmation_evaluated` SHALL contain a serialised `ConfirmationEvaluationResult`.

### AT-026 — Confirmation Recorded

`confirmation_recorded` SHALL contain a serialised `ConfirmationRecordResult`.

### AT-027 — Confirmation Policy Applied

`confirmation_policy_applied` SHALL contain a serialised `ConfirmationPolicyApplicationResult`.

### AT-028 — Confirmation Decision Applied

`confirmation_decision_applied` SHALL contain a serialised `ConfirmationDecisionApplicationResult`.

### AT-029 — Execution Completed

`execution_completed` SHALL contain an `ActionExecutionResult` where handler invocation occurred.

This includes successful execution and handled execution failure.

### AT-030 — Execution Boundary Rejected

`execution_boundary_rejected` SHALL contain an `ActionExecutionResult` representing a pre-handler boundary rejection.

### AT-031 — Event-Type Accuracy

The event type SHALL agree with the supplied workflow record.

Inconsistent event construction SHALL raise `ActionContractError`.

---

## 8. Event Creation

### AT-032 — Factory Functions

The initial implementation SHOULD provide deterministic factory functions for existing workflow records.

Examples:

```python
audit_proposal_created(proposal)
audit_validation_completed(proposal_id, result)
audit_transition_result(result)
audit_confirmation_evaluation(result)
audit_confirmation_record(result)
audit_confirmation_policy_application(result)
audit_confirmation_decision_application(result)
audit_action_execution(result)
```

Equivalent names MAY be used.

### AT-033 — No Policy Duplication

Factory functions SHALL inspect only enough record state to choose the correct event type and serialised payload.

They SHALL NOT recalculate:

- transition legality;
- confirmation requirements;
- approval decisions;
- execution outcomes.

### AT-034 — Event Timestamp Source

By default, an event SHOULD use the timestamp of the wrapped workflow record when one canonical timestamp exists.

Examples include:

- proposal `created_at`;
- transition `transitioned_at`;
- confirmation `evaluated_at`;
- confirmation `decided_at`;
- execution `completed_at`.

### AT-035 — Explicit Timestamp Override

Factories MAY allow an explicit timezone-aware event timestamp when the wrapped record has no single canonical timestamp.

The timestamp SHALL be canonicalised to UTC.

### AT-036 — Event Identifier Injection

Factories SHOULD permit deterministic `event_id` injection for automated tests.

Production callers MAY use a generated UUID.

---

## 9. Audit Event Serialisation

### AT-037 — JSON Dictionary

`AuditEvent` SHALL provide deterministic conversion to a JSON-compatible dictionary.

### AT-038 — Schema Version

Serialised audit events SHALL include an audit schema version.

The initial value SHALL be:

```text
1
```

### AT-039 — Canonical Shape

The initial serialised shape SHALL be:

```json
{
  "schema_version": 1,
  "event_id": "canonical-uuid",
  "proposal_id": "canonical-uuid",
  "event_type": "transition_completed",
  "occurred_at": "2026-07-20T18:00:00+00:00",
  "payload": {}
}
```

### AT-040 — Enum Representation

Enums SHALL be represented by their string values.

### AT-041 — Timestamp Representation

Timestamps SHALL use ISO 8601 with explicit UTC timezone information.

### AT-042 — Round Trip

The initial implementation SHALL support reconstructing an `AuditEvent` from validated dictionary data.

### AT-043 — Unknown Fields

Unknown top-level event fields SHALL be rejected during reconstruction.

### AT-044 — Unsupported Schema

Unsupported schema versions SHALL be rejected explicitly.

---

## 10. JSON Lines Storage

### AT-045 — One Event Per Line

Each audit event SHALL be stored as exactly one JSON object followed by one newline.

### AT-046 — UTF-8

The audit file SHALL use UTF-8 encoding.

### AT-047 — Deterministic Encoding

JSON encoding SHALL use deterministic options including stable key ordering and compact separators.

### AT-048 — Append Operation

Appending an event SHALL:

1. validate the event;
2. serialise it completely in memory;
3. encode it as one JSON line;
4. open the file in append mode;
5. write the complete line;
6. flush the stream.

### AT-049 — No Partial Object Construction

The store SHALL NOT begin a write before serialisation succeeds.

### AT-050 — File Synchronisation

The initial implementation SHOULD optionally support `fsync` after append.

Whether `fsync` is enabled SHALL be explicit.

### AT-051 — Existing Content

Appending SHALL preserve all existing bytes in the audit file.

### AT-052 — Empty Store

Reading a missing audit file SHALL return an empty tuple.

### AT-053 — Blank Lines

Blank lines SHALL be rejected as malformed audit content rather than silently interpreted as events.

---

## 11. Ordered Retrieval

### AT-054 — File Order

Reading all events SHALL preserve physical file order.

### AT-055 — Proposal Filtering

The store SHALL support retrieving events matching an exact `proposal_id`.

### AT-056 — Filter Order

Proposal-filtered retrieval SHALL preserve original file order.

### AT-057 — No Timestamp Reordering

The store SHALL NOT reorder events by timestamp automatically.

File append order is the canonical initial sequence.

### AT-058 — Event Sequence

Read operations SHOULD return immutable tuples of `AuditEvent`.

---

## 12. Malformed Stored Data

### AT-059 — Malformed JSON

Invalid JSON SHALL produce a structured audit-read error identifying the line number.

### AT-060 — Invalid Event Shape

A syntactically valid JSON object that violates the event contract SHALL produce a structured audit-read error identifying the line number.

### AT-061 — Non-Object Lines

JSON values that are not objects SHALL be rejected.

### AT-062 — No Silent Skipping

Malformed lines SHALL not be silently skipped by the default reader.

### AT-063 — Partial Final Line

A partial or unterminated invalid final line SHALL be treated as malformed.

### AT-064 — Read Result

The initial reader MAY raise a dedicated `AuditStoreError` when malformed content is encountered.

A later specification MAY introduce recovery or tolerant inspection modes.

---

## 13. Store Interface

### AT-065 — Initial Store

The initial implementation SHALL provide a JSONL-backed store resembling:

```python
class JsonlAuditStore:
    def append(self, event: AuditEvent) -> None:
        ...

    def read_all(self) -> tuple[AuditEvent, ...]:
        ...

    def read_for_proposal(
        self,
        proposal_id: str,
    ) -> tuple[AuditEvent, ...]:
        ...
```

Names MAY be refined during implementation.

### AT-066 — No Mutation API

The store SHALL NOT provide:

- update;
- replace;
- delete;
- truncate;
- clear.

### AT-067 — Explicit Dependency

Workflow orchestration code SHALL receive an audit store explicitly when persistence is required.

### AT-068 — No Hidden Automatic Persistence

Existing workflow functions SHALL not begin writing audit records implicitly during this milestone.

The caller SHALL explicitly create and append audit events.

This preserves separation between workflow behaviour and audit persistence.

---

## 14. Append Failure Behaviour

### AT-069 — Workflow Independence

An audit append failure SHALL not retroactively change the immutable workflow result being recorded.

### AT-070 — Caller Responsibility

The caller SHALL decide how an audit append failure affects the broader application operation.

### AT-071 — Explicit Error

Filesystem and encoding failures SHALL be exposed through a dedicated audit-store error.

### AT-072 — No Automatic Retry

The audit store SHALL not retry failed writes during this milestone.

---

## 15. Privacy and Security

### AT-073 — Sensitive Payloads

Audit payloads may contain:

- action parameters;
- human confirmation reasons;
- execution output;
- error details.

Callers SHALL treat audit files as sensitive runtime data.

### AT-074 — File Permissions

Deployments SHOULD restrict audit-file access to the LEA service account and authorised administrators.

### AT-075 — No Secret Expansion

The audit layer SHALL not expand environment variables, credentials or hidden runtime context into event payloads.

### AT-076 — Exception Safety

Exception objects and tracebacks SHALL never be stored in normal audit events.

### AT-077 — Integrity Limitations

Append-only API design does not prevent external filesystem modification.

Someone with sufficient filesystem access may still edit, remove, replace or truncate the audit file.

Cryptographic integrity, signatures, trusted checkpoints and tamper evidence are out of scope for this milestone and SHALL be addressed by a later audit-integrity specification.

---

## 16. Concurrency Limitations

### AT-078 — Single-Writer Assumption

The initial JSONL store SHALL assume one writer process at a time.

### AT-079 — Multi-Process Locking

Cross-process locking is out of scope.

### AT-080 — Documented Limitation

The store documentation SHALL state that concurrent writers are unsupported in the initial implementation.

### AT-081 — Future Strengthening

A future specification MAY introduce file locking, SQLite journalling or a dedicated audit service.

---

## 17. Tests

Automated tests SHALL cover at least:

1. canonical event-type values;
2. canonical event identifier validation;
3. canonical proposal identifier validation;
4. rejection of naive event timestamps;
5. UTC-aware event timestamps;
6. deeply immutable payloads;
7. deterministic event serialisation;
8. event dictionary round trip;
9. unsupported schema-version rejection;
10. unknown-field rejection;
11. proposal-created event factory;
12. validation-result event factory;
13. successful transition event factory;
14. rejected transition event factory;
15. confirmation-evaluation event factory;
16. confirmation-record event factory;
17. confirmation-policy-application event factory;
18. confirmation-decision-application event factory;
19. successful execution event factory;
20. handled execution-failure event factory;
21. pre-execution boundary-rejection event factory;
22. inconsistent event-type rejection;
23. append creates a missing audit file;
24. append preserves existing events;
25. one compact JSON object per line;
26. UTF-8 storage;
27. deterministic JSON key ordering;
28. complete serialisation before writing;
29. reading a missing store returns an empty tuple;
30. ordered full retrieval;
31. exact proposal filtering;
32. filtered retrieval preserves file order;
33. malformed JSON reports its line number;
34. invalid event shape reports its line number;
35. non-object JSON rejection;
36. blank-line rejection;
37. partial final-line rejection;
38. no mutation or deletion methods;
39. no automatic workflow execution;
40. no automatic audit persistence in existing workflow functions;
41. append failure does not mutate the workflow record;
42. no retry after append failure;
43. no callable, handler, registry, exception or traceback objects in serialised events;
44. single-writer limitation is documented;
45. full Ruff, mypy and pytest quality-gate success.

---

## 18. Out of Scope

This specification does not define:

- audit-event mutation;
- audit-event deletion;
- log rotation;
- retention periods;
- archive files;
- compression;
- cryptographic signatures;
- hash chaining;
- tamper-proof storage;
- encryption;
- remote storage;
- network transport;
- SQLite persistence;
- SQLite indexing;
- full-text search;
- dashboards;
- alerting;
- metrics;
- automatic workflow instrumentation;
- distributed transactions;
- atomic coupling between external side effects and audit writes;
- multi-process writers;
- cross-process locks;
- recovery tooling;
- tolerant malformed-line skipping;
- user-facing audit reports.

---

## 19. Success Criteria

This specification is satisfied when:

- immutable audit events exist;
- canonical event types cover the current action workflow;
- events reuse existing workflow serializers;
- event identifiers are canonical UUIDs;
- timestamps are UTC-aware and canonicalised to UTC;
- payloads are deeply immutable;
- serialisation is deterministic;
- event round trips are validated;
- JSONL storage is append-only through the core API;
- one event is written per line;
- reading a missing store returns an empty tuple;
- ordered retrieval works;
- proposal-filtered retrieval works;
- malformed lines fail explicitly;
- audit files remain outside the Git repository;
- workflow functions do not gain hidden persistence;
- no mutation or deletion API is introduced;
- all automated tests pass;
- Ruff, mypy and pytest pass through `scripts/check.sh`.

---

## 20. Future Considerations

Future specifications MAY introduce:

- deployment workspace discovery;
- configurable retention;
- log rotation;
- archive compression;
- file locking;
- SQLite projections;
- audit query indexes;
- audit reports;
- cryptographic event hashes;
- hash-chained audit events;
- HMAC-protected event chains;
- asymmetric digital signatures;
- digitally signed audit checkpoints;
- externally stored trusted checkpoints;
- audit-chain verification commands;
- key rotation;
- encryption at rest;
- replicated audit stores;
- remote append services;
- automatic workflow instrumentation;
- transactional outbox patterns;
- recovery and repair tooling;
- tolerant inspection mode;
- event redaction policy;
- per-field sensitivity classifications;
- audit access permissions.

---

## 21. References

- LEA-STD-0001 — Repository Layout Standard
- LEA-STD-0002 — Repository Bootstrap Standard
- LEA-SPEC-0002 — Action Proposal Contract Specification
- LEA-SPEC-0003 — Action State Transition Specification
- LEA-SPEC-0004 — Confirmation and Approval Policy Specification
- LEA-SPEC-0005 — Action Execution Boundary Specification
- RFC 2119 — Key words for use in RFCs to Indicate Requirement Levels
- RFC 8174 — Ambiguity of Uppercase vs Lowercase in RFC 2119 Key Words
- RFC 8259 — The JavaScript Object Notation Data Interchange Format
