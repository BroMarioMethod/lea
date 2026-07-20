# Audit Storage

LEA provides an append-only JSON Lines audit store for deterministic action
workflow events.

The audit store records workflow outcomes. It does not create proposals,
change proposal state, approve actions or execute handlers.

## Canonical format

The initial canonical audit format is JSON Lines, commonly abbreviated as
JSONL.

Each physical line contains exactly one complete JSON object followed by a
newline:

```text
{"event_id":"...","event_type":"proposal_created",...}
{"event_id":"...","event_type":"validation_completed",...}
```

The file is written using:

- UTF-8 encoding;
- one event per line;
- compact JSON separators;
- deterministic key ordering;
- explicit UTC timestamps.

The physical append order is the canonical initial event sequence. Events are
not automatically reordered by timestamp.

## Runtime location

Audit files are runtime data and must remain outside the Git repository.

A deployment may use:

```text
/var/lib/lea/audit/actions.jsonl
```

The path is supplied explicitly when constructing the store:

```python
from lea.audit import JsonlAuditStore

store = JsonlAuditStore(
    "/var/lib/lea/audit/actions.jsonl",
    create_parents=True,
    fsync=True,
)
```

Tests and development tools should use temporary or explicitly selected
runtime directories rather than `/var/lib/lea`.

## Append-only interface

The core store supports:

```python
store.append(event)
store.read_all()
store.read_for_proposal(proposal_id)
```

It deliberately does not provide:

```text
update
replace
delete
truncate
clear
```

This prevents normal application code from modifying or deleting historical
audit events through the store interface.

## Missing files

A missing audit file represents an empty audit store.

Therefore:

```python
store.read_all()
```

returns an empty tuple when the configured file does not yet exist.

## Parent directories

Parent-directory creation is disabled by default.

Use:

```python
JsonlAuditStore(
    path,
    create_parents=True,
)
```

only when the caller should be allowed to create the configured runtime
directory structure.

## Filesystem synchronisation

Filesystem synchronisation is optional and disabled by default.

Use:

```python
JsonlAuditStore(
    path,
    fsync=True,
)
```

to flush each appended event and request filesystem synchronisation before the
append operation returns.

This may improve durability but can reduce write performance.

## Malformed records

The default reader fails closed when it encounters:

- malformed JSON;
- blank lines;
- JSON values that are not objects;
- unsupported schema versions;
- unknown top-level event fields;
- invalid event data;
- an unterminated final line.

The resulting `AuditStoreError` includes:

- the audit-file path;
- the physical line number, when applicable;
- a structured error message.

Malformed records are not silently skipped.

## Single-writer limitation

The initial JSONL implementation assumes one writer process at a time.

It does not provide:

- cross-process locking;
- concurrent-writer coordination;
- transactional multi-process appends;
- a dedicated audit service.

Deployments must ensure that only one process writes to a given audit file at
a time.

Future implementations may introduce file locking, SQLite journalling or a
dedicated audit service.

## Integrity limitation

The append-only interface prevents mutation through LEA’s normal audit-store
API. It does not make the underlying file tamper-proof.

A user or process with sufficient filesystem access may still:

- edit an existing line;
- remove selected events;
- truncate the file;
- replace the file;
- delete the file.

Cryptographic integrity is reserved for a future milestone. Planned options
include:

- hash-chained audit events;
- HMAC-protected chains;
- asymmetric digital signatures;
- signed checkpoints;
- externally stored trusted checkpoints;
- integrity-verification commands;
- key rotation.

Until those controls exist, the JSONL audit trail should be described as
append-only through the application interface, not cryptographically
tamper-proof.

## File permissions

Audit payloads may contain sensitive operational information, including:

- action parameters;
- validation issues;
- confirmation decisions and reasons;
- execution output;
- structured execution errors.

Deployments should restrict the audit directory and file to the LEA service
account and authorised administrators.

A typical deployment should avoid granting general users write access to the
audit directory.

## Current constraints

The initial implementation does not provide:

- cryptographic integrity;
- encryption at rest;
- retention rules;
- log rotation;
- archival;
- compression;
- remote replication;
- tolerant malformed-line recovery;
- multi-process writing;
- a user-facing audit browser.

These are future roadmap concerns rather than guarantees of the current
milestone.

