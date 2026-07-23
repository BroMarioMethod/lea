# LEA-SPEC-0014: Markdown Knowledge Repository

- **Status:** Accepted
- **Version:** 1.0
- **Date:** 23 July 2026
- **Milestone:** 2.4 — Knowledge and Markdown persistence
- **Related specifications:**
  - `LEA-SPEC-0002_ACTION_PROPOSAL_CONTRACT.md`
  - `LEA-SPEC-0006_ACTION_AUDIT_TRAIL.md`
  - `LEA-SPEC-0007_AUDIT_INTEGRITY_VERIFICATION.md`
  - `LEA-SPEC-0009_RUNTIME_LAYOUT_CONFIGURATION.md`
  - `LEA-SPEC-0010_PERSISTENT_PROPOSAL_REPOSITORY.md`
  - `LEA-SPEC-0013_LOCAL_COMMAND_LINE_INTERFACE.md`

## 1. Purpose

This specification defines LEA's canonical Markdown knowledge repository.

The repository provides durable, human-readable knowledge documents that users
and authorised local AI components can inspect through the same canonical
source. LEA may build disposable indexes and other derived views from these
documents, but canonical knowledge remains stored in Markdown.

Markdown is the unified bridge between human knowledge work and LEA's later
agent and local-model capabilities. Humans must be able to read, edit and
organise the same knowledge that LEA uses for context, summarisation, planning
and deterministic proposal generation.

The repository is a deterministic persistence boundary. It is not a general
filesystem abstraction, an unrestricted note-taking application, a search
engine or an authority to execute actions.

## 2. Scope

Milestone 2.4 initially covers:

- stable knowledge-document identifiers;
- canonical document types;
- deterministic YAML-style front matter;
- preserved user-authored Markdown bodies;
- strict parsing and validation;
- deterministic paths and filenames;
- atomic document creation and replacement;
- explicit expected-version conflict handling;
- stable links between knowledge documents;
- optional links to existing task, proposal and audit identifiers;
- document sensitivity classification;
- role and context documents for human–AI collaboration;
- read, list and filtered-query repository operations;
- deterministic context-selection boundaries for later local-model use;
- disposable search-index boundaries;
- backup, restore and import/export requirements.

Initial canonical document types are:

```text
note
person
organisation
project
decision
role
```

The initial milestone does not define natural-language interpretation, semantic
search, embeddings, remote synchronisation, multi-user editing, collaborative
locking or automatic conflict merging.

## 3. Design principles

The knowledge repository must:

- keep canonical knowledge human-readable;
- make Markdown the shared source of truth for humans and authorised AI;
- allow documents to be inspected and edited without LEA;
- preserve stable identifiers after renaming or moving files;
- separate document identity from filesystem paths;
- use deterministic serialisation for LEA-authored metadata;
- preserve user-authored Markdown body content;
- reject malformed documents visibly;
- never silently discard unknown metadata;
- use atomic file replacement for canonical writes;
- reject stale replacements through explicit expected-version checks;
- keep derived indexes disposable and reproducible;
- use stable identifiers for links between documents;
- expose sensitivity before knowledge is selected for AI context;
- prevent sensitivity labels from being treated as execution permissions;
- record transparent audit events for knowledge operations and failures;
- avoid hidden network access;
- remain suitable for Raspberry Pi 4B hardware;
- use UK English and UTF-8.

## 4. Terminology

### 4.1 Knowledge document

A UTF-8 Markdown file containing:

1. canonical YAML-style front matter; and
2. a Markdown body.

### 4.2 Canonical document

The Markdown file that is the durable source of truth for one knowledge item.

### 4.3 Document identifier

A stable UUID identifying the logical document independently of its path,
filename, title or document type.

### 4.4 Document version

A monotonically increasing positive integer used for optimistic conflict
detection.

### 4.5 Document type

A stable classification determining required metadata and validation rules.

### 4.6 Document link

A typed reference from one knowledge document to another stable document
identifier.

### 4.7 External reference

A typed reference to an identifier owned by another LEA subsystem or external
provider, such as a Taskwarrior UUID, proposal identifier or audit event
identifier.

### 4.8 Derived index

A disposable database or search structure built entirely from canonical
Markdown documents.

### 4.9 Sensitivity

A document metadata classification describing how carefully its content must be
handled. Sensitivity is distinct from action risk, confirmation policy and file
permissions.

### 4.10 Role document

A knowledge document that provides durable context, responsibilities,
terminology, boundaries and working practices for a named human or AI-assisted
role.

A role document does not grant capabilities and cannot bypass validation,
approval, permissions, execution or audit.

## 5. Repository layout

The runtime configuration shall provide one explicit knowledge-root directory.

A recommended layout is:

```text
<knowledge-root>/
├── notes/
├── people/
├── organisations/
├── projects/
├── decisions/
├── attachments/
└── .index/
```

The `.index/` directory is derived state and must not contain canonical
knowledge.

The repository must not assume that a document's current directory or filename
is its identity.

## 6. Stable document identifiers

### KD-001 — Identifier format

Every knowledge document shall have one stable UUID identifier.

The initial canonical textual form shall be a lowercase hyphenated UUID:

```text
123e4567-e89b-42d3-a456-426614174000
```

The initial implementation should generate UUID version 4 identifiers unless a
later accepted specification defines another generation strategy.

### KD-002 — Stability

The identifier shall remain unchanged when:

- the title changes;
- the filename changes;
- the document moves between directories;
- links are added or removed;
- the body changes;
- the document version increases.

### KD-003 — Uniqueness

Two canonical documents in one repository must not share an identifier.

Duplicate identifiers shall be reported as repository integrity failures.

### KD-004 — Identifier validation

Identifiers shall be validated strictly. Invalid or non-canonical UUID text
shall not be silently normalised during parsing.

### KD-005 — Identifier ownership

The repository owns knowledge-document identifiers.

Taskwarrior UUIDs, proposal identifiers and audit event identifiers remain
owned by their existing subsystems and shall appear only as external
references.

## 7. Document types

The initial supported document types are:

```text
note
person
organisation
project
decision
```

Each type shall have a stable lowercase identifier.

Unknown document types shall fail validation unless an explicit extension
contract later permits them.

### 7.1 Note

A general-purpose knowledge record.

Required metadata:

- identifier;
- schema version;
- document type;
- document version;
- title;
- created timestamp;
- updated timestamp.

### 7.2 Person

A record about one person.

The initial contract shall not require contact details. Contact synchronisation
with khard and vdirsyncer remains a later integration.

### 7.3 Organisation

A record about one organisation, business, institution or group.

### 7.4 Project

A knowledge record describing one project.

This is distinct from a Taskwarrior project string, although an external
reference may link them.

### 7.5 Decision

A record of one decision and its context.

The Markdown body should support rationale, alternatives and consequences
without requiring a rigid body template in the initial slice.

### 7.6 Role

A reusable context document describing one working role.

Examples include:

```text
accounts_manager
project_manager
task_manager
relationship_manager
```

Role documents may guide later local-model context assembly, summarisation and
proposal generation. They shall not contain executable instructions that bypass
LEA's deterministic boundaries, and selecting a role shall not grant any
permission or capability.

## 8. Canonical front matter

Every document shall begin at byte zero with deterministic YAML-style front
matter.

The delimiter shall be:

```text
---
```

The document shall contain one closing delimiter before the Markdown body.

The initial canonical field order is:

```yaml
---
schema_version: 1
document_id: 123e4567-e89b-42d3-a456-426614174000
document_type: note
document_version: 1
title: Example title
sensitivity: low
created_at: 2026-07-23T08:00:00Z
updated_at: 2026-07-23T08:00:00Z
links: []
external_references: []
---
```

### KD-006 — Required fields

The initial required fields are:

```text
schema_version
document_id
document_type
document_version
title
sensitivity
created_at
updated_at
links
external_references
```

### KD-007 — Field order

LEA-authored serialisation shall use the canonical field order.

Parsing shall not depend on field order unless the chosen strict parser
requires a later accepted constraint.

### KD-008 — Unknown fields

Unknown front-matter fields shall not be silently discarded.

The initial parser shall report them as structured validation issues.

### KD-009 — Duplicate fields

Duplicate front-matter keys shall be rejected.

### KD-010 — Scalar rules

Scalar values shall use deterministic UTF-8 text.

Titles shall be non-empty after validation but shall not be trimmed or rewritten
silently during parsing.

### KD-011 — Collections

`links` and `external_references` shall be explicit collections.

Missing collections shall not be treated as implicit empty collections.

### KD-012 — Timestamps

Canonical stored timestamps shall use UTC and RFC 3339-compatible text with a
`Z` suffix.

Displayed timestamps may be localised by interfaces, but canonical documents
remain in UTC.


### KD-012A — Sensitivity values

The initial canonical sensitivity values are:

```text
low
medium
critical
```

They mean:

- `low`: routine knowledge suitable for normal authorised local retrieval;
- `medium`: personal, commercial or operational knowledge requiring deliberate
  handling and restricted context selection;
- `critical`: highly sensitive knowledge excluded from automatic model context
  unless an explicit policy and authorised operation permit its use.

### KD-012B — Sensitivity is not permission

Sensitivity does not grant access, execution authority or confirmation
exemption.

A component must still hold the required read capability and pass the relevant
policy checks.

### KD-012C — Conservative handling

Unknown sensitivity values shall fail validation.

Missing sensitivity shall not default silently. Every canonical document must
state its classification.

### KD-012D — Derived copies

Indexes, summaries, caches, diagnostic bundles and model-context records derived
from a document shall be handled at least as sensitively as their source.

Content derived from multiple documents shall inherit the highest source
sensitivity.

### KD-012E — Critical content

Critical document bodies shall not be written to ordinary logs, audit payloads
or diagnostic output.

Audit records may contain stable identifiers, versions, operation outcomes,
issue codes and content hashes where appropriate, but not the critical body.

## 9. Schema versions

### KD-013 — Schema version

`schema_version` identifies the document-format schema.

The initial schema version is:

```text
1
```

### KD-014 — Unsupported versions

Unsupported schema versions shall fail visibly.

The repository shall not rewrite unsupported documents.

### KD-015 — Migration

Schema migration is outside the first implementation slice.

A later migration contract must define:

- accepted source versions;
- deterministic transformations;
- backup requirements;
- rollback behaviour;
- failure recovery;
- audit requirements where appropriate.

## 10. Document versions and conflict handling

### KD-016 — Version format

`document_version` shall be a positive integer beginning at `1`.

### KD-017 — Version increments

Every successful canonical replacement shall increase the document version by
exactly one.

Creation shall persist version `1`.

### KD-018 — Expected-version replacement

Replacement shall require an `expected_version`.

The repository shall:

1. read the current canonical document;
2. validate it;
3. compare its version with `expected_version`;
4. reject the replacement if they differ;
5. write the new version atomically only when they match.

### KD-019 — Conflict result

A stale update shall produce a structured conflict issue and shall not modify
the canonical file.

The issue shall identify:

- document identifier;
- expected version;
- actual version.

### KD-020 — No automatic merge

The initial repository shall not merge competing edits automatically.

## 11. Markdown body handling

### KD-021 — Body preservation

The Markdown body is user-authored content.

Parsing and serialisation shall preserve it without semantic rewriting.

### KD-022 — Boundary

The body begins immediately after the closing front-matter delimiter and its
required line ending.

### KD-023 — Line endings

Canonical LEA-authored documents shall use LF line endings.

The parser may detect other line endings, but the initial behaviour must be
explicitly tested and must not silently corrupt body content.

### KD-024 — Trailing newline

Canonical LEA-authored documents shall end with exactly one trailing newline.

### KD-025 — Empty body

An empty Markdown body is permitted unless a document-type contract later
requires content.

### KD-026 — Markdown freedom

The repository shall not impose heading levels, paragraph templates or body
section names in the initial milestone.

## 12. Deterministic filenames and paths

### KD-027 — Filename identity separation

A filename shall not be the source of document identity.

### KD-028 — Initial filename convention

The initial deterministic filename convention shall be:

```text
<slug>--<document-id>.md
```

Example:

```text
boiler-efficiency-review--123e4567-e89b-42d3-a456-426614174000.md
```

### KD-029 — Slug purpose

The slug exists for human readability only.

The identifier suffix is authoritative.

### KD-030 — Slug generation

LEA-authored slug generation shall be deterministic from the title.

The initial rules shall be implemented and tested separately, including:

- lowercase output;
- ASCII hyphen separators;
- collapsed repeated separators;
- no leading or trailing separator;
- a deterministic fallback when no usable slug remains;
- a documented maximum length.

### KD-031 — Type directory

LEA-authored documents shall be stored in the canonical directory for their
document type.

### KD-032 — Rename and move

Renaming or moving a document shall not change its identifier.

A later CLI may perform renames, but repository reads must remain based on
validated document content rather than trusting paths alone.

### KD-033 — Filename mismatch

A filename whose identifier suffix differs from the front matter shall fail
repository validation.

## 13. Document links

### KD-034 — Stable target

Knowledge-document links shall target `document_id`, not a relative path.

### KD-035 — Link shape

The initial canonical logical shape is:

```yaml
links:
  - relation: related
    document_id: 123e4567-e89b-42d3-a456-426614174000
```

### KD-036 — Link relation

The initial implementation shall define a small stable set of relation
identifiers or explicitly accept validated namespaced relations.

The exact relation vocabulary must be accepted before implementation.

### KD-037 — Missing targets

A document may be parsed even when a link target is missing, but repository
integrity inspection shall report unresolved links.

### KD-038 — Self-links

Self-links shall be rejected unless a later relation contract explicitly
permits them.

### KD-039 — Duplicate links

Duplicate links with the same relation and target shall be rejected.

## 14. External references

The initial supported reference namespaces are:

```text
taskwarrior.task
lea.proposal
lea.audit_event
```

The canonical logical shape is:

```yaml
external_references:
  - namespace: taskwarrior.task
    identifier: 22222222-2222-4222-8222-222222222222
```

### KD-040 — Namespace ownership

The knowledge repository shall validate reference syntax but shall not assume
ownership of the referenced record.

### KD-041 — Missing external targets

Missing external targets shall not make the Markdown document unparsable.

Integrity or health inspection may report them separately.

### KD-042 — No embedded secrets

External references shall not contain secrets, tokens, passwords or private
credentials.

## 15. Repository contract

The initial repository boundary shall support:

```text
create(document)
read(document_id)
list(query)
replace(document, expected_version)
inspect()
```

A later slice may add:

```text
move(document_id, destination)
delete(document_id, expected_version)
```

Deletion is deliberately excluded from the first implementation because
retention, backlink and recovery behaviour must be specified first.

### KD-043 — Create

Creation shall:

- validate the document;
- require version `1`;
- reject duplicate identifiers;
- reject an occupied canonical destination;
- serialise deterministically;
- write atomically;
- read back and verify the persisted document.

### KD-044 — Read

Reading by identifier shall:

- locate exactly one matching canonical document;
- parse and validate it;
- reject duplicate identifiers;
- return structured not-found and malformed-document issues.

### KD-045 — List

Listing shall use deterministic ordering.

The initial ordering shall be specified before implementation. The recommended
ordering is:

```text
document_type, title, document_id
```

### KD-046 — Filtered query

The initial query contract may filter by:

- document type;
- exact document identifier;
- exact link target;
- exact external-reference namespace and identifier;
- exact sensitivity;
- exact role identifier where applicable.

Full-text search belongs to the derived index.

### KD-047 — Replace

Replacement shall:

- require the same document identifier;
- require the current expected version;
- require a new version exactly one greater;
- preserve `created_at`;
- set or validate `updated_at`;
- validate the complete replacement document;
- write atomically;
- read back and verify the persisted document.

### KD-048 — Inspect

Inspection shall report:

- repository availability;
- malformed files;
- duplicate identifiers;
- filename/front-matter mismatches;
- unsupported schema versions;
- unresolved knowledge links;
- index availability where applicable.

## 16. Atomic writes

### KD-049 — Temporary file

Canonical writes shall use a temporary file in the destination directory.

### KD-050 — Flush and synchronisation

The implementation shall support:

- file flush;
- optional file `fsync`;
- atomic `os.replace`;
- optional parent-directory `fsync`.

The exact durability mode shall be configurable or explicitly documented.

### KD-051 — Permissions

Temporary and final files shall use deliberate permissions appropriate to the
runtime profile.

### KD-052 — Cleanup

Failed writes shall attempt to remove temporary files.

Cleanup failure shall be reported without hiding the primary write failure.

### KD-053 — Read-back verification

After replacement, the repository shall read and compare the canonical
document.

### KD-054 — Atomicity limitation

Filesystem replacement prevents partially written canonical files but does not
provide full compare-and-swap semantics across independent processes.

Cross-process locking remains future work.

## 17. Strict parsing and validation

Parsing shall distinguish:

- filesystem read failure;
- missing opening delimiter;
- missing closing delimiter;
- malformed front matter;
- duplicate keys;
- unknown keys;
- missing required fields;
- invalid scalar values;
- invalid identifiers;
- unsupported schema versions;
- invalid document versions;
- invalid timestamps;
- invalid link structures;
- invalid external references;
- filename/front-matter mismatch;
- invalid UTF-8.

### KD-055 — Structured issues

Every failure shall use stable issue codes and human-readable messages.

Issues should include a field name and path where practical.

### KD-056 — No silent repair

Parsing shall not rewrite, repair or normalise malformed canonical documents.

### KD-057 — Partial repository health

One malformed document shall not prevent inspection of unrelated valid
documents, but the repository shall report degraded health.

Operations targeting the malformed document shall fail.

## 18. Disposable search index

### KD-058 — Derived status

The search index is derived state.

It shall not be required to reconstruct canonical knowledge.

### KD-059 — Rebuild

LEA shall be able to delete and rebuild the complete index from canonical
Markdown.

### KD-060 — Index content

The initial index may contain:

- document identifier;
- document type;
- title;
- canonical path;
- document version;
- updated timestamp;
- body text;
- link targets;
- external references.

### KD-061 — Index technology

The specific index technology is outside this first specification version.

SQLite full-text search is a permitted candidate if it remains disposable and
suitable for Raspberry Pi hardware.

### KD-062 — Staleness

Index staleness shall be detectable.

Canonical reads must not trust index content over Markdown.

### KD-063 — Failure tolerance

Index corruption or absence shall not make canonical documents unreadable.

## 19. Attachments and external files

Attachments are outside the first implementation slice.

Before attachment writes are implemented, a later contract must define:

- stable attachment identifiers;
- content hashing;
- filename handling;
- permitted paths;
- replacement and deletion;
- backlink behaviour;
- backup inclusion;
- size limits;
- MIME-type handling;
- security scanning limitations.

Knowledge documents may contain normal Markdown links, but LEA shall not
automatically fetch remote content.

## 20. Import, export, backup and restore

### KD-064 — Export

The canonical Markdown tree is itself the primary export format.

### KD-065 — Backup scope

Backups shall include:

- canonical Markdown documents;
- attachments once supported;
- configuration required to interpret repository paths;
- schema and version information.

Disposable indexes need not be backed up.

### KD-066 — Restore verification

Restore procedures shall verify:

- readable UTF-8;
- unique identifiers;
- schema support;
- filename/front-matter consistency;
- document versions;
- link integrity;
- repository inspection status.

### KD-067 — Import

Bulk import behaviour is deferred until duplicate, conflict and trust rules are
specified.

## 21. Security and privacy

Knowledge documents may contain personal, commercial or confidential
information.

The implementation shall:

- avoid logging full document bodies by default;
- avoid storing secrets in front matter;
- respect runtime directory permissions;
- avoid hidden network access;
- report path traversal attempts;
- prevent writes outside the configured knowledge root;
- treat symbolic links according to an explicit fail-closed policy;
- document backup sensitivity;
- keep derived indexes under the same privacy assumptions as canonical data.

## 22. Runtime integration

The runtime configuration shall expose explicit knowledge paths.

A recommended future configuration shape is:

```toml
[knowledge]
root = "/var/lib/lea/knowledge"
index = "/var/lib/lea/knowledge/.index/knowledge.sqlite3"
durability = "fsync"
```

Exact configuration fields shall be added through the runtime configuration
contract and tests.

Development and test profiles shall remain isolated from system data.

## 23. CLI integration

CLI knowledge commands are deferred until the repository contract is stable.

The likely initial read-only commands are:

```text
lea knowledge list
lea knowledge show <document-id>
lea knowledge inspect
```

Write commands require separate confirmation and conflict behaviour.

The CLI must not bypass repository validation or atomic writes.

## 24. Audit integration

The knowledge subsystem shall preserve transparent truth about operations
performed through LEA.

### KD-068 — Audited operations

Every LEA-mediated knowledge operation shall produce an audit attempt,
including:

- create;
- read;
- list or query;
- replace;
- inspect;
- index rebuild;
- context selection;
- validation failure;
- schema rejection;
- conflict rejection;
- path or permission rejection;
- serialisation or persistence failure.

High-volume read and query events may use a dedicated knowledge access log or
batched audit representation, but they must remain attributable and
integrity-verifiable. Optimisation must not silently remove the record of what
occurred.

### KD-069 — Failures are events

A failed operation is still an event.

Where a document cannot be parsed, the audit record should contain the known
path, operation, source, correlation identifier, stable issue codes and outcome.
It may contain a content hash when safely obtainable. It shall not copy an
untrusted or sensitive document body into the audit log.

### KD-070 — Direct external edits

LEA cannot record a manual filesystem edit at the instant it occurs when the
edit bypasses LEA.

The next repository read, inspection, index rebuild or filesystem-monitoring
event shall detect and record the observed change or validation failure. The
audit record must distinguish an observed external change from a LEA-authored
write.

### KD-071 — Audit failure

Failure to persist the audit event must be visible.

For read-only operations, the operation result shall report the audit failure.
For write operations, the ordering and partial-persistence behaviour must be
defined so that LEA never claims a fully audited write when the audit record was
not persisted.

### KD-072 — Audit payload minimisation

Audit records shall prefer:

- document identifier;
- document version;
- document type;
- sensitivity;
- operation;
- outcome;
- issue codes;
- actor or source;
- correlation identifier;
- timestamps;
- canonical content hash where appropriate.

Complete Markdown bodies shall not be copied into routine audit records.

## 25. AI context and human collaboration

The knowledge repository is the canonical bridge between human-authored
knowledge and LEA's later local-model and agent capabilities.

### KD-073 — Canonical context source

Later context assembly shall retrieve knowledge from canonical Markdown or from
a disposable index that can be traced back to canonical documents.

The model must not treat an index, summary or generated cache as more
authoritative than the source Markdown.

### KD-074 — Context provenance

Every selected context item shall retain provenance sufficient to identify:

- document identifier;
- document version;
- document type;
- sensitivity;
- canonical path;
- retrieval or selection reason.

### KD-075 — Role selection

Role documents may be selected to change the context and working perspective
used for a task.

Role selection shall be explicit and auditable. It shall not change tool
permissions, confirmation policy or deterministic action boundaries.

### KD-076 — Summaries and generated knowledge

AI-generated summaries, extracted facts and captured information shall not
silently overwrite source documents.

They shall be:

- returned as transient output;
- proposed as a new knowledge document; or
- proposed as an explicit versioned replacement.

The human-visible provenance and source links must be retained.

### KD-077 — Knowledge capture action

A later tool or action may capture structured information and persist it as
Markdown knowledge.

That action must use the same validation, sensitivity, versioning, repository,
approval and audit boundaries as every other knowledge write.

### KD-078 — Prompt injection boundary

Markdown body content is data, not trusted system instruction.

Later model-context assembly must distinguish trusted LEA policy and role
configuration from untrusted or user-authored document content.

### KD-079 — Context limits

Context selection shall be bounded, deterministic where practical and suitable
for Raspberry Pi memory constraints.

The full knowledge tree shall not be inserted into model context without an
explicit bounded retrieval policy.

## 26. Error and issue codes

The initial implementation shall define stable codes for at least:

```text
knowledge_not_found
knowledge_duplicate_id
knowledge_invalid_id
knowledge_invalid_utf8
knowledge_front_matter_missing
knowledge_front_matter_unclosed
knowledge_front_matter_malformed
knowledge_front_matter_duplicate_key
knowledge_front_matter_unknown_key
knowledge_required_field_missing
knowledge_schema_unsupported
knowledge_document_type_invalid
knowledge_document_version_invalid
knowledge_sensitivity_invalid
knowledge_timestamp_invalid
knowledge_link_invalid
knowledge_external_reference_invalid
knowledge_filename_mismatch
knowledge_version_conflict
knowledge_atomic_write_failed
knowledge_readback_mismatch
knowledge_path_outside_root
knowledge_symlink_rejected
knowledge_index_unavailable
knowledge_repository_degraded
```

Exact issue structures shall follow LEA's established immutable issue-contract
patterns.

## 27. Testing requirements

The implementation shall include tests for:

- valid canonical serialisation;
- strict front-matter parsing;
- body preservation;
- empty body handling;
- UTF-8 content;
- canonical line endings;
- stable identifiers;
- invalid and duplicate identifiers;
- deterministic filenames;
- filename/front-matter mismatches;
- every initial document type;
- role document validation;
- unknown document types;
- all sensitivity values;
- missing and unknown sensitivity;
- sensitivity inheritance for derived records;
- schema-version rejection;
- document-version increments;
- expected-version conflicts;
- atomic create;
- atomic replace;
- interrupted writes;
- temporary-file cleanup;
- read-back mismatch;
- duplicate repository identifiers;
- deterministic list ordering;
- exact filters;
- links and unresolved targets;
- external references;
- audit records for successful and failed knowledge operations;
- observed external-edit reporting;
- audit payload redaction for critical documents;
- AI context provenance;
- role selection without permission escalation;
- generated summary provenance;
- path traversal prevention;
- symbolic-link rejection;
- disposable-index absence and rebuild;
- development/test runtime isolation;
- Raspberry Pi acceptance checks.

## 28. Initial implementation sequence

The recommended implementation order is:

1. immutable document identifiers, document types and sensitivity enums;
2. immutable base document and issue contracts;
3. canonical link and external-reference contracts;
4. deterministic serialisation;
5. strict front-matter parser;
6. filename and path rules;
7. repository create and read;
8. deterministic list and query;
9. guarded version replacement;
10. repository inspection;
11. runtime configuration integration;
12. disposable index contract;
13. AI context-selection and provenance contracts;
14. knowledge audit integration;
15. initial CLI inspection commands;
16. backup and restore documentation;
17. target-device acceptance checks.

## 29. Acceptance criteria

Milestone 2.4 is accepted when:

- canonical knowledge is stored as human-readable Markdown;
- each document has one stable identifier;
- identifiers survive renaming and moving;
- initial document types, including role documents, are implemented and
  validated;
- every document has an explicit sensitivity classification;
- front matter is deterministic and strict;
- Markdown bodies are preserved;
- creation and replacement are atomic;
- stale replacements fail with explicit version conflicts;
- duplicate identifiers are detected;
- links use stable identifiers;
- unresolved links are inspectable;
- external references do not transfer ownership;
- derived indexes can be deleted and rebuilt;
- malformed files fail visibly and are not silently rewritten;
- successful and failed LEA-mediated knowledge operations are transparently
  audited;
- direct external edits are detected and recorded when next observed;
- AI context retains source provenance and respects sensitivity;
- role selection cannot escalate permissions;
- writes cannot escape the configured knowledge root;
- repository and runtime tests pass;
- target-device acceptance checks pass;
- backup and restore behaviour is documented.

## 30. Known limitations

The initial milestone does not provide:

- full compare-and-swap transactions;
- cross-process write locking;
- automatic conflict merging;
- collaborative editing;
- remote synchronisation;
- semantic embeddings;
- natural-language search;
- attachment management;
- deletion and retention policy;
- automatic schema migration;
- cryptographic signatures for individual knowledge documents;
- multi-user access control;
- complete backlink repair;
- guaranteed validation of external-reference targets.

## 31. Accepted design decisions

The following decisions are accepted for implementation:

1. Document identifiers use UUID version 4 in canonical lowercase hyphenated
   form.
2. Initial immutable contracts use the `KnowledgeDocument`,
   `KnowledgeDocumentLink`, `KnowledgeExternalReference`,
   `KnowledgeRepositoryIssue`, `KnowledgeQuery` and
   `KnowledgeRepositoryInspection` names.
3. Core link relations use stable lowercase identifiers. Extension relations
   must be namespaced and validated.
4. Deterministic slugs use lowercase ASCII, hyphen separators and a maximum of
   80 characters before the identifier suffix.
5. List ordering is document type, Unicode-casefolded title, then document
   identifier.
6. Runtime configuration uses explicit knowledge root, index path and durability
   settings.
7. Symbolic links are rejected and never followed by repository operations or
   inspection.
8. Unknown front-matter fields fail validation. Extensions require a later
   explicit schema.
9. Repository creation and replacement assign canonical timestamps through an
   injected UTC clock.
10. Sensitivity values are exactly `low`, `medium` and `critical`.
11. Every LEA-mediated knowledge operation, including failures, creates an
    attributable audit attempt without copying complete bodies.
12. Role documents are part of the initial document-type contract and influence
    context only, never permissions.
13. SQLite is the preferred disposable index technology. The exact FTS schema
    is accepted in the dedicated index slice after target-runtime capability
    inspection.
14. Explicit move and rename support remains inside Milestone 2.4 but follows
    the base repository create/read/list/replace slice.
15. Deletion remains deferred until retention, backlink and recovery behaviour
    is specified.
