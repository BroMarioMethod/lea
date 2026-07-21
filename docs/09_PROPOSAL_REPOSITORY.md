# Persistent Proposal Repository

## Purpose

LEA stores validated action proposals as canonical Markdown documents beneath the configured runtime proposal directory.

The proposal repository preserves intent. It does not approve, confirm, execute, or otherwise grant authority to an action.

## Runtime location

The repository uses:

```python
runtime_config.paths.proposal_dir
```

Canonical system layout:

```text
/var/lib/lea/proposals/
```

Canonical proposal path:

```text
<proposal_dir>/<proposal_id>.md
```

Example:

```text
/var/lib/lea/proposals/4b10f26d-0c54-4f3d-a14c-bce8a743116f.md
```

The proposal identifier must be a canonical lower-case UUID.

## Canonical source of truth

Each proposal has one canonical UTF-8 Markdown document.

No SQLite database, index, cache, or hidden metadata is required to reconstruct proposals. Future indexes must remain disposable or reproducible from the Markdown documents.

Documents use:

- UTF-8 encoding;
- LF line endings;
- exactly one final newline;
- deterministic field ordering;
- compact, key-sorted JSON parameters;
- deterministic re-render verification.

## Document structure

Each proposal document contains:

1. deterministic front matter;
2. a human-readable title;
3. a human-readable reason;
4. a fenced JSON parameter object.

Example:

```markdown
---
schema_version: 1
proposal_id: 4b10f26d-0c54-4f3d-a14c-bce8a743116f
action: task.create
status: proposed
risk_level: medium
confirmation_policy: when_required
source: "user"
created_at: 2026-07-21T12:00:00+00:00
---

# Action Proposal

## Reason

Create a test task.

## Parameters

```json
{"description":"Test task"}
```
```

Multiline reasons and ambiguous literal text such as `Not provided.` are preserved losslessly while remaining visible to a human reader.

## Repository operations

The public repository supports four operations.

### Create

```python
result = repository.create(proposal)
```

Creation:

- validates the canonical destination path;
- renders the complete deterministic document before publication;
- writes a temporary file in the repository directory;
- publishes exclusively without overwriting an existing proposal;
- optionally synchronises the file and directory when `fsync=True`;
- returns a structured result.

Duplicate creation fails with `proposal_already_exists`. Existing content remains unchanged.

Parent-directory creation is disabled by default. Runtime bootstrap owns creation of the configured proposal directory.

### Read

```python
result = repository.read(proposal_id)
```

Exact retrieval:

- validates the identifier;
- reads only the canonical filename;
- requires UTF-8;
- parses the strict Markdown structure;
- reuses the existing action proposal contract;
- verifies that the filename and document identifiers agree;
- compares the original document with a canonical re-render.

A missing proposal returns `proposal_not_found`.

Reading never creates or repairs files.

### List

```python
result = repository.list_all()
```

Listing returns all canonical proposal documents ordered by:

1. ascending `created_at`;
2. ascending `proposal_id`.

Listing fails closed when a canonical proposal document is malformed. It never silently skips invalid proposal documents or returns partial success.

### Verify

```python
result = repository.verify()
```

Verification is strictly read-only.

It reports:

- missing or invalid repository roots;
- malformed and non-canonical documents;
- invalid Markdown filenames;
- filename/document identity mismatches;
- non-UTF-8 content;
- unexpected files and directories;
- symbolic links;
- leftover temporary files.

Verification never creates, removes, renames, rewrites, or repairs repository entries.

## Runtime integration

Use the runtime integration helper:

```python
from lea.runtime import runtime_proposal_repository

repository = runtime_proposal_repository(runtime_config)
```

The helper accepts either `RuntimeConfig` or `RuntimePaths`.

It uses the configured `proposal_dir` and does not bootstrap the runtime implicitly.

Typical sequence:

```python
from lea.runtime import (
    bootstrap_runtime,
    isolated_test_runtime_paths,
    runtime_proposal_repository,
)

paths = isolated_test_runtime_paths(root)
bootstrap_result = bootstrap_runtime(paths)

if bootstrap_result.success:
    repository = runtime_proposal_repository(paths)
```

## Backup and restore

The complete proposal backup boundary is the proposal directory and its canonical Markdown files.

A basic offline backup may copy:

```text
<proposal_dir>/
```

To restore:

1. bootstrap or prepare the destination runtime;
2. stop LEA writers;
3. copy the canonical proposal directory into the destination;
4. construct the repository from the destination runtime;
5. run repository verification;
6. list and inspect restored proposals before resuming writes.

A restored repository requires no database or index files.

Verification detects corruption, identity mismatches, unexpected artefacts, and leftover temporary files after restoration.

Automatic backup and restore commands are not part of Milestone 2.1.

## Filesystem permissions

Proposal parameters may contain sensitive operational or personal information.

The proposal directory should:

- be owned by the LEA service account;
- use least-privilege permissions;
- not be readable by unrelated users;
- remain outside the Git repository;
- be included in protected backups;
- not be exposed through a web server.

Milestone 2.1 does not provide encryption at rest or automatic redaction.

## Relationship to the audit store

The proposal repository and audit store are separate persistence boundaries.

The proposal repository stores canonical proposal records.

The audit store records ordered workflow evidence.

Both correlate through `proposal_id`, but neither replaces the other.

A valid proposal document does not prove that an action was approved or executed. An audit event does not replace the canonical proposal record.

## Failure handling

Repository failures are represented by immutable structured issues.

Important codes include:

```text
proposal_directory_missing
proposal_directory_not_directory
proposal_not_found
proposal_already_exists
proposal_write_failed
proposal_read_failed
proposal_invalid_filename
proposal_malformed_document
proposal_unsupported_schema_version
proposal_missing_field
proposal_unknown_field
proposal_invalid_parameters
proposal_invalid_contract
proposal_identity_mismatch
proposal_non_canonical_document
proposal_unexpected_file
proposal_unexpected_entry
proposal_symbolic_link
proposal_temporary_file
```

Generic failure messages do not expose complete proposal parameters.

## Concurrency and crash behaviour

The initial repository assumes one writer process at a time.

Atomic exclusive publication prevents ordinary partial canonical writes and prevents overwrite races at the final destination.

Milestone 2.1 does not provide:

- cross-process writer locking;
- transactional multi-document operations;
- compare-and-swap updates;
- distributed coordination;
- automatic temporary-file cleanup after process termination.

Verification exposes leftover temporary files instead of repairing them silently.

## Known limitations

Milestone 2.1 does not provide:

- update, replace, or delete operations;
- proposal-state history inside documents;
- automatic reconciliation with the audit trail;
- resumable incomplete actions;
- SQLite indexes;
- full-text search;
- encryption;
- signatures;
- remote replication;
- retention or archival policy;
- automatic backup;
- a user-facing proposal browser;
- Taskwarrior or other domain-tool integration.

## Development verification

Run focused proposal tests:

```bash
uv run pytest \
    tests/test_proposal_documents.py \
    tests/test_proposal_document_reason_edges.py \
    tests/test_proposal_repository_create.py \
    tests/test_proposal_repository_read.py \
    tests/test_proposal_repository_list.py \
    tests/test_proposal_repository_verification.py \
    tests/test_proposal_repository_restore.py \
    tests/test_runtime_proposal_repository.py
```

Run the complete project gate:

```bash
scripts/check.sh
```
