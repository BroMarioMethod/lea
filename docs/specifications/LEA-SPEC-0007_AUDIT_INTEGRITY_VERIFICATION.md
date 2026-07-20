---
title: Audit Integrity and Verification Specification
document_id: LEA-SPEC-0007
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

# Audit Integrity and Verification Specification

## Document Status

| Item | Value |
|---|---|
| Status | Accepted |
| Requires Review | No |
| Implementation | Complete |
| Test Status | Passed - 347 tests |

---

## 1. Purpose

This specification defines deterministic tamper-evident integrity and
verification for LEA audit-event files.

The integrity layer SHALL detect changes to an audit chain without causing,
replaying or modifying the workflow events represented by that chain.

The central rule is:

> Audit integrity verifies recorded history; it does not create or alter
> recorded history.

---

## 2. Why?

Milestone 1.5 introduced an append-only JSONL audit store through LEA’s
application interface.

That interface prevents normal application code from updating or deleting
historical records, but it does not prevent a user or process with sufficient
filesystem access from:

- editing an existing event;
- deleting an event;
- inserting a new event;
- reordering events;
- truncating the file;
- replacing the entire file;
- rebuilding all hashes after modification.

Milestone 1.6 SHALL add deterministic hash chaining and verification so that
many forms of modification become detectable.

It SHALL also document the important limitation that plain hashes alone do
not prove authenticity against an attacker who can rewrite the entire file
and recompute the complete chain.

---

## 3. Scope

This specification defines:

- canonical integrity metadata;
- deterministic event hashing;
- previous-event hash chaining;
- genesis-event handling;
- canonical hash input;
- verification of stored event order;
- detection of changed, removed, inserted and reordered records;
- deterministic verification results;
- structured verification issues;
- compatibility rules for Milestone 1.5 audit files;
- explicit integrity limitations;
- automated tests.

This specification does not define:

- HMAC-protected chains;
- asymmetric digital signatures;
- trusted external checkpoints;
- key storage;
- key rotation;
- encryption at rest;
- multi-writer coordination;
- remote attestation;
- distributed consensus;
- automatic file repair;
- audit-event deletion;
- automatic recovery from malformed files;
- proof that an entire rewritten file is authentic.

---

## 4. Engineering Principles

### AI-001 — Verification Only

Integrity verification SHALL NOT:

- create proposals;
- validate proposals;
- change proposal state;
- approve or reject actions;
- execute handlers;
- append audit events;
- repair the audit file automatically;
- reorder stored events.

### AI-002 — Deterministic Hashing

The same canonical audit event and previous-event hash SHALL always produce
the same event hash.

### AI-003 — Physical Order

The physical JSONL file order SHALL define the chain order.

Events SHALL NOT be reordered by timestamp during verification.

### AI-004 — Fail Closed

Malformed, unsupported or inconsistent integrity data SHALL produce an
explicit verification failure.

### AI-005 — No Hidden Mutation

Verification SHALL be read-only.

### AI-006 — Backwards Awareness

The verifier SHALL distinguish between:

- a legacy Milestone 1.5 audit file without integrity metadata;
- an integrity-enabled audit file;
- a malformed mixed-format audit file.

### AI-007 — Clear Security Claims

The implementation and documentation SHALL distinguish tamper evidence from
cryptographic authenticity.

---

## 5. Integrity Model

### AI-008 — Hash Algorithm

The initial integrity implementation SHALL use SHA-256.

The canonical algorithm identifier SHALL be:

```text
sha256
```

### AI-009 — Hash Encoding

Hashes SHALL be represented as lower-case hexadecimal strings.

A SHA-256 hash SHALL contain exactly 64 hexadecimal characters.

### AI-010 — Chain Fields

Each integrity-enabled stored audit record SHALL contain:

```text
integrity_version
hash_algorithm
previous_event_hash
event_hash
```

### AI-011 — Initial Integrity Version

The initial integrity version SHALL be:

```text
1
```

### AI-012 — Genesis Previous Hash

The first event in a chain SHALL use a canonical genesis value for
`previous_event_hash`.

The canonical value SHALL be:

```text
null
```

### AI-013 — Subsequent Previous Hash

Every event after the first SHALL store the exact `event_hash` of the
immediately preceding physical record.

### AI-014 — Event Hash

`event_hash` SHALL be calculated from:

- the canonical event data;
- the integrity version;
- the hash algorithm identifier;
- the previous-event hash.

The stored `event_hash` field itself SHALL NOT be included in its own hash
input.

---

## 6. Canonical Integrity Record

### AI-015 — Stored Shape

An integrity-enabled JSONL record SHALL resemble:

```json
{
  "event": {
    "schema_version": 1,
    "event_id": "11111111-1111-4111-8111-111111111111",
    "proposal_id": "22222222-2222-4222-8222-222222222222",
    "event_type": "proposal_created",
    "occurred_at": "2026-07-20T18:00:00+00:00",
    "payload": {}
  },
  "integrity_version": 1,
  "hash_algorithm": "sha256",
  "previous_event_hash": null,
  "event_hash": "64-character-lower-case-hexadecimal-value"
}
```

### AI-016 — Event Envelope

Integrity metadata SHALL wrap the canonical serialised `AuditEvent`.

It SHALL NOT alter the canonical `AuditEvent` contract introduced by
LEA-SPEC-0006.

### AI-017 — Unknown Fields

Unknown top-level envelope fields SHALL be rejected.

### AI-018 — Unsupported Versions

Unsupported integrity versions SHALL be rejected explicitly.

### AI-019 — Unsupported Algorithms

Unsupported hash algorithms SHALL be rejected explicitly.

### AI-020 — Event Contract Reuse

The nested `event` object SHALL be reconstructed and validated using the
existing `AuditEvent.from_dict()` contract.

---

## 7. Canonical Hash Input

### AI-021 — Canonical Input Shape

The hash input SHALL contain exactly:

```json
{
  "event": {},
  "integrity_version": 1,
  "hash_algorithm": "sha256",
  "previous_event_hash": null
}
```

### AI-022 — JSON Encoding

The canonical hash input SHALL use:

- UTF-8 encoding;
- deterministic key ordering;
- compact JSON separators;
- `ensure_ascii=False`;
- no trailing newline.

### AI-023 — Hash Calculation

The initial hash calculation SHALL be equivalent to:

```python
sha256(canonical_json_bytes).hexdigest()
```

### AI-024 — Immutable Input

Hash calculation SHALL not mutate the event or supplied integrity data.

### AI-025 — Canonical UTC Event Data

The nested event SHALL use the existing canonical UTC serialisation defined by
LEA-SPEC-0006.

### AI-026 — No Filesystem Metadata

The hash input SHALL NOT include:

- file path;
- file permissions;
- file owner;
- inode;
- file modification time;
- line number;
- operating-system metadata.

---

## 8. Integrity Envelope Contract

### AI-027 — Core Type

The initial implementation SHOULD provide an immutable record resembling:

```python
IntegrityEnvelope(
    event: AuditEvent,
    integrity_version: int,
    hash_algorithm: str,
    previous_event_hash: str | None,
    event_hash: str,
)
```

Equivalent names MAY be used.

### AI-028 — Immutability

Integrity envelopes SHALL be immutable after construction.

### AI-029 — Event Hash Validation

`event_hash` SHALL be validated as a canonical lower-case SHA-256 hexadecimal
string.

### AI-030 — Previous Hash Validation

`previous_event_hash` SHALL be either:

- `None` for the first record; or
- a canonical lower-case SHA-256 hexadecimal string.

### AI-031 — Genesis Consistency

Only the first physical record MAY use `previous_event_hash = None`.

### AI-032 — Envelope Round Trip

The implementation SHALL support deterministic dictionary serialisation and
validated reconstruction.

---

## 9. Integrity Event Creation

### AI-033 — Explicit Creation

Integrity envelopes SHALL be created explicitly from an `AuditEvent` and the
previous event hash.

### AI-034 — Genesis Factory

A genesis envelope SHALL be created with:

```text
previous_event_hash = null
```

### AI-035 — Chained Factory

A non-genesis envelope SHALL receive the previous envelope’s `event_hash`.

### AI-036 — No File Inspection in Pure Factory

The pure envelope factory SHALL NOT inspect the filesystem.

### AI-037 — No Workflow Logic

Envelope creation SHALL NOT recalculate workflow policy or action outcomes.

### AI-038 — Deterministic Testing

Factories SHOULD permit deterministic test inputs without random identifiers
or clock access.

---

## 10. Integrity-Enabled Store

### AI-039 — Separate Store Boundary

The initial implementation SHOULD provide an integrity-enabled JSONL store
separate from the Milestone 1.5 plain `JsonlAuditStore`.

A likely interface is:

```python
class IntegrityJsonlAuditStore:
    def append(self, event: AuditEvent) -> IntegrityEnvelope:
        ...

    def read_all(self) -> tuple[IntegrityEnvelope, ...]:
        ...

    def verify(self) -> AuditIntegrityVerificationResult:
        ...
```

Names MAY be refined during implementation.

### AI-040 — Existing Store Stability

The Milestone 1.5 `JsonlAuditStore` SHALL remain compatible with its existing
contract.

### AI-041 — Append Behaviour

Appending an event SHALL:

1. read or determine the current final event hash;
2. create the correct integrity envelope;
3. serialise the complete envelope in memory;
4. append exactly one JSON object and one newline;
5. flush the stream;
6. optionally perform `fsync`.

### AI-042 — Empty Store

Appending to an empty integrity store SHALL create a genesis envelope.

### AI-043 — Existing Chain Verification Before Append

Before appending to a non-empty integrity file, the store SHALL verify at
least the final chain linkage needed to avoid extending an obviously invalid
chain.

The implementation MAY perform full-chain verification for the initial
milestone.

### AI-044 — Invalid Existing Chain

The store SHALL refuse to append to a chain that fails integrity
verification.

### AI-045 — Single Writer

The integrity-enabled JSONL store SHALL retain the single-writer limitation of
Milestone 1.5.

### AI-046 — No Mutation API

The integrity-enabled store SHALL NOT provide:

- update;
- replace;
- delete;
- truncate;
- clear;
- repair.

---

## 11. Verification Result Contract

### AI-047 — Verification Result

The implementation SHALL provide an immutable verification result resembling:

```python
AuditIntegrityVerificationResult(
    valid: bool,
    checked_events: int,
    last_valid_line: int | None,
    final_event_hash: str | None,
    issues: tuple[AuditIntegrityIssue, ...],
)
```

Equivalent names MAY be used.

### AI-048 — Verification Issue

Each verification issue SHALL contain at least:

```python
AuditIntegrityIssue(
    code: str,
    message: str,
    line_number: int | None,
    event_id: str | None,
)
```

### AI-049 — Valid Result

A valid verification result SHALL:

- use `valid = True`;
- contain no issues;
- report the number of checked events;
- report the final event hash when events exist.

### AI-050 — Invalid Result

An invalid verification result SHALL:

- use `valid = False`;
- contain at least one issue;
- identify the earliest detected failure line when possible.

### AI-051 — Empty Chain

An empty integrity store SHALL verify successfully with:

```text
checked_events = 0
final_event_hash = null
issues = ()
```

---

## 12. Verification Rules

### AI-052 — Recompute Every Hash

Verification SHALL recompute every event hash from canonical input.

### AI-053 — Compare Stored Hash

The recomputed hash SHALL exactly match the stored `event_hash`.

### AI-054 — Verify Previous Link

For every record after the first:

```text
current.previous_event_hash == previous.event_hash
```

### AI-055 — Verify Genesis

The first record SHALL use `previous_event_hash = None`.

### AI-056 — Verify Algorithm

Every record SHALL use the supported canonical hash algorithm.

### AI-057 — Verify Integrity Version

Every record SHALL use a supported integrity version.

### AI-058 — Verify Event Contract

Every nested audit event SHALL satisfy the existing `AuditEvent` contract.

### AI-059 — Verify File Order

Verification SHALL process records in physical file order.

### AI-060 — No Timestamp Ordering Requirement

Verification SHALL NOT fail merely because timestamps are equal or out of
chronological order.

The chain protects physical append order, not chronological truth.

---

## 13. Detectable Modifications

### AI-061 — Edited Event

Changing any hashed event field SHALL cause verification to fail.

### AI-062 — Edited Payload

Changing nested payload data SHALL cause verification to fail.

### AI-063 — Edited Integrity Metadata

Changing the integrity version, algorithm identifier or previous-event hash
SHALL cause verification to fail.

### AI-064 — Removed Middle Event

Removing a middle record without rebuilding the remaining chain SHALL cause
verification to fail at the next record.

### AI-065 — Inserted Event

Inserting an event without correctly rebuilding subsequent chain hashes SHALL
cause verification to fail.

### AI-066 — Reordered Events

Reordering records without rebuilding the chain SHALL cause verification to
fail.

### AI-067 — Truncated Tail

Hash chaining alone cannot prove that a valid chain has not been truncated at
a valid record boundary when no trusted external final hash or checkpoint
exists.

The verifier SHALL report the remaining chain as internally valid.

This limitation SHALL be documented clearly.

### AI-068 — Entire Chain Rewrite

An attacker who can rewrite the complete file can also recompute every plain
SHA-256 hash.

Plain hash chaining SHALL therefore be described as tamper-evident against
unrecomputed modification, not authenticated against a fully capable
filesystem attacker.

---

## 14. Legacy Milestone 1.5 Files

### AI-069 — Legacy Detection

A plain Milestone 1.5 audit file SHALL be detected as a legacy unprotected
format rather than misreported as a malformed integrity envelope.

### AI-070 — Legacy Verification Status

The integrity verifier SHALL NOT report a legacy plain file as
cryptographically verified.

It SHOULD return a structured result or error indicating:

```text
integrity_not_present
```

### AI-071 — No Silent Upgrade

The verifier SHALL NOT rewrite or upgrade legacy files automatically.

### AI-072 — Explicit Migration

A future migration tool MAY convert a legacy file into a new integrity-enabled
file.

Such migration SHALL:

- preserve original event order;
- validate every legacy event first;
- create a new file rather than mutating the original by default;
- record migration provenance outside the hashed event payload or through a
  separately specified mechanism.

### AI-073 — Mixed Format

A file containing both plain audit events and integrity envelopes SHALL be
rejected as an unsupported mixed format.

---

## 15. Malformed Data

### AI-074 — Malformed JSON

Malformed JSON SHALL produce a structured verification issue or store error
with the physical line number.

### AI-075 — Blank Lines

Blank lines SHALL be rejected.

### AI-076 — Non-Object JSON

JSON values that are not objects SHALL be rejected.

### AI-077 — Missing Fields

Missing required envelope fields SHALL be rejected.

### AI-078 — Unknown Fields

Unknown top-level envelope fields SHALL be rejected.

### AI-079 — Invalid Hash Encoding

Hashes that are not exactly 64 lower-case hexadecimal characters SHALL be
rejected.

### AI-080 — Unterminated Final Line

An invalid unterminated final line SHALL be rejected.

### AI-081 — No Silent Skipping

The default verifier SHALL not silently skip malformed or invalid records.

---

## 16. Verification Issue Codes

The initial implementation SHOULD define stable issue codes including:

```text
integrity_not_present
mixed_audit_format
malformed_json
non_object_record
blank_line
unterminated_line
invalid_envelope
unsupported_integrity_version
unsupported_hash_algorithm
invalid_event_hash
invalid_previous_event_hash
invalid_genesis_link
chain_link_mismatch
event_hash_mismatch
invalid_audit_event
```

Equivalent additions MAY be introduced when needed, but existing codes SHALL
remain stable once published.

---

## 17. Security Limitations

### AI-082 — Plain Hash Limitation

SHA-256 hash chaining provides deterministic change detection when an attacker
does not rebuild the full chain.

It does not authenticate the writer.

### AI-083 — No Secret

The initial hash chain SHALL use no secret key.

### AI-084 — No Signature

The initial hash chain SHALL use no digital signature.

### AI-085 — Full Rewrite Risk

A user with complete write access to the audit file can replace the file and
recompute a valid plain hash chain.

### AI-086 — Tail Truncation Risk

Without an external trusted checkpoint, removal of one or more final valid
records cannot be proven from the remaining file alone.

### AI-087 — Operational Protection

Deployments SHOULD continue to use restrictive filesystem permissions,
backups and independent monitoring.

### AI-088 — Future Authenticated Integrity

A future milestone SHOULD introduce one or more of:

- HMAC-protected event chains;
- asymmetric signatures;
- externally stored final-hash checkpoints;
- signed periodic checkpoints;
- append-only remote storage;
- hardware-backed key storage;
- key rotation.

---

## 18. Privacy

### AI-089 — No Payload Expansion

Integrity processing SHALL hash the existing canonical event representation.

It SHALL NOT expand hidden credentials, environment variables or external
context into the event.

### AI-090 — Hashes Are Not Encryption

Hash chaining SHALL not be described as encryption.

Audit payloads remain readable unless a separate encryption mechanism is
introduced.

### AI-091 — Sensitive Files

Integrity-enabled audit files SHALL continue to be treated as sensitive
runtime data.

---

## 19. Performance

### AI-092 — Linear Verification

Full-chain verification MAY require reading and hashing every event.

The expected complexity is linear in the number of stored records.

### AI-093 — Initial Simplicity

The initial milestone SHOULD prioritise deterministic correctness over
premature indexing or optimisation.

### AI-094 — No Hidden Cache

Verification SHALL not rely on an unverified hidden cache as its source of
truth.

### AI-095 — Future Checkpoints

Trusted checkpoints MAY later reduce the amount of data required for repeated
verification.

---

## 20. Tests

Automated tests SHALL cover at least:

1. canonical SHA-256 algorithm identifier;
2. integrity version value;
3. canonical lower-case hash validation;
4. rejection of malformed hashes;
5. genesis envelope creation;
6. non-genesis envelope creation;
7. deterministic canonical hash input;
8. deterministic hash calculation;
9. envelope immutability;
10. deterministic envelope serialisation;
11. envelope dictionary round trip;
12. unknown envelope-field rejection;
13. unsupported integrity-version rejection;
14. unsupported algorithm rejection;
15. nested `AuditEvent` validation;
16. empty-chain verification;
17. single-event genesis verification;
18. multi-event chain verification;
19. final event-hash reporting;
20. physical-order verification;
21. no timestamp-based reordering;
22. edited event detection;
23. edited payload detection;
24. edited previous hash detection;
25. edited event hash detection;
26. removed middle-event detection;
27. inserted-event detection;
28. reordered-event detection;
29. malformed JSON line reporting;
30. blank-line rejection;
31. non-object record rejection;
32. invalid envelope rejection;
33. invalid genesis-link detection;
34. chain-link mismatch detection;
35. hash mismatch detection;
36. legacy plain-file detection;
37. legacy file not reported as verified;
38. mixed plain and integrity-format rejection;
39. no automatic legacy-file rewrite;
40. appending to an empty integrity store;
41. appending to a valid existing chain;
42. refusal to append to an invalid chain;
43. one deterministic JSON object per line;
44. UTF-8 storage;
45. optional `fsync`;
46. no mutation, deletion or repair API;
47. single-writer limitation documentation;
48. full-rewrite security limitation documentation;
49. tail-truncation limitation documentation;
50. full Ruff, mypy and pytest quality-gate success.

---

## 21. Out of Scope

This specification does not define:

- secret-key HMAC protection;
- asymmetric signing;
- public-key infrastructure;
- key generation;
- key storage;
- key backup;
- key recovery;
- key rotation implementation;
- trusted timestamp authorities;
- external checkpoint services;
- remote append-only ledgers;
- hardware security modules;
- TPM integration;
- encryption at rest;
- audit-file compression;
- retention policy;
- automatic repair;
- deletion recovery;
- multi-writer locking;
- distributed writers;
- proof against complete chain replacement;
- proof against valid tail truncation without checkpoints.

---

## 22. Success Criteria

This specification is satisfied when:

- immutable integrity envelopes exist;
- SHA-256 event hashes are deterministic;
- each non-genesis event links to the previous physical record;
- genesis handling is explicit;
- canonical hash input is stable;
- full-chain verification is deterministic;
- verification returns structured immutable results;
- modified events are detected;
- modified payloads are detected;
- broken chain links are detected;
- inserted and reordered records are detected unless the full chain is rebuilt;
- legacy Milestone 1.5 files are identified explicitly;
- mixed formats are rejected;
- no existing workflow function gains hidden mutation or persistence;
- the existing plain JSONL store remains compatible;
- the integrity-enabled store exposes no destructive API;
- security limitations are documented accurately;
- all automated tests pass;
- Ruff, mypy and pytest pass through `scripts/check.sh`.

---

## 23. Future Considerations

Future specifications MAY introduce:

- HMAC-protected chains;
- asymmetric digital signatures;
- signed checkpoints;
- external final-hash publication;
- remote append-only checkpoint storage;
- hardware-backed keys;
- key rotation;
- key revocation;
- multiple signing identities;
- archive signing;
- checkpoint-based partial verification;
- secure legacy-file migration;
- integrity reports for administrators;
- scheduled verification;
- alerting on integrity failure;
- backup comparison;
- replicated audit stores;
- trusted timestamping;
- encrypted audit payloads.

---

## 24. References

- LEA-SPEC-0006 — Action Audit Trail Specification
- LEA-STD-0001 — Repository Layout Standard
- LEA-STD-0002 — Repository Bootstrap Standard
- RFC 2119 — Key words for use in RFCs to Indicate Requirement Levels
- RFC 8174 — Ambiguity of Uppercase vs Lowercase in RFC 2119 Key Words
- RFC 8259 — The JavaScript Object Notation Data Interchange Format
- FIPS PUB 180-4 — Secure Hash Standard

