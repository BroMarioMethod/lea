---
id: LEA-SPEC-0010
title: Persistent Proposal Repository Specification
version: 0.1.1
status: Accepted
review_required: false
---

# Persistent Proposal Repository Specification

## Status

| Item | Value |
|---|---|
| Status | Accepted |
| Requires Review | No |
| Implementation | Not Started |
| Test Status | Not Tested |

## 1. Purpose

This specification defines the first durable repository for LEA action proposals.

The repository shall persist validated `ActionProposal` records as deterministic, human-readable Markdown documents beneath the configured runtime proposal directory.

The repository shall preserve LEA's existing boundaries:

- an action proposal describes intent and grants no execution authority;
- deterministic code owns validation and persistence;
- Markdown is the canonical human-readable source;
- runtime data remains outside the Git repository;
- audit persistence remains a separate append-only evidence boundary.

## 2. Scope

Milestone 2.1 shall provide:

- immutable proposal-repository result and issue contracts;
- a deterministic Markdown document format;
- stable file naming based on canonical proposal identifiers;
- atomic proposal creation;
- exact proposal retrieval by identifier;
- deterministic proposal listing;
- explicit duplicate, missing and malformed-document failures;
- read-only repository verification;
- optional orchestration integration through an injected repository boundary;
- operator documentation;
- automated tests using isolated runtime paths.

## 3. Non-goals

Milestone 2.1 shall not provide:

- proposal deletion;
- in-place proposal mutation;
- proposal-state event history inside the proposal document;
- Taskwarrior integration;
- Telegram or LAN messaging;
- calendar, CRM or accounting integration;
- SQLite indexing;
- full-text search;
- multi-process writer locking;
- remote storage;
- encryption at rest;
- cryptographic signatures;
- automatic backup;
- automatic migration;
- conflict resolution;
- execution or confirmation authority.

## 4. Engineering principles

### PR-001 — Proposal is not authority

Persisting, loading or listing a proposal shall not validate, approve, confirm or execute it.

### PR-002 — Canonical Markdown source

Each proposal shall have one canonical Markdown document.

Future indexes and databases shall be reproducible from those documents.

### PR-003 — Stable identity

The canonical lower-case UUID `proposal_id` shall determine the document identity and filename.

### PR-004 — Immutable records

The repository shall create and read immutable proposal records.

It shall not expose general update, replace or delete operations.

### PR-005 — Deterministic parsing

Repository loading shall reuse the existing proposal validation and serialisation boundaries.

Malformed or unsupported documents shall fail closed.

### PR-006 — Runtime separation

Proposal documents shall be stored beneath `RuntimePaths.proposal_dir`.

They shall not be written into tracked repository source directories.

### PR-007 — Explicit filesystem behaviour

Parent creation, synchronisation and repository verification shall be explicit.

No repository operation shall silently repair malformed content.

## 5. Existing proposal contract

The repository shall persist the existing `ActionProposal` fields:

- `proposal_id`;
- `action`;
- `parameters`;
- `status`;
- `risk_level`;
- `confirmation_policy`;
- `source`;
- `created_at`;
- optional `reason`.

The existing proposal schema version and deterministic JSON-compatible serialisation shall remain authoritative for field meaning and validation.

The repository shall not introduce a second competing proposal model.

## 6. Repository location

### PR-008 — Explicit root

The repository shall receive its proposal directory explicitly as an absolute `Path`.

The standard runtime integration shall use:

```python
runtime_config.paths.proposal_dir
```

### PR-009 — Canonical layout

Each proposal shall be stored as:

```text
<proposal_dir>/<proposal_id>.md
```

Example:

```text
/var/lib/lea/proposals/4b10f26d-0c54-4f3d-a14c-bce8a743116f.md
```

### PR-010 — No hidden discovery

The repository shall not search environment variables, the current working directory or repository-relative fallback paths.

## 7. Markdown document format

### PR-011 — UTF-8 Markdown

Documents shall use UTF-8, LF line endings and exactly one trailing newline.

### PR-012 — Deterministic front matter

Each document shall begin with deterministic YAML-style front matter containing scalar metadata:

```yaml
---
schema_version: 1
proposal_id: 4b10f26d-0c54-4f3d-a14c-bce8a743116f
action: task.create
status: proposed
risk_level: medium
confirmation_policy: when_required
source: user
created_at: 2026-07-21T12:00:00+00:00
---
```

Field order shall be fixed.

Unknown or missing front-matter fields shall fail closed.

### PR-013 — Human-readable body

The Markdown body shall contain stable sections:

```markdown
# Action Proposal

## Reason

Human-readable reason, or `Not provided.`

## Parameters

```json
{"description":"Test task"}
```
```

The parameter JSON shall use deterministic key ordering and compact JSON-compatible values.

### PR-014 — No executable interpretation

Markdown prose shall never be interpreted as executable input.

Only validated structured fields and the fenced JSON parameter object shall reconstruct the proposal.

### PR-015 — Secret handling

Proposal documents may contain sensitive action parameters.

The repository shall not redact or transform fields silently.

Operators shall protect the proposal directory with least-privilege filesystem permissions.

## 8. Filename and identifier safety

### PR-016 — Canonical UUID filename

Only canonical lower-case proposal UUIDs accepted by the existing action contract may be used.

### PR-017 — No path traversal

The repository shall derive filenames from validated identifiers and shall reject:

- path separators;
- `.` or `..`;
- absolute paths;
- alternate filename suffixes;
- embedded null bytes;
- non-canonical UUID text.

Caller input shall never be concatenated into an unchecked path.

## 9. Public contracts

The initial implementation shall provide immutable, slotted contracts resembling:

```text
ProposalRepositoryIssue
ProposalWriteResult
ProposalReadResult
ProposalListResult
ProposalVerificationResult
ProposalDocumentResult
```

Exact names may be refined while preserving the observable requirements.

### PR-018 — Issue contract

A repository issue shall contain:

- stable `code`;
- human-readable `message`;
- optional `proposal_id`;
- optional `path`;
- optional physical line number;
- optional field name.

### PR-019 — Result consistency

Successful results shall contain the expected record and no failure issues.

Failed results shall contain at least one structured issue and no misleading successful record.

## 10. Repository interface

The repository shall provide operations equivalent to:

```python
create(proposal)
read(proposal_id)
list_all()
verify()
```

It shall not expose:

```text
update
replace
delete
truncate
clear
```

## 11. Atomic creation

### PR-020 — Exclusive creation

Creating a proposal whose canonical document already exists shall fail with a stable duplicate code.

Existing content shall remain unchanged.

### PR-021 — Atomic publication

Creation shall write complete content to a temporary file in the same directory and atomically publish it to the canonical destination.

A partially written canonical document shall not be observable after ordinary write failure.

### PR-022 — Temporary-file cleanup

Temporary files shall be removed after handled failures where safe.

A cleanup failure shall be reported explicitly rather than hidden.

### PR-023 — Parent creation

Parent-directory creation shall be disabled by default.

An explicit constructor option may permit creation of the configured proposal directory.

### PR-024 — Filesystem synchronisation

Optional file and directory `fsync` behaviour may be supported through explicit configuration.

It shall be disabled by default unless a later accepted standard changes the durability policy.

## 12. Proposal retrieval

### PR-025 — Exact lookup

Retrieval shall load only the canonical file for the supplied validated proposal identifier.

### PR-026 — Missing proposal

A missing file shall return a structured `proposal_not_found` failure.

It shall not be represented as an empty repository result.

### PR-027 — Identity agreement

The `proposal_id` inside the document shall exactly match the identifier in the filename and lookup request.

Mismatch shall fail closed.

### PR-028 — Existing validation reuse

The parsed data shall be reconstructed through the existing `proposal_from_dict` boundary or an equivalent shared validator.

## 13. Deterministic listing

### PR-029 — Stable order

`list_all()` shall return proposals in one documented deterministic order.

The initial order shall be:

1. ascending `created_at`;
2. ascending `proposal_id` as a stable tie-breaker.

### PR-030 — File selection

Listing shall inspect canonical `*.md` proposal filenames only.

Unexpected files shall be reported by verification and shall not be silently interpreted as proposals.

### PR-031 — Malformed proposal during listing

The default listing operation shall fail closed when any canonical proposal document is malformed.

It shall not silently skip unreadable or invalid proposals.

## 14. Repository verification

### PR-032 — Read-only verification

Verification shall inspect repository structure and content without creating, modifying, renaming or deleting anything.

### PR-033 — Verification checks

Verification shall report at least:

- proposal directory existence;
- directory type and readability;
- unexpected files;
- non-canonical filenames;
- malformed front matter;
- unsupported schema version;
- missing and unknown fields;
- invalid parameter JSON;
- invalid proposal data;
- filename/document identifier mismatch;
- duplicate logical proposal identifiers;
- non-UTF-8 content;
- missing final newline;
- non-deterministic document rendering.

### PR-034 — Canonical re-render comparison

After parsing, verification shall deterministically re-render the proposal and compare it with the physical document.

Differences shall be reported as non-canonical content.

Verification shall not rewrite the file.

## 15. Failure codes

Stable codes shall distinguish at least:

- `proposal_directory_missing`;
- `proposal_directory_not_directory`;
- `proposal_directory_not_readable`;
- `proposal_directory_not_writable`;
- `proposal_not_found`;
- `proposal_already_exists`;
- `proposal_write_failed`;
- `proposal_read_failed`;
- `proposal_invalid_filename`;
- `proposal_malformed_document`;
- `proposal_unsupported_schema_version`;
- `proposal_missing_field`;
- `proposal_unknown_field`;
- `proposal_invalid_parameters`;
- `proposal_invalid_contract`;
- `proposal_identity_mismatch`;
- `proposal_non_canonical_document`;
- `proposal_unexpected_file`;
- `proposal_cleanup_failed`.

Names may be refined before acceptance, but each failure class shall remain distinguishable.

## 16. Orchestration integration

### PR-035 — Injected repository boundary

The orchestration service may receive a proposal repository through dependency injection.

No global repository singleton shall be introduced.

### PR-036 — Submission persistence point

When enabled, successful proposal submission shall persist the final proposal record produced by submission orchestration.

The exact persistence point and audit ordering shall be explicit and tested.

### PR-037 — Persistence failure visibility

Repository failure shall be returned as structured orchestration failure information.

It shall not be reported as successful persistence.

### PR-038 — No false rollback

If audit or another external side effect completed before proposal persistence failed, the result shall expose that partial completion.

The implementation shall not claim transactional rollback.

### PR-039 — No automatic execution

Loading a persisted approved proposal shall not execute it.

Execution remains restricted to the established approved-only execution boundary.

## 17. Audit relationship

Proposal documents and audit events serve different purposes:

- the proposal repository stores canonical proposal records;
- the audit trail stores ordered workflow evidence.

The proposal repository shall not replace the audit store.

Audit records shall continue to correlate through `proposal_id`.

Milestone 2.1 shall not duplicate the complete audit history inside proposal documents.

## 18. Concurrency

The initial repository assumes one writer process at a time.

It does not provide:

- cross-process locking;
- compare-and-swap updates;
- transactional multi-document writes;
- distributed coordination.

Atomic creation protects against partial publication but does not provide a complete concurrent-writer protocol.

## 19. Security considerations

The implementation shall:

- derive paths only from validated canonical identifiers;
- avoid shell command construction;
- avoid unsafe temporary directories;
- use exclusive creation;
- avoid following repository-relative fallbacks;
- avoid logging complete proposal parameters in generic error messages;
- avoid silently skipping malformed files;
- keep proposal data outside Git;
- document that proposal parameters may be sensitive.

## 20. Testing requirements

Automated tests shall cover at least:

- deterministic Markdown rendering;
- rendering with and without a reason;
- nested JSON-compatible parameters;
- round-trip proposal reconstruction;
- canonical filename generation;
- path traversal rejection;
- successful atomic creation;
- duplicate creation without overwrite;
- missing parent behaviour;
- explicit parent creation;
- simulated write failure;
- temporary-file cleanup;
- exact retrieval;
- missing proposal;
- filename/document identifier mismatch;
- malformed front matter;
- unknown and missing fields;
- malformed and non-object parameter JSON;
- invalid proposal fields;
- UTF-8 handling;
- final newline requirements;
- deterministic listing order;
- malformed listing failure;
- unexpected-file verification;
- non-canonical document verification;
- read-only verification;
- no current-working-directory dependency;
- immutable contracts;
- orchestration persistence success and failure;
- no implicit confirmation or execution;
- complete repository quality gate.

## 21. Documentation requirements

Completion documentation shall include:

- proposal repository location;
- canonical Markdown format;
- file permissions;
- creation, retrieval, listing and verification behaviour;
- duplicate and malformed-document handling;
- backup boundary;
- single-writer limitation;
- relationship to audit storage;
- known limitations.

## 22. Known limitations

Milestone 2.1 shall not provide:

- proposal deletion or replacement;
- concurrent writer locking;
- SQLite indexes;
- full-text search;
- encryption;
- signatures;
- remote replication;
- retention policy;
- archival;
- automatic backups;
- state-history projection;
- domain-tool integration;
- user-facing proposal browser.
