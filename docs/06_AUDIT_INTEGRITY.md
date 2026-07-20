# Audit Integrity and Verification

LEA provides a deterministic SHA-256 hash chain for integrity-enabled audit
records.

The integrity layer verifies recorded audit history. It does not create,
approve, reject, execute, repair or reorder workflow events.

## Purpose

The Milestone 1.5 JSONL audit store is append-only through LEA’s application
interface, but a user or process with sufficient filesystem access could still
edit, remove, insert, reorder, truncate or replace audit records.

Milestone 1.6 adds tamper-evident verification by linking each stored audit
event to the hash of the preceding physical record.

## Integrity envelope

Each integrity-enabled JSONL line contains an envelope with:

- the canonical serialised `AuditEvent`;
- `integrity_version`;
- `hash_algorithm`;
- `previous_event_hash`;
- `event_hash`.

The initial integrity version is:

```text
1
```

The initial hash algorithm is:

```text
sha256
```

A stored envelope resembles:

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

## Canonical hash input

The hash input contains:

```json
{
  "event": {},
  "integrity_version": 1,
  "hash_algorithm": "sha256",
  "previous_event_hash": null
}
```

The `event_hash` field is excluded from its own hash input.

Canonical encoding uses:

- UTF-8;
- deterministic key ordering;
- compact JSON separators;
- `ensure_ascii=False`;
- no trailing newline.

The event hash is calculated as:

```python
sha256(canonical_json_bytes).hexdigest()
```

## Genesis record

The first physical record in an integrity chain is the genesis record.

It must use:

```text
previous_event_hash = null
```

Every later record must use the exact `event_hash` of the immediately preceding
physical record.

## Integrity-enabled store

Use:

```python
from lea.audit import IntegrityJsonlAuditStore

store = IntegrityJsonlAuditStore(
    "/var/lib/lea/audit/actions-integrity.jsonl",
    create_parents=True,
    fsync=True,
)
```

The store supports:

```python
envelope = store.append(event)
envelopes = store.read_all()
verification = store.verify()
```

The integrity-enabled store remains separate from the plain Milestone 1.5
`JsonlAuditStore`.

## Append behaviour

Appending to an empty integrity store creates a genesis envelope.

Appending to a non-empty integrity store:

1. reads the existing file;
2. validates its format;
3. verifies the existing chain;
4. refuses to continue if verification fails;
5. links the new envelope to the final valid event hash;
6. serialises the complete envelope in memory;
7. appends one compact JSON object and one newline;
8. flushes the stream;
9. optionally performs `fsync`.

The store does not append to an invalid chain.

## Verification

Verification processes envelopes in physical file order.

It:

- verifies that the first record has a null previous hash;
- verifies each subsequent previous-hash link;
- recomputes each event hash;
- compares each stored hash to the canonical recalculated hash;
- returns a structured immutable result;
- stops at the first detected failure.

A valid empty chain reports:

```text
valid = true
checked_events = 0
last_valid_line = null
final_event_hash = null
issues = ()
```

A valid non-empty chain reports the final verified event hash.

An invalid result includes a stable issue code, message, physical line number
when available and related event identifier when available.

## Detectable changes

Without rebuilding all later hashes, verification detects:

- edited event fields;
- edited payload data;
- edited integrity metadata;
- changed event hashes;
- changed previous-event hashes;
- removed middle records;
- inserted records;
- reordered records;
- broken genesis links.

The verifier protects physical append order. It does not require timestamps to
be chronologically ordered.

## Legacy files

A plain Milestone 1.5 JSONL audit file is recognised as a legacy unprotected
format.

It is not reported as integrity-verified.

Verification returns an `integrity_not_present` issue.

The integrity store does not silently rewrite, migrate or extend a legacy
plain audit file.

A future migration tool may create a new integrity-enabled file while
preserving and validating the original record order.

## Mixed formats

A file containing both plain audit events and integrity envelopes is rejected
as an unsupported mixed format.

The implementation does not silently merge or upgrade mixed data.

## Malformed records

The integrity reader rejects:

- malformed JSON;
- blank lines;
- non-object JSON values;
- unknown record shapes;
- missing envelope fields;
- unknown envelope fields;
- invalid nested audit events;
- unsupported integrity versions;
- unsupported hash algorithms;
- malformed hashes;
- unterminated final lines.

Malformed records are not silently skipped.

## Single-writer limitation

The integrity-enabled JSONL store assumes one writer process at a time.

It does not provide:

- cross-process locking;
- concurrent-writer coordination;
- transactional multi-process appends;
- a dedicated audit service.

Deployments must ensure that only one process writes to a given integrity file
at a time.

## Security limitations

SHA-256 hash chaining provides tamper evidence against changes where the full
chain is not correctly rebuilt.

It does not authenticate the writer.

A user with complete write access to the file may replace the full file and
recompute a valid plain hash chain.

A valid tail may also be truncated at a record boundary without detection from
the remaining file alone when no trusted external final hash or checkpoint
exists.

Therefore, the current implementation must not be described as:

- tamper-proof;
- authenticated;
- digitally signed;
- protected by a secret key;
- proof against complete replacement;
- proof against valid tail truncation.

Future milestones may add:

- HMAC-protected chains;
- asymmetric digital signatures;
- signed checkpoints;
- externally stored trusted final hashes;
- hardware-backed keys;
- key rotation;
- remote append-only checkpoint storage.

## Hashes are not encryption

Hash chaining does not encrypt audit payloads.

The stored event data remains readable.

Deployments should continue to restrict file and directory permissions because
audit payloads may contain:

- action parameters;
- validation issues;
- confirmation decisions and reasons;
- execution output;
- structured errors.

## Append-only interface

The integrity store deliberately provides no:

```text
update
replace
delete
truncate
clear
repair
```

Verification is read-only and does not repair or mutate the file.

## Current constraints

The current integrity implementation does not provide:

- HMAC authentication;
- digital signatures;
- trusted external checkpoints;
- key generation or storage;
- key rotation;
- encryption at rest;
- multi-writer locking;
- automatic legacy migration;
- automatic repair;
- proof against complete chain replacement;
- proof against valid tail truncation;
- remote attestation;
- a user-facing integrity browser.

These remain future roadmap concerns.
