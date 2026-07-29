# LEA-SPEC-0015 — Channel Interaction and Telegram Adapter

- **Status:** Accepted
- **Version:** 1.4
- **Date:** 24 July 2026
- **Milestone:** 2.5 — Telegram Adapter

## 1. Purpose

This specification defines LEA’s first remote interaction channel and the reusable channel-neutral contracts that future interfaces, including the Local Web/PWA interface, will use.

Telegram is the first remote transport because it provides a practical, low-cost bot interface without requiring LEA to expose a public HTTP endpoint. Telegram-specific types and behaviours must remain isolated from LEA’s core application services.

The implementation must preserve LEA’s existing architectural guarantees:

- deterministic Python boundaries;
- validated immutable contracts;
- explicit permissions;
- confirmation before sensitive execution;
- append-only audit logging;
- externalised secrets;
- local-first storage;
- provider-neutral tools and actions;
- no direct transport-to-tool execution path.

## 2. Scope

Milestone 2.5 includes:

- channel-neutral inbound request and outbound response contracts;
- Telegram user and private-chat authorisation;
- role-to-capability resolution;
- Telegram long polling;
- deterministic Telegram update parsing;
- explicit command routing;
- safe response formatting;
- proposal approval, rejection, cancellation and revision requests;
- explicit execution of approved proposals;
- persistent update-offset handling;
- duplicate-update protection;
- runtime construction;
- a supervisor-neutral long-running worker, with a `systemd` deployment asset for DietPi;
- graceful shutdown;
- tests for contracts, transport boundaries, authorisation, routing and polling.

Milestone 2.5 does not include:

- free-form LLM conversation;
- automatic interpretation of ordinary text;
- public Telegram groups or channels;
- public webhook exposure;
- WhatsApp;
- Local Web/PWA implementation;
- general multi-tenant hosting;
- unrestricted remote administration;
- direct shell execution;
- installation or removal of integrations through Telegram;
- modification of audit records;
- owner configuration changes through Telegram.

## 3. Architectural position

The intended flow is:

```text
Telegram update
    ↓
Telegram transport parser
    ↓
channel-neutral inbound request
    ↓
identity and capability authorisation
    ↓
deterministic command router
    ↓
existing LEA application services
    ↓
channel-neutral response
    ↓
Telegram response formatter
    ↓
Telegram Bot API
```

The Telegram adapter must never call Taskwarrior, filesystem operations, knowledge persistence or action handlers directly.

All tool use must continue through LEA’s existing provider, action, proposal, confirmation, execution and audit boundaries.

## 4. Shared channel boundary

Milestone 2.5 introduces reusable channel-neutral interaction contracts.

These contracts must not import Telegram-specific types.

Suggested package:

```text
src/lea/channels/
    __init__.py
    contracts.py
    authorisation.py
    routing.py
```

Telegram-specific implementation:

```text
src/lea/adapters/telegram/
    __init__.py
    contracts.py
    parser.py
    transport.py
    authorisation.py
    formatting.py
    offset_store.py
    worker.py
```

Runtime construction:

```text
src/lea/runtime/telegram.py
```

## 5. Channel-neutral contracts

### 5.1 Channel identity

A channel identity represents the authenticated source of one request.

Required fields:

- `channel`: stable lower-case channel name;
- `user_id`: stable channel-scoped user identifier;
- `conversation_id`: stable channel-scoped conversation identifier;
- `display_name`: optional human-readable name;
- `role`: resolved role name;
- `capabilities`: immutable explicit capability set.

Telegram numeric identifiers must be represented canonically as decimal strings at the shared channel boundary.

### 5.2 Inbound request

A channel-neutral request must include:

- request identifier;
- source update identifier;
- channel identity;
- request type;
- command name;
- immutable parameters;
- received UTC timestamp;
- optional correlation identifier.

The request type must be an enum, initially supporting:

- `command`;
- `confirmation`;
- `revision_request`.

Ordinary text that does not match an accepted command must not become an action proposal.

### 5.3 Outbound response

A channel-neutral response must include:

- request identifier;
- outcome;
- safe user-facing message;
- optional structured data;
- optional interaction controls;
- optional correlation identifier;
- response UTC timestamp.

Response outcomes should initially include:

- `succeeded`;
- `rejected`;
- `not_authorised`;
- `validation_failed`;
- `not_found`;
- `conflict`;
- `application_failed`;
- `temporarily_unavailable`.

Responses must not contain:

- Python exception text;
- stack traces;
- filesystem paths;
- bot tokens;
- complete runtime configuration;
- unrestricted knowledge content;
- audit hash internals;
- provider command lines unless explicitly safe and intended.

Channel responses shall not expose channel-scoped user or
conversation identifiers as decision actors. User-facing decision data shall
use a role-scoped label such as `telegram:owner`. The full accountable actor
identifier may remain in local proposal-decision and audit records.

### 5.4 Interaction controls

Channel-neutral controls should represent:

- action identifier;
- label;
- control type;
- immutable parameters;
- required capability.

Telegram renders these controls as inline buttons. The Local Web/PWA interface may later render the same controls as buttons or forms.

## 6. Telegram transport

### 6.1 Delivery method

Telegram updates must be received through long polling.

Webhooks are out of scope for Milestone 2.5.

The worker must:

- request updates using a persisted offset;
- use a bounded long-poll timeout;
- process updates in deterministic update-ID order;
- apply the routed update and prepare any response before checkpointing;
- advance the offset after a terminal application result and before outbound
  response delivery;
- treat response-formatting, send, edit and callback-answer failures after
  checkpointing as redacted non-fatal warnings;
- continue processing later updates after a response-delivery failure;
- retry temporary update-fetching failures with bounded back-off;
- stop cleanly on termination signals;
- avoid uncontrolled busy loops.

### 6.2 Telegram API boundary

The transport must be represented by an injected protocol rather than importing a third-party Telegram SDK into core services.

Required operations:

- fetch updates;
- send text message;
- send message with inline controls;
- answer callback query;
- optionally edit an existing message.

HTTP implementation details must remain inside the Telegram adapter.

No direct network calls are permitted in contracts, routing or application services.

### 6.3 Supported update types

Initially accepted:

- private text messages containing explicit commands;
- callback queries generated by LEA inline controls.

Initially rejected or ignored safely:

- group messages;
- supergroup messages;
- channel posts;
- edited messages;
- media;
- files;
- voice notes;
- inline queries;
- unsupported callback data;
- updates from unauthorised users;
- requests from a mismatched private chat.

## 7. Authorised users

### 7.1 Storage

Authorised users must be stored in an external TOML file, not in `.env`, source code or the repository.

Recommended runtime path:

```text
/etc/lea/telegram/authorised-users.toml
```

A non-secret example file may be committed at:

```text
config/examples/telegram-authorised-users.example.toml
```

The example must use fictional identifiers only.

### 7.2 User record

Each authorised user record must contain:

- human-readable name;
- Telegram numeric user ID;
- permitted private-chat ID;
- role;
- enabled state;
- optional explicit capability additions;
- optional explicit capability removals.

Example:

```toml
schema_version = 1

[[users]]
name = "Owner"
telegram_user_id = 123456789
private_chat_id = 123456789
role = "owner"
enabled = true
```

### 7.3 Matching

Authorisation requires both:

- exact Telegram user-ID match; and
- exact private-chat-ID match.

A valid user ID from an unrecognised chat must be rejected.

A valid chat ID paired with an unrecognised user must be rejected.

Display names and usernames are never sufficient for authentication.

### 7.4 Logging

Rejected access attempts may be audited using safe metadata:

- channel;
- reason code;
- hashed or redacted external identifier;
- timestamp.

Usernames, message content and bot tokens must not be included unless a later specification explicitly permits them.

## 8. Roles and capabilities

### 8.1 Initial roles

Initial roles:

- `owner`;
- `tester`;
- `read_only`.

Roles are named capability bundles. Authorisation decisions must be made against explicit capabilities, not by scattered direct role checks.

### 8.2 Capability principles

Capabilities must use stable namespaced identifiers.

Read and write capabilities remain distinct. Neither implies the other.

Examples:

```text
Runtime.Status.Read
Tasks.Read
Tasks.Write
Tasks.Delete
Proposals.Read
Proposals.Confirm
Proposals.Execute.LowRisk
Proposals.Execute.MediumRisk
Proposals.Execute.HighRisk
Knowledge.Read.Low
Knowledge.Read.Medium
Knowledge.Read.Critical
```

### 8.3 Initial role intent

`owner`:

- broad operational access;
- may use high-risk execution where existing confirmation rules permit it;
- may view critical knowledge where explicitly configured;
- may not change host configuration through Telegram in Milestone 2.5.

`tester`:

- may exercise normal operational workflows;
- may use only permitted data and tools;
- may execute low- and optionally medium-risk actions;
- may not execute high-risk actions;
- may not manage users, roles, skills or configuration;
- must not automatically gain access to owner data.

`read_only`:

- may view explicitly permitted status, tasks, proposals and knowledge;
- may not create, modify, confirm, revise, cancel or execute.

### 8.4 Test-user isolation

External testers should initially use either:

- a dedicated test deployment; or
- explicitly isolated sample data.

A tester role alone is not a substitute for data isolation.

Milestone 2.5 may implement the multi-user authorisation structure while enabling only the owner account. Test accounts are expected to be enabled during Milestone 2.7.

## 9. Bot token

The token must be read from the existing runtime secret path:

```text
/etc/lea/secrets/telegram-bot-token
```

Requirements:

- never stored in TOML runtime configuration as a literal value;
- never committed;
- never logged;
- never included in exceptions returned to users;
- restrictive file permissions;
- read only by the LEA service account;
- trailing newline permitted and stripped exactly once;
- empty or malformed values rejected deterministically.

## 10. Active and planned commands

The active Telegram command set shall contain only commands backed by an
implemented channel handler and application operation.

### Active general commands

- `/start`
- `/help`
- `/status`

### Active task commands

- `/tasks`
- `/task_add`
- `/task_show`
- `/task_modify`
- `/task_complete`
- `/task_delete`

### Active proposal commands

- `/proposals`
- `/proposal_show`
- `/proposal_approve`
- `/proposal_reject`
- `/proposal_cancel`
- `/proposal_execute`

### Deferred planned commands

The following commands remain part of the planned interaction catalogue but
shall not be registered by the active Telegram router until their application
operations are implemented:

- `/proposal_revise`;
- `/knowledge_show`;
- `/knowledge_find`.

`/proposal_revise` shall return only with the complete revision workflow
specified below. The knowledge commands shall return with the provider-neutral
knowledge integration.

Exact active command syntax must be deterministic and documented.

Commands should map to channel-neutral request names rather than directly to CLI functions.

The existing CLI remains a peer adapter, not the internal API for Telegram.

## 10.1 Task command lifecycle

Task read commands and task mutation commands have different execution
boundaries.

### Read commands

The following commands are read-only and may execute immediately after channel
authentication and capability validation:

```text
/tasks
/task_show <task-uuid>
```

`/task_show` shall use the provider-neutral task read boundary. It shall not
create an action proposal and shall return exactly one matching task or a
structured not-found result.

### Mutation commands

The following commands request mutations and shall never invoke a task provider
or Local CLI task mutation service directly:

```text
/task_add
/task_modify
/task_complete
/task_delete
```

Each mutation command shall:

1. parse and validate deterministic channel arguments;
2. construct a new `ActionProposal`;
3. record the authenticated channel identity as the proposal source;
4. submit the proposal through `ActionOrchestrator`;
5. persist the resulting canonical proposal document;
6. persist all required append-only audit events;
7. return the proposal identifier, action, risk, status and next permitted
   operation;
8. perform no provider mutation during proposal submission.

The initial task-action risk assignments and provider-neutral builder
defaults are:

| Action | Risk | Builder confirmation policy |
|---|---|---|
| `task.create` | Low | When required |
| `task.modify` | Medium | When required |
| `task.complete` | Medium | When required |
| `task.delete` | High | When required |

Interactive Telegram and Web/PWA task requests shall override the builder
default with `always`. Every interactive task mutation, including low-risk
creation, shall therefore persist as `awaiting_confirmation` and immediately
return approval controls.

The provider-neutral builders retain `when_required` so a future explicitly
trusted automation may use the normal risk policy without changing the
interactive safety contract. Approval never implies execution.

### Confirmation and execution

Approval shall remain separate from execution.

An approval callback or `/proposal_approve` command may transition an
`awaiting_confirmation` proposal to `approved`, but shall not invoke
Taskwarrior.

Execution shall occur only through `/proposal_execute` or an explicit
Execute control. The execution handler shall:

- load the persistent proposal;
- require `approved` status;
- derive the required capability from the proposal risk:
  - `Proposals.Execute.LowRisk`;
  - `Proposals.Execute.MediumRisk`;
  - `Proposals.Execute.HighRisk`;
- reject the request before provider loading when the authenticated identity
  lacks the exact capability;
- execute through the registered provider-neutral action handler;
- persist the action-execution audit event;
- persist the final proposal state.

A single static low-risk route capability shall not authorise medium- or
high-risk proposal execution.

After successful approval, the channel shall return:

```text
Execute | Cancel
```

The Execute control shall carry the exact risk-specific execution capability.
The callback route may use `Proposals.Read` as its static entry capability, but
the stored-risk authorisation in the execution handler remains mandatory.

Cancellation is valid while a proposal is `awaiting_confirmation` or
`approved`. Cancelling an approved proposal shall preserve the actor, reason,
timestamp, append-only audit event and optimistic repository status guard.
Approval and rejection remain invalid once the proposal is already approved.

### Help command

`/help` shall return the deterministic command set actually supported by the
channel application. It shall not advertise deferred commands as operational.

## 11. Confirmation controls

When a proposal awaits confirmation, Telegram should render:

```text
Approve | Reject | Cancel | Revise
```

### Approve

Applies an explicit approved confirmation decision through the existing orchestration boundary.

### Reject

Applies an explicit rejected confirmation decision.

### Cancel

Applies an explicit cancelled confirmation decision.

### Revise

Must not mutate the original proposal in place.

Revision must:

1. preserve the original proposal and audit history;
2. collect requested replacement values;
3. create a new proposal with a new proposal ID;
4. retain an explicit relationship to the original proposal;
5. restart validation and confirmation policy.

A complete conversational form editor is not required initially.

The first implementation may return a structured `/proposal_revise` command containing the original proposal ID and supported editable fields.

### Execution

Approval must not automatically imply execution.

Execution remains a separate explicit command or control after approval.

## 12. Callback security

Inline callback data must not contain sensitive content.

Callback data should contain only bounded identifiers, such as:

- action code;
- proposal ID;
- revision or version token.

The adapter must validate:

- callback format;
- authorised user;
- authorised chat;
- proposal existence;
- current proposal state;
- required capability;
- stale or duplicate callback use.

A stale callback must fail safely without altering state.

## 13. Ordinary text

Milestone 2.5 is commands-only.

Unrecognised text should receive a safe response such as:

```text
LEA cannot interpret free-form messages yet.

Use /help to see the available commands.
```

No ordinary text may be sent to an LLM or converted into an action proposal during this milestone.

A future LLM provider may propose structured channel requests, but those requests must still pass the same validation, permission, confirmation and audit boundaries.

## 14. Offset persistence and duplicate protection

Telegram update offsets must be stored below the configured adapter runtime directory.

Suggested path:

```text
<adapter_dir>/telegram/update-offset.json
```

Requirements:

- canonical deterministic serialisation;
- atomic replacement;
- explicit schema version;
- no symbolic-link traversal;
- malformed state fails closed;
- monotonic update ID;
- duplicate update IDs do not repeat operations;
- offset publication occurs only after terminal handling;
- temporary response-delivery failure must have explicit retry semantics.

The offset store is runtime state and must not be committed.

## 15. Audit requirements

LEA-mediated Telegram operations must preserve existing audit guarantees.

The adapter may add safe channel metadata to relevant audit events where explicitly supported:

- channel name;
- request ID;
- authorisation role;
- safe command name;
- safe outcome code.

The adapter must not audit:

- bot token;
- unrestricted message bodies;
- knowledge bodies;
- unredacted sensitive identifiers;
- inline callback payloads containing internal data.

Unauthorised and malformed requests should produce structured security or adapter events in a future audit extension. Their absence must not allow an action to proceed.

## 16. Runtime configuration

Milestone 2.5 should add explicit Telegram runtime configuration rather than relying on arbitrary environment variables.

Expected configuration concepts:

- enabled state;
- authorised-user file path;
- bot-token file path;
- polling timeout;
- retry delay bounds;
- offset-store path or deterministic derivation;
- optional safe message-size limit.

The runtime loader must reject unknown fields and invalid relationships.

Existing profiles must remain deterministic.

No configuration constructor may create files or directories.

## 17. Runtime construction

A deterministic factory should construct the Telegram runtime from validated configuration.

Suggested result:

```text
TelegramRuntime
├── transport
├── authorised-user repository
├── capability resolver
├── command router
├── response formatter
├── offset store
└── polling worker
```

Construction must not:

- start polling;
- create the token file;
- create the authorised-user file;
- create the offset file;
- send a Telegram request;
- modify runtime state.

## 18. Service supervision

The Telegram worker must not depend on a particular init or service-
supervision system.

The production DietPi deployment should include a dedicated `systemd` service.
Later Unix-family deployment support may provide equivalent definitions for
runit, OpenRC, s6, launchd or another suitable supervisor without changing the
worker or its application contracts.

Requirements:

- run as the LEA service account;
- restart on recoverable failure with bounded delay;
- stop cleanly;
- not run as root;
- no token in command-line arguments;
- explicit working directory not required for correctness;
- logs must avoid sensitive values;
- startup must fail clearly when required configuration is invalid.

The CLI should provide inspection or health commands before enabling the worker.

## 19. Error handling

Every boundary must convert failures into structured issues.

Required failure categories include:

- configuration invalid;
- token unavailable;
- authorised-user file invalid;
- unauthorised user;
- chat mismatch;
- unsupported update;
- malformed command;
- capability denied;
- proposal not found;
- proposal state conflict;
- stale callback;
- Telegram transport unavailable;
- Telegram response rejected;
- offset persistence failed;
- application service failed;
- audit persistence failed.

Internal exceptions must not be sent to Telegram users.

## 20. Message limits and formatting

Telegram response formatting must:

- escape or avoid unsupported markup;
- apply deterministic maximum lengths;
- split oversized safe responses deterministically;
- avoid splitting identifiers where practical;
- omit sensitive details;
- clearly identify success, rejection and failure;
- localise displayed timestamps using the configured display timezone;
- retain UTC in stored contracts and audit data.

## 21. Testing requirements

Tests must not require live Telegram access.

Required test classes:

- immutable channel contracts;
- authorisation-file parsing;
- exact user/chat matching;
- role capability resolution;
- disabled-user rejection;
- private-chat enforcement;
- Telegram update parsing;
- command parsing;
- ordinary-text rejection;
- callback validation;
- stale callback handling;
- response formatting;
- offset atomicity;
- duplicate-update protection;
- retry behaviour;
- graceful shutdown;
- runtime configuration;
- runtime construction without side effects;
- end-to-end fake transport flow;
- audit preservation;
- token redaction;
- no direct provider or shell bypass.

A separate manual live smoke test may be documented using the owner’s Telegram user ID and private chat ID.

The bot token must never be included in test fixtures committed to the repository.

## 22. Security requirements

Milestone 2.5 must enforce:

- private chats only;
- exact numeric identity matching;
- explicit capabilities;
- no username-based trust;
- no direct shell access;
- no Telegram configuration changes;
- no unrestricted knowledge access;
- no token logging;
- no direct transport-to-provider calls;
- bounded incoming message size;
- bounded callback-data size;
- safe handling of duplicate and stale requests;
- symbolic-link rejection for security-relevant state files;
- deterministic failure on malformed state.

## 23. Compatibility and extensibility

The shared channel contracts must support future adapters without importing Telegram.

Milestone 2.6 must be able to implement the Local Web/PWA interface by adapting HTTP requests into the same application-facing contracts.

Future tools and skills should register capabilities and commands without requiring changes to Telegram transport parsing.

WhatsApp is explicitly outside the planned LEA integration scope.

## 24. Packaging direction

Native DietPi remains the primary deployment target.

Windows 11 support through WSL is a higher priority than container packaging.

The implementation should remain portable by preserving:

- explicit runtime paths;
- injected dependencies;
- externalised state;
- no current-working-directory assumptions;
- deterministic startup and shutdown;
- provider-neutral contracts.

Docker or Compose packaging may be considered later but is not a Milestone 2.5 requirement.

## 25. Milestone delivery slices

1. Accept this specification.
2. Add channel-neutral interaction contracts.
3. Add authorised-user and capability contracts.
4. Add authorised-user TOML parsing and validation.
5. Add Telegram transport contracts and fake transport.
6. Add Telegram update parsing.
7. Add deterministic command routing.
8. Add proposal confirmation and revision controls.
9. Add response formatting.
10. Add offset persistence and duplicate protection.
11. Add runtime configuration and construction.
12. Add polling worker and graceful shutdown.
13. Add the DietPi `systemd` deployment asset, supervisor-neutral worker guidance and health checks.
14. Run milestone verification.
15. Open, check, merge and tag `milestone-2.5`.

## 26. Acceptance criteria

Milestone 2.5 is complete when:

- Telegram long polling works through an injected transport;
- only explicitly authorised user/chat pairs are accepted;
- roles resolve to immutable explicit capabilities;
- commands route through shared channel contracts;
- ordinary text is not interpreted;
- task, proposal, status and exact knowledge commands are available;
- confirmation controls use existing orchestration;
- revision never mutates an existing proposal;
- approval and execution remain separate;
- duplicate updates cannot repeat operations;
- persistent offsets are atomic and validated;
- no Telegram-specific type leaks into core services;
- no direct tool or shell bypass exists;
- bot secrets remain external;
- runtime construction has no side effects;
- the supervisor-neutral worker can start and stop safely, and the DietPi `systemd` deployment asset is verified;
- all automated quality checks pass;
- the pull request is merged with a merge commit;
- the annotated `milestone-2.5` tag is pushed.
