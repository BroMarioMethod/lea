# Telegram Task Lifecycle Correction

| Item | Value |
|---|---|
| Document Status | Accepted |
| Implementation Status | Not Started |
| Verification Status | Not Tested |
| Date | 29 July 2026 |
| Base Release | `milestone-2.7` / LEA `0.2.0` |
| Development Branch | `fix/telegram-task-lifecycle` |

## Purpose

Live test-card acceptance proved that the Taskwarrior provider can create,
list, modify, complete and delete tasks through Telegram. The same acceptance
also exposed a channel-application boundary defect.

Task mutations currently call Local CLI task services directly. As a result,
the live commands bypass persistent proposal creation, confirmation policy,
approved-only execution and append-only action audit persistence.

## Observed behaviour

The live test-card workflow established:

- `/tasks` succeeded;
- `/task_add` mutated Taskwarrior immediately;
- `/task_modify` mutated Taskwarrior immediately;
- `/task_complete` mutated Taskwarrior immediately;
- `/task_delete` deleted immediately without explicit confirmation;
- `/task_show` returned `channel_command_not_supported`;
- `/help` returned `channel_command_not_supported`;
- no matching persistent proposal or action-integrity audit records were found
  for the tested task UUIDs.

The provider lifecycle itself passed. The defect is in channel-to-application
composition, not in Taskwarrior execution.

## Architectural correction

The required path is:

```text
Telegram request
→ channel authentication and capability validation
→ deterministic request parsing
→ ActionProposal construction
→ ActionOrchestrator submission
→ proposal and audit persistence
→ explicit confirmation where required
→ explicit approved execution
→ task action handler
→ Taskwarrior provider
→ final proposal and execution-audit persistence
```

Telegram shall not use the Local CLI as its internal task mutation API. The
Local CLI and Telegram remain peer adapters over reusable application
services.

## Interactive confirmation policy

The provider-neutral task proposal builders retain
`ConfirmationPolicy.WHEN_REQUIRED` as their reusable default.

Interactive Telegram and Web/PWA task requests shall override that default
with `ConfirmationPolicy.ALWAYS`. Every interactive task mutation, including
low-risk task creation, shall therefore:

1. construct and persist a proposal;
2. persist the submission audit events;
3. remain in `awaiting_confirmation`;
4. immediately return approval controls;
5. perform no task-provider mutation.

Approval remains separate from execution. A future explicitly trusted
automation may use the provider-neutral builder default, but ordinary
interactive requests must not be silently approved.

## Implementation slices

### Slice 1 — Proposal-submission application service

Create a reusable, channel-neutral service that:

- constructs an `ActionProposal` from validated action inputs;
- accepts injected proposal-ID and UTC timestamp sources;
- submits through `ActionOrchestrator`;
- persists the resulting proposal with `MarkdownProposalRepository`;
- reports audit and proposal partial-persistence failures explicitly;
- never executes an action handler.

### Slice 2 — Task proposal builders

Add deterministic builders for:

- `task.create`;
- `task.modify`;
- `task.complete`;
- `task.delete`.

Builders shall expose the risk and confirmation assignments in
LEA-SPEC-0015 section 10.1.

### Slice 3 — Channel mutation handlers

Replace direct task-mutation executors in `ChannelHandlerDependencies` with the
proposal-submission service.

Responses shall expose:

- proposal ID;
- action;
- risk level;
- proposal status;
- audit persistence;
- proposal persistence;
- available next operation.

Awaiting-confirmation responses shall include bounded Approve, Reject, Cancel
and Revise controls.

Approved low-risk responses shall instruct the user to execute explicitly.

### Slice 4 — Read-only help and task-show handlers

Implement:

- `system.help`;
- `tasks.show`.

`tasks.show` shall use the provider-neutral read boundary and accept one
canonical task UUID.

### Slice 5 — Risk-specific proposal execution authorisation

Change proposal execution so the exact execution capability is checked against
the stored proposal risk before provider loading or action execution.

### Slice 6 — Production runtime composition

Construct the proposal repository, integrity audit store, orchestrator and
submission service from the validated system runtime configuration used by the
Telegram worker.

### Slice 7 — Automated regression coverage

Add tests proving:

- no channel task mutation executor calls the provider directly;
- proposal submission never executes;
- proposal and audit records are persisted;
- delete awaits confirmation;
- approval does not execute;
- execution requires the risk-specific capability;
- stale and duplicate controls fail closed;
- `/help` and `/task_show` are supported;
- partial persistence is reported safely;
- secrets and external Telegram identifiers are not written to proposal or
  audit content.

### Slice 8 — Test-card acceptance

Repeat a disposable Telegram lifecycle:

```text
create proposal
→ execute approved create proposal
→ show task
→ modify proposal
→ approve
→ execute
→ complete proposal
→ approve
→ execute
→ delete proposal
→ approve
→ execute
```

Verify Taskwarrior state, proposal documents, action-integrity audit records,
reboot continuity and service recovery.

## Completion criteria

This correction is complete only when:

- every Telegram task mutation uses the proposal workflow;
- no mutation occurs during submission or approval;
- delete cannot execute without explicit confirmation;
- risk-specific execution capabilities are enforced;
- `/help` and `/task_show` work;
- proposal and audit evidence exists for the complete live lifecycle;
- the full repository gate passes;
- test-card acceptance passes.
