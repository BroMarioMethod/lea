license: AGPL-3.0-only
---
id: LEA-SPEC-0011
title: Task Provider and Taskwarrior CLI Adapter Specification
version: 0.2.0
status: Accepted
review_required: false
---

# Task Provider and Taskwarrior CLI Adapter Specification

## Status

| Item | Value |
|---|---|
| Status | Accepted |
| Requires Review | No |
| Implementation | Not Started |
| Test Status | Taskwarrior 3.4.2 environment verified manually |

## 1. Purpose

This specification defines LEA's generic task-provider boundary and its first deterministic implementation using Taskwarrior 3.

The initial provider shall invoke a LEA-managed Taskwarrior 3 executable, use TaskChampion-backed storage through the Taskwarrior CLI, parse structured results, and return immutable LEA-owned contracts.

The design shall preserve LEA's existing execution boundary:

- an action proposal grants no execution authority;
- only approved proposals may reach execution;
- the task provider performs deterministic tool invocation;
- Taskwarrior remains the task-system source of truth for the initial provider;
- audit persistence remains a separate evidence boundary;
- user-facing times are localised only for presentation.

## 2. Architecture

LEA shall define a provider-neutral task boundary:

```text
LEA task actions
        ↓
TaskProvider
        ↓
TaskwarriorCliProvider
        ↓
LEA-managed Taskwarrior 3 executable
        ↓
TaskChampion-backed storage
```

A future direct provider may use TaskChampion without changing LEA's action model:

```text
LEA task actions
        ↓
TaskProvider
        ↓
TaskChampionProvider
```

Milestone 2.2 shall implement `TaskwarriorCliProvider`.

## 3. Supported environment

The primary development and deployment baseline is:

```text
Taskwarrior: 3.4.2
Platform: Linux
Storage: TaskChampion SQLite
```

The verified LEA-managed executable path is:

```text
/opt/lea-tools/taskwarrior/3.4.2/bin/task
```

The verified isolated development environment uses:

```text
taskrc: /tmp/lea-taskwarrior-3/config/taskrc
data:   /tmp/lea-taskwarrior-3/data
home:   /tmp/lea-taskwarrior-3/home
```

The TaskChampion storage file is:

```text
taskchampion.sqlite3
```

Taskwarrior 2.6.2 may remain installed as a compatibility reference, but it is not the primary Milestone 2.2 target.

The implementation shall not depend on Taskwarrior's internal data-file format.

The adapter shall interact through the exact configured executable and documented CLI behaviour.

## 4. Plug-and-play installation goal

LEA shall not permanently require users to install Taskwarrior manually.

The installer architecture shall support:

1. a LEA-managed bundled Taskwarrior binary;
2. an installer-downloaded and verified Taskwarrior binary;
3. an explicitly selected compatible system Taskwarrior binary.

The default long-term user experience shall be:

```text
Install LEA
Select task provider
Provision selected provider
Run health checks
Use LEA
```

Milestone 2.2 may use the manually installed LEA-managed development binary while preserving this deployment boundary.

## 5. Scope

Milestone 2.2 shall provide:

- a provider-neutral `TaskProvider` boundary;
- immutable task-provider and Taskwarrior adapter contracts;
- a `TaskwarriorCliProvider` implementation;
- executable discovery and version inspection;
- safe subprocess invocation using argument sequences;
- explicit timeout handling;
- deterministic environment construction;
- isolated Taskwarrior configuration for tests;
- Taskwarrior JSON export parsing;
- task creation;
- task listing;
- task modification;
- task completion;
- safe task deletion semantics;
- structured adapter failures;
- orchestration registration for approved task proposals;
- audit-visible execution results;
- operator and developer documentation;
- automated unit, integration, and acceptance tests;
- basic performance measurements on the Raspberry Pi target.

## 6. Non-goals

Milestone 2.2 shall not provide:

- direct access to TaskChampion SQLite files;
- a direct TaskChampion provider;
- a custom Rust task engine;
- Taskserver synchronisation;
- recurring-task authoring;
- dependency graph management;
- contexts;
- hooks;
- custom user-defined attributes;
- interactive editing;
- annotations;
- bulk destructive operations;
- `purge`;
- shell pipelines;
- arbitrary raw Taskwarrior filters;
- calendar integration;
- Telegram or LAN messaging;
- a graphical task browser.

## 7. Engineering principles

### TW-001 — Provider-neutral task boundary

LEA task actions shall depend on `TaskProvider`, not on Taskwarrior-specific subprocess details.

### TW-002 — Taskwarrior is authoritative for the initial provider

Taskwarrior owns task persistence and task-domain validation for `TaskwarriorCliProvider`.

LEA shall not duplicate or modify Taskwarrior's internal database directly.

### TW-003 — No shell construction

Commands shall be invoked with an argument sequence and `shell=False`.

Proposal values shall never be interpolated into a shell command string.

### TW-004 — Explicit executable selection

The provider shall receive an exact executable path.

It shall not rely on whichever `task` binary appears first in `PATH`.

### TW-005 — Isolated execution context

The provider shall receive its executable, configuration file, data directory, home directory, timeout, and environment explicitly.

It shall not discover project-relative or current-working-directory fallbacks.

### TW-006 — Structured output where available

Task retrieval shall use Taskwarrior JSON export.

Human-oriented report output shall not be parsed when a structured alternative exists.

### TW-007 — Fail closed

Missing executables, unsupported versions, timeouts, malformed JSON, non-zero exits, ambiguous task selection, and contract violations shall produce structured failures.

### TW-008 — No implicit confirmation

The provider shall not prompt interactively.

Taskwarrior confirmation shall be disabled only inside the explicitly configured provider invocation, after LEA's approval boundary has authorised execution.

### TW-009 — Exact task identity

Operations on existing tasks shall use Taskwarrior UUIDs rather than mutable numeric IDs.

### TW-010 — No direct storage scanning

LEA shall not use `grep`, `sed`, `ripgrep`, or direct SQLite access to locate or mutate Taskwarrior tasks.

UUID lookup shall use Taskwarrior's supported CLI and JSON export behaviour.

### TW-011 — No hidden side effects

Every mutating command and its result shall be represented in LEA's execution and audit boundaries.

## 8. Provider interface

The provider-neutral interface shall expose operations equivalent to:

```text
inspect()
create_task(request)
list_tasks(query)
modify_task(request)
complete_task(task_uuid)
delete_task(task_uuid)
```

The provider boundary shall use LEA-owned immutable request and result contracts.

Taskwarrior-specific command arguments shall remain private to `TaskwarriorCliProvider`.

## 9. Adapter configuration

The Taskwarrior CLI provider shall use an immutable configuration resembling:

```text
TaskwarriorConfig
```

It shall contain at least:

- absolute executable path;
- absolute Taskwarrior configuration-file path;
- absolute data-directory path;
- absolute home-directory path;
- positive command timeout;
- supported-version policy;
- optional neutral working directory.

All paths shall be explicit `Path` values.

The provider shall not use the operator's default `~/.taskrc` or task data unless those paths are explicitly selected by trusted runtime configuration.

## 10. Process invocation

### TW-012 — Base invocation

Commands shall be assembled from an argument tuple equivalent to:

```text
<task executable>
rc:<taskrc>
rc.data.location:<data directory>
rc.confirmation:no
rc.verbose:nothing
<filter and command arguments>
```

The exact v3-compatible configuration syntax shall be covered by integration tests.

### TW-013 — Environment

The subprocess environment shall be explicitly derived.

Tests shall provide isolated `HOME`, configuration, and data locations.

Secret values shall not be injected into generic logs or issue messages.

### TW-014 — Working directory

The provider shall not depend on the process current working directory.

### TW-015 — Timeouts

Every Taskwarrior invocation shall have a finite timeout.

Timeout shall return a stable structured failure and shall not be reported as a normal non-zero command exit.

### TW-016 — Captured streams

Standard output and standard error shall be captured as UTF-8 text.

Invalid UTF-8 shall fail explicitly.

Raw streams may be retained for internal diagnostics but shall not be exposed indiscriminately to users or audit logs.

## 11. Availability and version inspection

The provider shall provide a read-only inspection operation equivalent to:

```text
inspect()
```

Inspection shall report:

- whether the executable exists and is executable;
- the Taskwarrior version;
- whether the version is supported;
- whether the configured taskrc exists and is usable;
- whether the configured data directory is accessible;
- whether isolated TaskChampion storage can be initialised.

The initial supported version policy shall accept Taskwarrior 3.4.x.

Other Taskwarrior 3.x versions may be accepted after explicit compatibility tests.

Taskwarrior 2.x shall not be accepted by the primary provider configuration unless a separate compatibility mode is added later.

## 12. Public contracts

The initial implementation shall provide immutable, slotted contracts resembling:

```text
TaskProviderIssue
TaskProviderInspectionResult
TaskRecord
TaskCreateRequest
TaskCreateResult
TaskListQuery
TaskListResult
TaskModifyRequest
TaskMutationResult
TaskwarriorCommandResult
TaskwarriorConfig
```

Exact names may be refined while preserving the observable requirements.

### TW-017 — Issue contract

A provider issue shall contain:

- stable code;
- human-readable message;
- optional provider name;
- optional operation;
- optional task UUID;
- optional field name;
- optional process return code.

### TW-018 — Result consistency

Successful results shall contain their expected value and no failure issues.

Failed results shall contain at least one issue and no misleading successful value.

### TW-019 — Immutable task projection

LEA shall expose a validated immutable task projection rather than raw untrusted JSON dictionaries.

The initial projection shall include at least:

- UUID;
- description;
- status;
- entry timestamp;
- modified timestamp when available;
- due timestamp when available;
- project when available;
- tags;
- priority when available.

Unknown Taskwarrior fields may be ignored initially, but known fields shall be validated strictly.

## 13. Timestamp handling

Taskwarrior export timestamps shall be parsed deterministically and normalised to aware UTC `datetime` values.

The provider shall not localise timestamps during persistence or core processing.

Local-time conversion remains a presentation-layer responsibility.

Malformed timestamps shall fail closed.

## 14. JSON export parsing

### TW-020 — Export command

Task listing and post-mutation retrieval shall use Taskwarrior JSON export.

### TW-021 — Top-level shape

The export payload shall be a JSON array.

Each item shall be a JSON object.

Any other top-level shape shall fail with a stable malformed-export code.

### TW-022 — Required fields

Each exported task shall contain a valid UUID, non-blank description, recognised status, and valid entry timestamp.

### TW-023 — Stable ordering

The provider shall apply its own deterministic ordering:

1. ascending entry timestamp;
2. ascending UUID as a stable tie-breaker.

### TW-024 — Empty export

An empty JSON array shall be a successful empty listing.

## 15. Supported LEA actions

The initial action names shall be:

```text
task.create
task.list
task.modify
task.complete
task.delete
```

No other `task.*` action shall be registered by this milestone.

## 16. Task creation

`task.create` shall require:

```text
description
```

The initial optional parameters may include:

```text
project
due
priority
tags
```

Each modification shall be a separate subprocess argument.

Tags shall use explicit `+tag` arguments.

Successful creation shall return the created task's canonical Taskwarrior UUID.

The implementation shall not rely solely on a human-readable success message.

A command exit that does not create exactly one identifiable task shall fail explicitly.

## 17. Task listing

`task.list` shall default to pending tasks.

The initial exact filters may include:

- UUID;
- status;
- project;
- tag.

Arbitrary raw Taskwarrior filter expressions shall not be accepted from proposals.

The provider shall not parse column-formatted terminal reports.

## 18. Task modification

`task.modify` shall require exactly one canonical Taskwarrior UUID.

The initial modifiable fields shall be limited to:

```text
description
project
due
priority
tags
```

A modification request with no actual field change shall fail before invoking Taskwarrior.

After a successful modify command, the provider shall export the exact UUID and return the resulting task projection.

## 19. Task completion

`task.complete` shall require exactly one canonical UUID.

The provider shall invoke Taskwarrior's `done` command non-interactively.

After success, it shall export the exact task and verify completed status.

An already-completed task shall produce a deterministic documented result.

## 20. Task deletion

`task.delete` is destructive and shall require the existing LEA confirmation and approval policy before execution.

Taskwarrior's own interactive confirmation shall be disabled only after LEA approval.

The provider shall never invoke `purge`.

Deletion shall target exactly one canonical UUID.

After deletion, the provider shall verify the expected deleted state or absence according to Taskwarrior 3.4.x behaviour.

## 21. Proposal mapping

Each supported LEA action shall have a deterministic parameter schema.

Raw Taskwarrior command fragments shall never be accepted as proposal parameters.

Prohibited proposal values include:

```text
raw_filter
raw_command
shell
arguments
taskrc_override
data_location_override
executable_override
home_override
```

Provider configuration is owned by trusted runtime configuration, not by action proposals.

## 22. Orchestration integration

Supported task handlers shall be registered explicitly with the existing action registry.

No import-time global registration shall occur.

The existing orchestration boundary shall reject non-approved proposals before a provider method is invoked.

Successful execution shall return structured provider values suitable for deterministic serialisation and audit recording.

If Taskwarrior mutates state but post-condition export or later audit persistence fails, LEA shall expose the partial completion and shall not claim rollback.

## 23. Audit relationship

Audit events shall record enough structured information to correlate:

- LEA proposal ID;
- LEA action name;
- provider name;
- Taskwarrior task UUID when available;
- execution success or failure;
- stable provider issue codes.

Audit records shall not contain entire sensitive task descriptions by default.

## 24. Performance acceptance

The provider shall be benchmarked on the Raspberry Pi 4B target.

Measurements shall include:

- cold CLI startup;
- exact UUID export;
- create plus post-condition export;
- list with approximately 100 tasks;
- list with approximately 1,000 tasks;
- list with approximately 10,000 tasks where practical.

The milestone does not require a premature optimisation target.

Measured results shall determine whether a direct `TaskChampionProvider` prototype is necessary.

A custom Rust task engine shall not be considered unless both the CLI provider and direct TaskChampion integration fail documented requirements.

## 25. Failure codes

Stable codes shall distinguish at least:

```text
task_provider_unavailable
task_provider_unsupported
task_provider_parameter_invalid
task_provider_task_not_found
task_provider_task_ambiguous
taskwarrior_executable_missing
taskwarrior_executable_not_executable
taskwarrior_unsupported_version
taskwarrior_configuration_invalid
taskwarrior_data_directory_missing
taskwarrior_data_directory_not_directory
taskwarrior_process_timeout
taskwarrior_process_failed
taskwarrior_output_invalid_utf8
taskwarrior_export_invalid_json
taskwarrior_export_invalid_shape
taskwarrior_task_invalid
taskwarrior_create_failed
taskwarrior_modify_failed
taskwarrior_complete_failed
taskwarrior_delete_failed
taskwarrior_postcondition_failed
```

Names may be refined before implementation while preserving distinguishable failure classes.

## 26. Security considerations

The implementation shall:

- use `shell=False`;
- use an exact trusted executable path;
- avoid executable lookup through proposal values;
- avoid raw Taskwarrior filters from proposals;
- validate UUIDs and modification values;
- apply finite timeouts;
- isolate automated tests from personal task data;
- avoid complete task descriptions in generic logs;
- never invoke `purge`;
- disable hooks during isolated tests;
- use least-privilege runtime directories;
- treat task descriptions and metadata as potentially sensitive;
- avoid direct TaskChampion database access.

## 27. Testing requirements

Automated tests shall cover at least:

- immutable provider contracts;
- invalid contract combinations;
- executable discovery;
- missing executable;
- supported and unsupported versions;
- exact argument construction;
- `shell=False`;
- explicit taskrc, data, and home paths;
- timeout handling;
- non-zero process exits;
- invalid UTF-8;
- valid empty JSON export;
- malformed JSON;
- invalid top-level JSON shape;
- invalid task records;
- timestamp parsing;
- deterministic task ordering;
- isolated task creation;
- created UUID retrieval;
- exact listing;
- exact modification;
- completion;
- deletion;
- no `purge`;
- no current-working-directory dependency;
- no access to the operator's personal Taskwarrior database;
- approved-only orchestration execution;
- audit-visible execution outcomes;
- partial-failure visibility;
- Taskwarrior 3.4.2 acceptance tests;
- complete repository quality gate.

## 28. Packaging requirements

Completion documentation shall describe:

- supported Taskwarrior versions;
- LEA-managed executable layout;
- installer-managed and bundled provider options;
- third-party licence notices;
- isolated runtime configuration;
- upgrade and rollback behaviour;
- health checks;
- failure diagnosis.

Taskwarrior packaging shall remain replaceable without changing the provider-neutral task API.

## 29. Known limitations

Milestone 2.2 shall not provide:

- a direct TaskChampion provider;
- a custom Rust task engine;
- Taskserver synchronisation;
- recurring tasks;
- dependencies;
- annotations;
- contexts;
- hooks;
- arbitrary custom attributes;
- arbitrary filters;
- interactive editing;
- bulk mutations;
- `purge`;
- automatic conflict resolution;
- transactionality across Taskwarrior and the audit store;
- calendar projection;
- user-facing natural-language task entry;
- complete cross-platform packaging.
