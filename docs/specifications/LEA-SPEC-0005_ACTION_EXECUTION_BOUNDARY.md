---
title: Action Execution Boundary Specification
document_id: LEA-SPEC-0005
version: 0.1.2
status: Accepted
authors:
  - Marius du Preez
  - OpenAI ChatGPT
license: AGPL-3.0-only
created: 2026-07-20
last_updated: 2026-07-20
review_required: false
---

# Action Execution Boundary Specification

## Document Status

| Item | Value |
|---|---|
| Status | Accepted |
| Requires Review | No |
| Implementation | Complete |
| Test Status | Automated Tests Passing |

---

## 1. Purpose

This specification defines the deterministic boundary through which an approved LEA action proposal may reach an authorised action handler.

It defines:

- handler registration;
- deterministic handler lookup;
- execution eligibility;
- execution-state transitions;
- handler invocation;
- successful and failed execution results;
- exception containment;
- immutable execution records;
- structured execution issues;
- deterministic serialisation.

The execution boundary SHALL be the only core workflow component introduced by this milestone that may invoke an action handler.

---

## 2. Why?

LEA-SPEC-0002 defines action proposals and execution-result records.

LEA-SPEC-0003 defines legal proposal-state transitions.

LEA-SPEC-0004 defines confirmation and approval policy.

Those specifications do not define:

- how approved proposals reach handlers;
- how handlers are registered;
- how unknown actions fail safely;
- how handler exceptions are contained;
- how execution outcomes transition proposal state;
- how execution records and transitions are returned together.

Without a central execution boundary, callers could invoke handlers directly and bypass validation, approval and transition policy.

---

## 3. Scope

This specification defines:

- an action-handler protocol;
- an immutable handler registry or deterministic registry interface;
- unique action-name registration;
- deterministic handler lookup;
- execution eligibility checks;
- transition from `approved` to `executing`;
- handler invocation;
- successful execution outcomes;
- failed execution outcomes;
- transition from `executing` to `succeeded` or `failed`;
- exception containment;
- structured execution issues;
- immutable orchestration results;
- UTC-aware execution timestamps;
- deterministic JSON-compatible serialisation;
- automated tests.

This specification does not define:

- plugin discovery;
- dynamic module loading;
- external process isolation;
- retries;
- timeouts;
- cancellation during execution;
- authentication;
- permissions;
- persistent audit storage;
- distributed execution;
- background jobs;
- queues;
- scheduling;
- rollback;
- compensation;
- handler-specific domain logic;
- Telegram or other user interfaces.

---

## 4. Engineering Principles

### EB-001 — Approved Actions Only

Only proposals in the `approved` state SHALL be eligible to enter the execution boundary.

### EB-002 — Single Execution Boundary

Core workflow code SHALL invoke action handlers only through the deterministic execution boundary.

### EB-003 — Deterministic Dispatch

Action names SHALL map deterministically to explicitly registered handlers.

AI output SHALL NOT dynamically select executable Python objects.

### EB-004 — No Implicit Discovery

The initial implementation SHALL NOT scan modules, load entry points or discover plugins automatically.

### EB-005 — Fail Closed

Unknown, missing or invalid handlers SHALL produce structured failure outcomes.

They SHALL NOT fall back to another handler.

### EB-006 — Exception Containment

Exceptions raised by handlers SHALL be caught at the execution boundary and converted into structured execution failures.

### EB-007 — Immutable Workflow Data

The supplied proposal SHALL remain unchanged.

Execution SHALL return new proposal states and immutable records.

### EB-008 — Explicit State Progression

Execution SHALL follow:

```text
approved → executing → succeeded
```

or:

```text
approved → executing → failed
```

### EB-009 — Result Is Not Proof of External Truth

A successful execution result indicates that the handler reported success.

It does not independently prove that every external real-world effect occurred as intended.

### EB-010 — Conservative Error Exposure

Handler exceptions SHALL not expose tracebacks, internal object representations or secrets through normal serialised results.

---

## 5. Existing Contracts

The implementation SHALL reuse:

```text
ActionProposal
ActionStatus
ActionTransition
TransitionResult
ExecutionError
ExecutionResult
```

The implementation SHALL reuse the state-transition policy defined by LEA-SPEC-0003.

It SHALL NOT duplicate transition legality inside the execution module.

---

## 6. Action Handler Contract

### EB-011 — Handler Input

A handler SHALL receive an immutable `ActionProposal`.

The proposal supplied to the handler SHALL have status:

```text
executing
```

### EB-012 — Handler Output

A handler SHALL return a JSON-compatible mapping or `None`.

The returned value represents handler output only.

The handler SHALL NOT construct the final `ExecutionResult`.

### EB-013 — Handler Protocol

The initial handler protocol SHALL resemble:

```python
class ActionHandler(Protocol):
    def __call__(
        self,
        proposal: ActionProposal,
    ) -> Mapping[str, object] | None:
        ...
```

Equivalent callable type aliases MAY be used if strict typing and observable behaviour remain unchanged.

### EB-014 — Synchronous Execution

Handlers SHALL execute synchronously during this milestone.

Asynchronous handlers are out of scope.

### EB-015 — Handler Responsibility

Handlers SHALL perform any domain-specific validation necessary immediately before performing their action.

Core proposal validation does not replace handler-specific validation.

### EB-016 — Handler Side Effects

A handler MAY perform the side effect represented by its registered action.

No earlier workflow stage may perform that side effect.

### EB-017 — Handler Output Validation

Handler output SHALL be converted into the immutable JSON-compatible value model used by LEA action records.

Unsupported output values SHALL cause execution to fail safely.

---

## 7. Handler Registry

### EB-018 — Explicit Registration

Handlers SHALL be registered explicitly against canonical action names.

Example:

```text
task.create
calendar.event.create
knowledge.note.write
```

### EB-019 — Canonical Action Names

Registered action names SHALL follow the same canonical naming rules as `ActionProposal.action`.

### EB-020 — Unique Registration

An action name SHALL map to exactly one handler in a registry.

Duplicate registration SHALL be rejected.

### EB-021 — Registry Mutation

The initial registry MAY be mutable during application initialisation.

Execution SHALL only use the registry’s deterministic current mapping.

### EB-022 — Lookup

Handler lookup SHALL use the proposal’s exact canonical action name.

Partial matching, aliases and fuzzy matching SHALL NOT be used.

### EB-023 — Unknown Action

When no handler is registered for an action, execution SHALL fail with:

```text
unknown_action
```

The handler SHALL not be invoked.

### EB-024 — Registry Interface

The initial implementation SHALL provide an interface resembling:

```python
registry.register(
    action: str,
    handler: ActionHandler,
) -> None
```

and:

```python
registry.get(
    action: str,
) -> ActionHandler | None
```

Names MAY be refined during implementation provided the observable contract remains unchanged.

---

## 8. Execution Eligibility

### EB-025 — Required Proposal State

`execute_action()` SHALL accept execution only when:

```text
proposal.status == approved
```

### EB-026 — Invalid Proposal State

A proposal in any other state SHALL produce a structured issue:

```text
invalid_proposal_status
```

The proposal SHALL not transition and no handler SHALL be invoked.

### EB-027 — Handler Resolution Before Execution State

The execution boundary SHALL resolve the handler before transitioning the proposal to `executing`.

An unknown action SHALL therefore leave the proposal in `approved`.

This prevents a proposal becoming stranded in `executing` when no handler exists.

---

## 9. Execution Process

### EB-028 — Execution Sequence

For an eligible proposal with a registered handler, the boundary SHALL perform these steps in order:

1. verify that the proposal is `approved`;
2. resolve the registered handler;
3. record the execution start timestamp;
4. transition the proposal from `approved` to `executing`;
5. invoke the handler with the new `executing` proposal;
6. record the completion timestamp;
7. construct an `ExecutionResult`;
8. transition the executing proposal to `succeeded` or `failed`;
9. return the complete orchestration result.

### EB-029 — Start Transition

The transition:

```text
approved → executing
```

SHALL be recorded before handler invocation.

### EB-030 — Successful Handler Outcome

When the handler returns normally and its output is valid:

- `ExecutionResult.success` SHALL be `true`;
- `ExecutionResult.status` SHALL be `succeeded`;
- `ExecutionResult.error` SHALL be `None`;
- the proposal SHALL transition from `executing` to `succeeded`.

### EB-031 — Handler Failure Outcome

When the handler raises an exception or returns invalid output:

- `ExecutionResult.success` SHALL be `false`;
- `ExecutionResult.status` SHALL be `failed`;
- `ExecutionResult.error` SHALL contain an `ExecutionError`;
- the proposal SHALL transition from `executing` to `failed`.

### EB-032 — Original Proposal

The original approved proposal SHALL remain unchanged.

### EB-033 — Executing Proposal

The handler SHALL receive a distinct immutable proposal whose status is `executing`.

### EB-034 — Final Proposal

The successful orchestration result SHALL contain a distinct immutable proposal whose status is either:

```text
succeeded
failed
```

---

## 10. Execution Timestamps

### EB-035 — Start Timestamp

`started_at` SHALL be timezone-aware and stored in UTC.

### EB-036 — Completion Timestamp

`completed_at` SHALL be timezone-aware and stored in UTC.

### EB-037 — Ordering

`completed_at` SHALL not occur before `started_at`.

### EB-038 — Start Transition Timestamp

The `approved → executing` transition timestamp SHALL equal `started_at`.

### EB-039 — Completion Transition Timestamp

The `executing → succeeded` or `executing → failed` transition timestamp SHALL equal `completed_at`.

### EB-040 — Injected Clock

The execution boundary SHOULD permit deterministic timestamp injection for automated tests.

The exact clock interface MAY be refined during implementation.

### EB-041 — User Presentation

When timestamps are shown to users, LEA SHOULD convert them to the user’s configured local time zone while preserving canonical UTC storage.

When no user time zone is available, timestamps SHALL be shown as UTC and identified as UTC.

---

## 11. Execution Errors

### EB-042 — Unknown Action Error

An unknown action SHALL produce an execution-boundary issue with code:

```text
unknown_action
```

Because no handler was invoked, no `ExecutionResult` SHALL be created.

### EB-043 — Handler Exception Error

An exception raised by a handler SHALL produce:

```text
handler_exception
```

as the `ExecutionError.code`.

### EB-044 — Invalid Handler Output Error

Unsupported handler output SHALL produce:

```text
invalid_handler_output
```

as the `ExecutionError.code`.

### EB-045 — Error Message

Execution-error messages SHALL be human-readable and safe for logging.

### EB-046 — Error Details

Error details MAY contain structured, non-sensitive diagnostic context.

Normal error details SHALL NOT contain:

- tracebacks;
- exception objects;
- executable objects;
- secrets;
- credentials;
- environment dumps.

### EB-047 — Exception Type

The exception class name MAY be recorded as a plain string in safe error details.

The exception message SHOULD NOT be exposed automatically unless explicitly judged safe by a later policy.

---

## 12. Execution Boundary Issues

### EB-048 — Boundary Issue

An execution-boundary issue SHALL contain:

- a machine-readable `code`;
- a human-readable `message`;
- the proposal identifier;
- optional `field`.

### EB-049 — Initial Boundary Issue Codes

Initial boundary issue codes SHALL include:

```text
invalid_proposal_status
unknown_action
invalid_start_transition
invalid_completion_transition
inconsistent_result
```

### EB-050 — Issues Before Handler Invocation

Eligibility, registry and start-transition failures SHALL be represented as boundary issues.

They SHALL not create an `ExecutionResult` because the handler was not executed.

### EB-051 — Failures During Handler Invocation

Failures after entering the `executing` state SHALL be represented by a failed `ExecutionResult` and a transition to `failed`.

---

## 13. Execution Boundary Result

### EB-052 — Result Fields

The orchestration result SHALL contain:

- `success`;
- the current proposal;
- optional execution result;
- optional start transition;
- optional completion transition;
- zero or more execution-boundary issues.

### EB-053 — Successful Boundary Result

A successful boundary result SHALL contain:

- `success=true`;
- a final proposal in `succeeded`;
- a successful `ExecutionResult`;
- an `approved → executing` transition;
- an `executing → succeeded` transition;
- no boundary issues.

### EB-054 — Handled Execution Failure

A handled handler failure SHALL contain:

- `success=false`;
- a final proposal in `failed`;
- a failed `ExecutionResult`;
- an `approved → executing` transition;
- an `executing → failed` transition;
- no boundary issues.

A failed handler outcome is a completed execution workflow, not a boundary-policy error.

### EB-055 — Pre-Execution Boundary Failure

A failure before handler invocation SHALL contain:

- `success=false`;
- the unchanged original proposal;
- no `ExecutionResult`;
- no completion transition;
- one or more boundary issues.

A start transition SHALL not be returned if the transition failed.

### EB-056 — Result Consistency

Invalid orchestration-result construction SHALL raise `ActionContractError`.

### EB-057 — No Mixed Failure Representation

A result SHALL not represent the same failure simultaneously as both:

- a boundary issue; and
- an execution error.

Pre-invocation failures use boundary issues.

Invocation-time failures use `ExecutionError`.

---

## 14. Function Contract

### EB-058 — Execute Function

The initial execution function SHALL resemble:

```python
execute_action(
    proposal: ActionProposal,
    registry: ActionHandlerRegistry,
    *,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> ActionExecutionResult
```

The timestamp injection interface MAY be replaced with an injected clock callable if that produces a cleaner deterministic design.

### EB-059 — No Confirmation Evaluation

`execute_action()` SHALL NOT evaluate confirmation policy.

It SHALL rely only on the proposal’s current approved state.

### EB-060 — No Automatic Approval

`execute_action()` SHALL NOT approve, validate or confirm a proposal automatically.

### EB-061 — One Handler Invocation

For an eligible proposal and registered action, the handler SHALL be invoked exactly once.

### EB-062 — No Retry

The execution boundary SHALL not retry a failed handler during this milestone.

---

## 15. Serialisation

### EB-063 — JSON Conversion

Execution-boundary issues and orchestration results SHALL provide deterministic conversion to JSON-compatible dictionaries.

Existing `ExecutionError`, `ExecutionResult`, `ActionProposal` and `ActionTransition` serializers SHALL be reused.

### EB-064 — Enum Representation

Enums SHALL be represented using their string values.

### EB-065 — Timestamp Representation

Timestamps SHALL use ISO 8601 with explicit timezone information.

### EB-066 — Issue Collections

Issue tuples SHALL be serialised as JSON-compatible lists.

### EB-067 — No Python Internals

Serialised results SHALL not contain:

- callable objects;
- handler objects;
- registry objects;
- exception objects;
- tracebacks;
- dataclass internals;
- Python object representations.

---

## 16. Security Considerations

Explicit handler registration reduces accidental or model-directed access to arbitrary executable code.

The registry SHALL NOT accept action names from fuzzy or generative matching.

An approved proposal does not guarantee that:

- its parameters remain valid for the target domain;
- the handler is correctly implemented;
- the external service is trustworthy;
- the external effect can be reversed.

Handlers SHALL perform domain-specific validation immediately before acting.

Exception messages may contain sensitive data and SHALL not be copied automatically into normal execution results.

Persistent audit storage, handler permissions and process isolation require separate specifications.

---

## 17. Tests

Automated tests SHALL cover at least:

1. registration of a valid action handler;
2. lookup of a registered handler;
3. rejection of duplicate registration;
4. rejection of invalid action names;
5. unknown-action lookup;
6. execution rejection for every non-approved proposal status;
7. unknown action leaves the proposal approved;
8. unknown action does not invoke a handler;
9. approved proposal transitions to executing before invocation;
10. handler receives an executing proposal;
11. successful handler is invoked exactly once;
12. successful handler output is frozen;
13. successful execution result;
14. successful transition to `succeeded`;
15. handler exception containment;
16. failed execution result for a handler exception;
17. transition to `failed` after handler exception;
18. invalid handler-output containment;
19. original proposal remains unchanged;
20. start and completion transition timestamps;
21. timezone-aware start timestamp;
22. timezone-aware completion timestamp;
23. rejection of naive injected timestamps;
24. completion cannot precede start;
25. successful result consistency;
26. handled-failure result consistency;
27. pre-execution failure consistency;
28. deterministic issue serialisation;
29. deterministic orchestration-result serialisation;
30. absence of handler, registry and exception objects in serialised output;
31. no automatic validation, approval or confirmation;
32. no retry after handler failure.

---

## 18. Out of Scope

This specification does not define:

- automatic plugin discovery;
- dependency injection frameworks;
- async handlers;
- background queues;
- worker processes;
- execution timeouts;
- retries;
- rollback;
- compensation;
- distributed locks;
- idempotency keys;
- scheduled actions;
- recurring actions;
- persistent audit storage;
- authentication;
- role-based permissions;
- sandboxing;
- process isolation;
- network policy;
- rate limiting;
- secrets management;
- handler-specific schemas;
- user interfaces.

---

## 19. Success Criteria

This specification is satisfied when:

- handlers are registered explicitly;
- handler lookup is deterministic;
- only approved proposals may execute;
- unknown actions fail closed;
- approved proposals transition to executing before invocation;
- handler outcomes produce valid `ExecutionResult` records;
- successful execution transitions to succeeded;
- failed execution transitions to failed;
- handler exceptions are contained;
- the original proposal remains unchanged;
- timestamps are timezone-aware and canonical;
- serialisation is deterministic;
- no dynamic plugin discovery is introduced;
- no retry behaviour is introduced;
- all automated tests pass;
- Ruff, mypy and pytest pass through `scripts/check.sh`.

---

## 20. Future Considerations

Future specifications MAY introduce:

- plugin discovery;
- handler metadata;
- per-handler parameter schemas;
- authenticated handler permissions;
- execution timeouts;
- retries;
- idempotency;
- rollback and compensation;
- asynchronous execution;
- background workers;
- queues;
- recurring actions;
- process isolation;
- resource limits;
- audit persistence;
- execution receipts;
- external-effect verification;
- dry-run handlers;
- simulation mode;
- rate limiting;
- secrets injection.

---

## 21. References

- LEA-SPEC-0002 — Action Proposal Contract Specification
- LEA-SPEC-0003 — Action State Transition Specification
- LEA-SPEC-0004 — Confirmation and Approval Policy Specification
- RFC 2119 — Key words for use in RFCs to Indicate Requirement Levels
- RFC 8174 — Ambiguity of Uppercase vs Lowercase in RFC 2119 Key Words
