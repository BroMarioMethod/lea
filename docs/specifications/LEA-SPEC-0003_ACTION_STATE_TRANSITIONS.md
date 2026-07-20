---
title: Action State Transition Specification
document_id: LEA-SPEC-0003
version: 0.1.2
status: Accepted
authors:
  - Marius du Preez
  - OpenAI ChatGPT
license: GPL-3.0-only
created: 2026-07-18
last_updated: 2026-07-20
review_required: false
---

# Action State Transition Specification

## Document Status

| Item | Value |
|---|---|
| Status | Accepted |
| Requires Review | No |
| Implementation | Complete |
| Test Status | Automated Tests Passing |

---

## 1. Purpose

This specification defines the deterministic policy governing state transitions for LEA action proposals.

A state transition records workflow progress. It does not execute the proposed action, grant permission, or confirm that a real-world change occurred.

The implementation SHALL provide:

- an explicit transition policy;
- deterministic transition validation;
- immutable creation of transitioned proposals;
- terminal-state protection;
- structured transition errors;
- transition metadata suitable for logging and future auditing.

---

## 2. Why?

LEA-SPEC-0002 defines the available proposal states but does not define which transitions are legal.

Without an explicit transition policy, application code could accidentally perform nonsensical or unsafe changes such as:

```text
proposed → succeeded
rejected → executing
failed → approved
```

A central deterministic policy prevents each workflow or plugin from inventing its own lifecycle behaviour.

---

## 3. Scope

This specification defines:

- legal state transitions;
- invalid-transition reporting;
- terminal states;
- transition records;
- immutable proposal updates;
- transition timestamps;
- transition reasons;
- side-effect-free transition behaviour;
- automated tests.

This specification does not define:

- action execution;
- confirmation interfaces;
- approval permissions;
- adaptive confidence;
- plugin handlers;
- workflow orchestration;
- persistent audit storage;
- retries;
- rollback or compensation;
- transition authentication.

---

## 4. Engineering Principles

### EP-001 — State Is Not Execution

Changing a proposal state SHALL NOT execute its action.

### EP-002 — Explicit Policy

All permitted state transitions SHALL be defined centrally in deterministic code.

### EP-003 — Immutable History

A transition SHALL create a new proposal record.

The original proposal SHALL remain unchanged.

### EP-004 — Terminal Protection

Terminal states SHALL not transition to another state under the initial policy.

### EP-005 — No Implicit Skipping

Intermediate lifecycle stages SHALL not be skipped unless explicitly permitted by this specification.

### EP-006 — Auditable Intent

Each successful transition SHALL produce a structured transition record containing its origin, destination and timestamp.

---

## 5. Core Data Structures

The implementation SHALL provide:

```text
ActionTransition
TransitionResult
TransitionIssue
```

The implementation SHALL also provide deterministic functions resembling:

```python
can_transition(current: ActionStatus, target: ActionStatus) -> bool

transition_proposal(
    proposal: ActionProposal,
    target: ActionStatus,
    reason: str | None = None,
) -> TransitionResult
```

These names MAY be refined during implementation provided the observable contract remains unchanged.

---

## 6. Lifecycle Policy

### ST-001 — Standard Successful Path

The standard lifecycle SHALL be:

```text
proposed
    ↓
validated
    ↓
awaiting_confirmation
    ↓
approved
    ↓
executing
    ↓
succeeded
```

### ST-002 — Rejection Path

The following transition SHALL be permitted:

```text
proposed → rejected
validated → rejected
awaiting_confirmation → rejected
```

An approved or executing proposal SHALL NOT transition to `rejected`.

### ST-003 — Confirmation Bypass

A validated proposal MAY transition directly to `approved` when deterministic policy has established that confirmation is unnecessary.

Permitted:

```text
validated → approved
```

This specification does not define the policy that grants such approval.

### ST-004 — Cancellation

The following transitions SHALL be permitted:

```text
awaiting_confirmation → cancelled
approved → cancelled
```

A proposal SHALL NOT be cancelled after execution has begun.

### ST-005 — Execution Failure

The following transition SHALL be permitted:

```text
executing → failed
```

### ST-006 — Terminal States

The initial terminal states SHALL be:

```text
rejected
succeeded
failed
cancelled
```

Terminal states SHALL have no outgoing transitions.

### ST-007 — Self-Transitions

A proposal SHALL NOT transition to its current state.

Example:

```text
validated → validated
```

SHALL be rejected.

### ST-008 — Initial State

A proposal in `proposed` state MAY transition only to:

```text
validated
rejected
```

### ST-009 — Validated State

A proposal in `validated` state MAY transition only to:

```text
awaiting_confirmation
approved
rejected
```

### ST-010 — Awaiting Confirmation State

A proposal in `awaiting_confirmation` state MAY transition only to:

```text
approved
rejected
cancelled
```

### ST-011 — Approved State

A proposal in `approved` state MAY transition only to:

```text
executing
cancelled
```

### ST-012 — Executing State

A proposal in `executing` state MAY transition only to:

```text
succeeded
failed
```

---

## 7. Transition Record

### ST-013 — Action Transition

A successful transition SHALL produce an immutable `ActionTransition` record containing:

- `proposal_id`;
- `from_status`;
- `to_status`;
- `transitioned_at`;
- optional `reason`.

### ST-014 — Timestamp

`transitioned_at` SHALL be timezone-aware.

New timestamps SHALL default to UTC.

Naive timestamps SHALL be rejected.

### ST-014A — Time-Zone Presentation

Transition timestamps SHALL be stored and serialised in UTC with explicit
timezone information.

When a timestamp is presented to a user through diagnostics, reports or a user
interface, LEA SHOULD convert it to the user's configured local time zone.

Localisation SHALL affect presentation only. It SHALL NOT alter the canonical
UTC timestamp or the recorded instant.

When the user's time zone is unavailable, LEA SHALL present the UTC timestamp
and identify it as UTC.

### ST-015 — Transition Reason

A transition reason MAY contain a concise human-readable explanation.

The reason SHALL NOT be treated as executable input or authorisation.

### ST-016 — Identifier Consistency

The transition record’s `proposal_id` SHALL match the proposal being transitioned.

### ST-017 — Serialisation

`ActionTransition` SHALL provide deterministic conversion to a JSON-compatible dictionary.

Enums SHALL be represented by their string values.

The timestamp SHALL use ISO 8601 format.

---

## 8. Transition Result

### ST-018 — Successful Result

A successful transition result SHALL contain:

- `success=true`;
- the newly created proposal;
- the transition record;
- no issues.

### ST-019 — Failed Result

A failed transition result SHALL contain:

- `success=false`;
- the original proposal;
- no transition record;
- at least one transition issue.

### ST-020 — Transition Issue

A transition issue SHALL contain:

- a stable machine-readable `code`;
- a human-readable `message`;
- `from_status`;
- `to_status`.

The initial issue codes SHALL include:

```text
invalid_transition
terminal_state
self_transition
```

### ST-021 — Result Consistency

A successful result SHALL contain a transition record and no issues.

A failed result SHALL contain at least one issue and no transition record.

---

## 9. Proposal Update Behaviour

### ST-022 — Immutable Proposal Update

A successful transition SHALL create a new `ActionProposal` with the target status.

All other proposal fields SHALL remain unchanged.

The original proposal SHALL not be modified.

### ST-023 — Proposal Identifier

The transitioned proposal SHALL preserve the original `proposal_id`.

### ST-024 — Creation Timestamp

The transitioned proposal SHALL preserve the original `created_at` value.

The transition timestamp SHALL be stored in `ActionTransition`, not by replacing `created_at`.

### ST-025 — Parameters

Proposal parameters SHALL remain deeply immutable and unchanged during state transition.

### ST-026 — No Side Effects

Transition evaluation SHALL NOT:

- execute the action;
- invoke plugins;
- access the network;
- write files;
- obtain user confirmation;
- change external state;
- mutate the supplied proposal.

---

## 10. Transition Table

The initial permitted transition table SHALL be:

| Current State | Permitted Target States |
|---|---|
| `proposed` | `validated`, `rejected` |
| `validated` | `awaiting_confirmation`, `approved`, `rejected` |
| `awaiting_confirmation` | `approved`, `rejected`, `cancelled` |
| `approved` | `executing`, `cancelled` |
| `executing` | `succeeded`, `failed` |
| `rejected` | none |
| `succeeded` | none |
| `failed` | none |
| `cancelled` | none |

This table SHALL be the canonical initial policy.

---

## 11. Error Behaviour

### ST-027 — Invalid Transition

A transition not listed in the canonical transition table SHALL fail deterministically.

### ST-028 — Terminal-State Error

An attempted transition from a terminal state SHALL produce the issue code:

```text
terminal_state
```

### ST-029 — Self-Transition Error

An attempted transition to the current state SHALL produce the issue code:

```text
self_transition
```

### ST-030 — General Invalid Transition

Other disallowed transitions SHALL produce the issue code:

```text
invalid_transition
```

### ST-031 — Exceptions

Normal policy rejection SHOULD be represented by `TransitionResult`, not by raising an exception.

Invalid construction of transition records or internally inconsistent result objects SHALL raise `ActionContractError`.

---

## 12. Security Considerations

A legal transition does not prove:

- that a user is authorised;
- that confirmation occurred;
- that the proposal is semantically safe;
- that the action handler is trusted;
- that external execution succeeded.

Future workflow and permission policies SHALL establish those conditions separately.

A proposal identifier SHALL not be treated as authentication.

Transition reasons MAY contain sensitive text and SHOULD be handled carefully in future audit logs.

---

## 13. Tests

Automated tests SHALL cover at least:

1. every permitted transition;
2. every state’s disallowed transitions;
3. self-transition rejection;
4. terminal-state rejection;
5. preservation of proposal identity;
6. preservation of parameters;
7. preservation of creation timestamp;
8. immutability of the original proposal;
9. creation of the new proposal;
10. timezone-aware transition timestamps;
11. rejection of naive transition timestamps;
12. successful result consistency;
13. failed result consistency;
14. transition issue immutability;
15. transition-record serialisation;
16. side-effect-free operation;
17. deterministic transition-table behaviour.

---

## 14. Out of Scope

This specification does not define:

- who may approve proposals;
- whether confirmation is required;
- how confidence affects confirmation;
- action handlers;
- execution retries;
- persistence;
- rollback;
- audit-log storage;
- proposal expiration;
- concurrency control;
- distributed locking;
- workflow correlation.

---

## 15. Success Criteria

This specification is satisfied when:

- the canonical transition table exists;
- permitted transitions succeed;
- invalid transitions return structured issues;
- terminal states cannot transition;
- proposals are replaced rather than mutated;
- transition records are immutable and serialisable;
- transitions cause no action-execution side effects;
- all automated tests pass;
- Ruff, mypy and pytest pass through `scripts/check.sh`.

---

## 16. Future Considerations

Future specifications MAY introduce:

- approval records;
- confirmation records;
- authorised transition actors;
- proposal expiration;
- retries from failed states;
- cancellation during execution;
- compensation workflows;
- transition persistence;
- optimistic concurrency;
- state-transition events;
- audit signatures;
- workflow-engine integration.
- user time-zone configuration;
- localised diagnostic timestamp presentation;

---

## 17. References

- LEA-SPEC-0002 — Action Proposal Contract Specification
- RFC 2119 — Key words for use in RFCs to Indicate Requirement Levels
- RFC 8174 — Ambiguity of Uppercase vs Lowercase in RFC 2119 Key Words
