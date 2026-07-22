# LEA-SPEC-0013: Local Command-Line Interface

- **Status:** Accepted
- **Version:** 1.13
- **Date:** 22 July 2026
- **Milestone:** 2.3 — Local CLI
- **Related specifications:**
  - `LEA-SPEC-0008_ACTION_ORCHESTRATION_SERVICE.md`
  - `LEA-SPEC-0009_RUNTIME_LAYOUT_CONFIGURATION.md`
  - `LEA-SPEC-0010_PERSISTENT_PROPOSAL_REPOSITORY.md`
  - `LEA-SPEC-0011_TASK_PROVIDER_TASKWARRIOR_CLI.md`
  - `LEA-SPEC-0012_TASKWARRIOR_INSTALLER_CONTRACT.md`

## 1. Purpose

This specification defines LEA's first complete local user interface.

The Local CLI provides deterministic access to runtime inspection, task
operations, proposal review and proposal decisions without bypassing LEA's
existing provider, action, confirmation, orchestration, repository or audit
boundaries.

The CLI is an interface over LEA. It is not a second execution architecture.

## 2. Scope

Milestone 2.3 initially supports:

```text
lea status

lea task list
lea task create
lea task modify
lea task complete
lea task delete

lea proposal list
lea proposal show
lea proposal approve
lea proposal reject
lea proposal cancel
lea proposal execute
```

The existing runtime CLI remains available through:

```text
lea runtime ...
```

Model chat, natural-language interpretation, accounting, calendar, contacts,
email and remote interfaces are outside the first implementation scope.

## 3. Design principles

The Local CLI must:

- call existing LEA contracts and services;
- never read or modify provider storage directly;
- use explicit provider configuration;
- remain deterministic and independently testable;
- produce human-readable output by default;
- support deterministic JSON output;
- return stable exit codes;
- write normal output to standard output;
- write errors and diagnostics to standard error;
- localise displayed timestamps;
- store timestamps in their canonical existing format;
- require explicit confirmation where policy demands it;
- never infer approval from interactive terminal presence;
- preserve audit and proposal semantics;
- avoid hidden network access;
- remain reusable by later Telegram, LAN and PWA interfaces.

## 4. Command grammar

The canonical grammar is:

```text
lea [global-options] <command> [subcommand] [options]
```

Global options initially include:

```text
--json
--config <absolute-path>
--profile <system|development|test>
--no-colour
--help
--version
```

Global options must be accepted only in documented positions supported by the
chosen parser. Ambiguous ordering must not be silently interpreted.

## 5. Top-level commands

### 5.1 Status

```text
lea status
```

Displays:

- runtime configuration status;
- runtime path health;
- proposal repository availability;
- Taskwarrior provider availability;
- Taskwarrior version;
- relevant warnings and failures.

`status` must not modify runtime or provider state.

### 5.2 Runtime

```text
lea runtime ...
```

Delegates to the existing runtime CLI.

The existing runtime command behaviour and exit codes must remain compatible
unless a later specification explicitly changes them.

### 5.3 Task

```text
lea task <subcommand>
```

Task commands use `TaskProvider` and must never invoke Taskwarrior storage or
TaskChampion SQLite directly.

### 5.4 Proposal

```text
lea proposal <subcommand>
```

Proposal commands use the persistent proposal repository and orchestration
services.

## 6. Task commands

### 6.1 List

```text
lea task list
```

Supported initial filters:

```text
--uuid <uuid>
--status <pending|completed|deleted>
--project <project>
--tag <tag>
```

The initial slice supports one exact tag filter. Waiting semantics, multiple-tag
semantics and result limiting are deferred until their provider-neutral
contracts and deterministic ordering behaviour are specified.

Human-readable output uses a stable table or line-oriented layout.

JSON output returns one object containing:

```json
{
  "success": true,
  "tasks": [],
  "issues": []
}
```

An empty result is successful and is not a not-found error.

### 6.2 Create

```text
lea task create --description <text>
```

Optional fields:

```text
--project <project>
--priority <H|M|L>
--tag <tag>
```

`--tag` may be supplied more than once. The exact supported date grammar must
be deterministic and documented before `--due` is implemented.

The CLI must not silently reinterpret invalid dates.

Task creation must use the provider-neutral `TaskCreateRequest`.

### 6.3 Modify

```text
lea task modify <uuid>
```

Supported changes:

```text
--description <text>
--project <project>
--priority <H|M|L>
--add-tag <tag>
--remove-tag <tag>
```

At least one modification must be supplied.

Modification uses the provider-neutral `TaskModifyRequest`.

### 6.4 Complete

```text
lea task complete <uuid>
```

Completion targets one exact UUID.

### 6.5 Delete

```text
lea task delete <uuid>
```

Deletion targets one exact UUID.

The command must not provide Taskwarrior purge behaviour.

## 7. Proposal commands

### 7.1 List

```text
lea proposal list
```

Initial filters:

```text
--status <status>
--action-type <type>
--limit <positive-integer>
```

Results must be ordered deterministically.

The default ordering should be newest first when repository metadata supports
it unambiguously. Otherwise, the repository's canonical ordering is used and
documented.

### 7.2 Show

```text
lea proposal show <proposal-id>
```

Displays:

- stable proposal identifier;
- action type;
- status;
- risk level;
- confirmation policy;
- parameters;
- created timestamp;
- updated timestamp where available;
- execution or transition errors;
- repository verification state.

Timestamps shown to the user must be localised through LEA's runtime time
boundary.

JSON output preserves canonical timestamp values and must not replace them with
localised display strings unless the JSON contract explicitly includes both.

### 7.3 Approve

```text
lea proposal approve <proposal-id>
```

Approval must:

1. read and verify the exact proposal;
2. apply the existing confirmation decision contract;
3. persist the resulting proposal state;
4. emit the required audit events;
5. return the orchestration outcome.

Approval does not necessarily execute the proposal immediately unless the
existing orchestration contract explicitly performs execution as part of the
approved workflow.

The CLI must not duplicate transition or confirmation logic.

### 7.4 Reject

```text
lea proposal reject <proposal-id>
```

Optional:

```text
--reason <text>
```

Rejection must use the existing confirmation and orchestration contracts.

A reason may be required by policy in a later revision.

### 7.5 Cancel

```text
lea proposal cancel <proposal-id> --actor <name> [--reason <text>]
```

Cancellation must use the existing confirmation and orchestration contracts and must apply only to a proposal awaiting confirmation. It must not execute the underlying action. The cancellation decision and resulting proposal state must be audited and persisted.

### 7.6 Execute

```text
lea proposal execute <proposal-id>
```

Execution applies only to a proposal in the `approved` state.

The command must:

- load the configured provider through the shared provider-loading boundary;
- register the provider-neutral action handlers supported by the runtime;
- execute through `ActionOrchestrator`;
- persist the action-execution audit event;
- replace the canonical proposal document using `approved` as the expected
  existing status;
- persist successful actions as `succeeded`;
- persist handled action failures as `failed`;
- report partial persistence when the audit event was persisted but the
  proposal document could not be replaced.

Execution does not accept an actor argument. The approving actor and decision
were already recorded by `lea proposal approve`.

## 8. Direct task operations versus proposals

Milestone 2.3 may expose direct deterministic task-provider commands for local
administrative use.

The implementation must make the execution boundary explicit:

```text
direct task command
→ validated provider-neutral request
→ provider
→ structured result
```

Direct task commands must not be misrepresented as proposal-driven actions.

A later revision may add:

```text
--propose
```

to create an action proposal instead of executing directly.

Commands that require the proposal and approval path by policy must not offer a
direct bypass.

## 9. Human-readable output

Human-readable output must:

- use UK English;
- avoid raw Python representations;
- avoid exposing internal object addresses;
- use stable headings and field labels;
- display localised timestamps;
- display UUIDs and proposal IDs exactly;
- represent missing optional values consistently;
- remain readable in a narrow SSH terminal;
- avoid mandatory colour;
- avoid interactive pagers.

Tables must degrade gracefully when fields are long.

The initial implementation may use line-oriented records instead of complex
tables where that improves reliability.

## 10. JSON output

`--json` produces deterministic UTF-8 JSON.

Requirements:

- one top-level JSON object;
- sorted keys where existing LEA serialisation policy requires it;
- no NaN or infinite values;
- no human commentary outside the JSON document;
- no ANSI escape sequences;
- canonical identifiers and timestamps;
- structured issue objects;
- newline termination;
- standard error remains separate.

A successful command uses:

```json
{
  "success": true,
  "data": {},
  "issues": []
}
```

A failed command uses:

```json
{
  "success": false,
  "data": null,
  "issues": [
    {
      "code": "stable_error_code",
      "message": "Actionable error message."
    }
  ]
}
```

Command-specific contracts may expose a more specific field such as `tasks` or
`proposal`, provided the schema is documented and stable.

## 11. Timestamp policy

Stored timestamps remain canonical UTC where existing contracts require UTC.

Human-readable output must use:

```python
localise_utc_timestamp(...)
```

or the equivalent established runtime boundary.

JSON output initially preserves canonical UTC timestamps.

A future option may add an explicit display timezone, but implicit machine-local
timezone assumptions must not alter persisted data.

## 12. Confirmation and interaction

The CLI must support non-interactive operation.

Commands must never block waiting for input unless interactivity was explicitly
requested.

Initial policy:

```text
default: non-interactive
```

Where a command requires confirmation:

- return a structured confirmation-required result; or
- require an explicit decision option.

Potential future options:

```text
--approve
--reject
--yes
```

`--yes` must never override policy that requires recorded human confirmation.

Interactive prompts are deferred until their behaviour, timeout and
non-terminal handling are specified.

## 13. Configuration

The CLI loads LEA runtime configuration through existing runtime APIs.

It must not create hidden configuration files.

An explicit `--config` path must:

- be absolute;
- identify a supported configuration file;
- be validated through the runtime loader;
- fail closed on invalid content.

Profile selection must use existing runtime profiles.

`--config` selects one explicit configuration file. `--profile` is an
optional assertion against the profile declared by that file. When no
`--config` is supplied, only the system profile is valid and the CLI
uses `/etc/lea/lea.toml`. Development and test profiles require an
explicit `--config` path. The CLI must not search the working directory
or derive configuration paths from it.

Taskwarrior executable, taskrc, home and data paths must come from validated
configuration or an established provider factory. They must not be discovered
through `PATH`.

## 14. Dependency construction

CLI parsing, rendering and service construction must remain separate.

Recommended structure:

```text
src/lea/cli/
├── __init__.py
├── contracts.py
├── parser.py
├── dispatch.py
├── rendering.py
├── serialisation.py
├── services.py
├── status.py
├── task_commands.py
└── proposal_commands.py
```

`main.py` remains a thin top-level dispatcher.

The CLI should use dependency injection for:

- task provider;
- proposal repository;
- action orchestrator;
- clock or timestamp formatting where needed;
- output streams.

Tests must not require a real Taskwarrior executable except for explicit
integration tests.

## 15. Stable exit codes

The Local CLI reserves:

```text
0   success
1   command or application failure
2   command-line usage error
3   configuration error
4   not found
5   confirmation required
6   permission denied
7   conflict or invalid state transition
8   provider unavailable
9   validation failure
70  unexpected internal error
```

The existing top-level constants remain compatible:

```text
EXIT_SUCCESS = 0
EXIT_APPLICATION_ERROR = 1
EXIT_CONFIGURATION_ERROR = 2
EXIT_INTERNAL_ERROR = 70
```

Because the existing runtime CLI already uses `2` for parser errors and separate
runtime/configuration statuses, implementation must reconcile naming without
silently changing established behaviour.

The final code should define exit codes in one shared Local CLI contract module
and map existing boundaries deliberately.

A command may return only one process exit code, while detailed causes remain in
structured issues.

## 16. Error handling

Expected failures must not print tracebacks.

Unexpected failures:

- return exit code 70;
- write a concise message to standard error;
- use configured structured logging;
- avoid exposing secrets;
- preserve diagnostics in logs.

Parser errors return exit code 2.

Provider, repository and orchestration issues must be mapped rather than
discarded.

## 17. Help and discoverability

Every command and subcommand must support `--help`.

Help output must include:

- purpose;
- required arguments;
- options;
- default behaviour;
- destructive-operation warning where applicable;
- JSON availability;
- one concise example.

The root help must list `runtime`, `status`, `task` and `proposal`.

## 18. Security requirements

The CLI must:

- avoid `shell=True`;
- avoid provider discovery through `PATH`;
- validate identifiers and paths;
- avoid logging secrets or entire environments;
- preserve permission and approval boundaries;
- avoid direct storage access;
- avoid destructive defaults;
- never turn parse errors into executable requests;
- fail closed on invalid configuration;
- keep stdout machine-readable when `--json` is active.

## 19. Testing requirements

Automated tests must cover:

- root parser and help;
- every command grammar;
- global option handling;
- parser error exit status;
- human-readable output;
- deterministic JSON output;
- stdout and stderr separation;
- exit-code mapping;
- timestamp localisation;
- empty task and proposal lists;
- invalid UUID and proposal IDs;
- provider unavailable results;
- repository read and verification failures;
- confirmation-required outcomes;
- approve and reject orchestration;
- unexpected internal failures;
- dependency injection;
- no direct Taskwarrior storage access;
- compatibility of the existing `lea runtime` path.

Real Taskwarrior integration tests should cover selected task CLI commands using
isolated state.

## 20. Documentation requirements

Milestone documentation must include:

- command reference;
- examples;
- JSON schemas or examples;
- exit-code table;
- configuration examples;
- confirmation behaviour;
- troubleshooting;
- distinction between direct task commands and proposal-driven actions.

## 21. Initial implementation sequence

Implementation should proceed in these slices:

1. CLI contracts and exit codes;
2. root parser and top-level dispatch;
3. status command;
4. task list;
5. task create;
6. task modify;
7. task complete and delete;
8. proposal list and show;
9. proposal approve, reject and cancel;
10. JSON serialisation;
11. timestamp localisation;
12. documentation and integration tests.

Each slice must pass the complete repository quality gate before commit.

## 22. Deferred work

The following are deferred:

- model chat;
- natural-language command interpretation;
- shell completion generation;
- interactive terminal UI;
- offline command queueing;
- remote execution;
- calendar, contacts, accounting and email commands;
- PWA integration;
- plugin or skill command discovery;
- command aliases beyond documented grammar;
- automatic provider installation from the CLI.

## 23. Acceptance criteria

Milestone 2.3 is complete when:

- `lea status` reports runtime and provider state;
- all initial task commands work through `TaskProvider`;
- proposal list, show, approve, reject, cancel and execute use repository and
  orchestration boundaries;
- human-readable output is stable and localised;
- `--json` produces deterministic structured output;
- stable exit codes are implemented and documented;
- parser and expected failures do not expose tracebacks;
- existing `lea runtime` commands remain compatible;
- direct storage access is absent;
- isolated integration tests pass;
- the full repository quality and CI gates pass.

### 6.6 Task-tag normalisation

Task-tag input is trimmed and each hyphen is replaced with an underscore before
validation. Canonical tags must match `[A-Za-z_][A-Za-z0-9_]*`.

The CLI reports every changed tag in both human-readable and JSON output.
Other unsupported characters are rejected rather than silently removed.
Duplicate tags and add/remove conflicts are evaluated after normalisation.

Provider task records must already contain canonical tags and are never
silently rewritten during read-back.
