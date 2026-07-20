---
title: Confirmation and Approval Policy Specification
document_id: LEA-SPEC-0004
version: 0.1.2
status: Accepted
authors:
  - Marius du Preez
  - OpenAI ChatGPT
license: GPL-3.0-only
created: 2026-07-20
last_updated: 2026-07-20
review_required: false
---

# Confirmation and Approval Policy Specification

## Document Status

| Item | Value |
|---|---|
| Status | Accepted |
| Requires Review | No |
| Implementation | Complete |
| Test Status | Automated Testing Passing |

---

## 1. Purpose

This specification defines the deterministic policy LEA uses to decide whether an action proposal requires explicit human confirmation.

It also defines immutable records for approval, rejection and confirmation-policy decisions.

Approval permits a proposal to continue through the workflow. It does not execute the proposed action.

---

## 2. Why?

LEA-SPEC-0002 defines risk levels and confirmation policies.

LEA-SPEC-0003 defines legal proposal-state transitions.

Neither specification defines:

- when confirmation is required;
- when confirmation may be bypassed;
- which safety rules override proposal preferences;
- what constitutes an approval or rejection;
- how confirmation decisions are recorded.

Without a central policy, individual workflows or integrations could apply inconsistent safety rules.

---

## 3. Scope

This specification defines:

- deterministic confirmation-policy evaluation;
- hard risk overrides;
- confirmation requirements;
- approval records;
- rejection records;
- decision actors;
- decision timestamps;
- immutable proposal-state updates;
- structured policy issues;
- serialisation requirements;
- automated tests.

This specification does not define:

- user-interface design;
- Telegram confirmation messages;
- authentication;
- permissions;
- adaptive confidence calculations;
- action execution;
- plugin handlers;
- persistent audit storage;
- notification delivery;
- approval expiry;
- multi-user voting.

---

## 4. Engineering Principles

### EP-001 — Approval Is Not Execution

Approval SHALL permit workflow progression only.

Approval SHALL NOT execute an action.

### EP-002 — Human Safety Override

High-risk and critical-risk proposals SHALL require explicit human confirmation regardless of a proposal’s confirmation-policy preference.

### EP-003 — Deterministic Policy

Confirmation requirements SHALL be calculated by deterministic code.

AI output SHALL NOT decide whether its own proposal requires confirmation.

### EP-004 — Explicit Human Decision

Where confirmation is required, workflow progression SHALL pause until a human decision is recorded.

### EP-005 — Immutable Records

Confirmation-policy decisions and human approval decisions SHALL be immutable.

### EP-006 — Auditable Decisions

Every confirmation-policy evaluation and human decision SHALL produce structured records suitable for future audit storage.

### EP-007 — Conservative Failure

When policy inputs are missing, inconsistent or unsupported, LEA SHALL favour confirmation rather than silent progression.

---

## 5. Core Data Structures

The initial implementation SHALL provide:

```text
ConfirmationRequirement
ConfirmationDecision
ConfirmationEvaluation
ConfirmationRecord
ConfirmationIssue
```

The implementation SHALL provide deterministic functions resembling:

```python
evaluate_confirmation(
    proposal: ActionProposal,
) -> ConfirmationEvaluation
```

and:

```python
record_confirmation(
    proposal: ActionProposal,
    decision: ConfirmationDecision,
    actor: str,
    reason: str | None = None,
) -> ConfirmationRecord
```

Names MAY be refined during implementation provided the observable contract remains unchanged.

---

## 6. Confirmation Requirement

### CP-001 — Requirement Values

The initial confirmation requirements SHALL be:

```text
not_required
required
```

### CP-002 — Decision Values

The initial human confirmation decisions SHALL be:

```text
approved
rejected
cancelled
```

### CP-003 — Deterministic Evaluation

Confirmation evaluation SHALL consider:

- proposal risk level;
- proposal confirmation policy;
- proposal status.

It SHALL NOT consider model confidence during this milestone.

### CP-004 — Policy Hierarchy

Confirmation policy SHALL be evaluated in this order:

1. hard safety overrides;
2. explicit confirmation policy;
3. risk-based policy.

A lower-priority rule SHALL NOT weaken a higher-priority rule.

---

## 7. Canonical Confirmation Matrix

The initial policy matrix SHALL be:

| Risk Level | `never` | `when_required` | `always` |
|---|---|---|---|
| `low` | not required | not required | required |
| `medium` | not required | required | required |
| `high` | required | required | required |
| `critical` | required | required | required |

This table SHALL be the canonical initial confirmation policy.

### CP-005 — Low Risk

Low-risk proposals SHALL require confirmation only when their confirmation policy is `always`.

### CP-006 — Medium Risk

Medium-risk proposals SHALL:

- not require confirmation under `never`;
- require confirmation under `when_required`;
- require confirmation under `always`.

### CP-007 — High Risk

High-risk proposals SHALL always require explicit human confirmation.

The `never` policy SHALL NOT bypass this rule.

### CP-008 — Critical Risk

Critical-risk proposals SHALL always require explicit human confirmation.

No confirmation policy SHALL bypass this rule.

### CP-009 — Always Policy

`ConfirmationPolicy.ALWAYS` SHALL require explicit confirmation for every risk level.

### CP-010 — Never Policy

`ConfirmationPolicy.NEVER` SHALL permit confirmation bypass only for:

```text
low
medium
```

It SHALL NOT bypass high-risk or critical-risk confirmation.

### CP-011 — When Required Policy

`ConfirmationPolicy.WHEN_REQUIRED` SHALL require confirmation for:

```text
medium
high
critical
```

It SHALL not require confirmation for low-risk proposals.

---

## 8. Eligible Proposal States

### CP-012 — Evaluation State

Confirmation policy SHALL be evaluated only for proposals in:

```text
validated
```

Other proposal states SHALL produce a structured policy issue.

### CP-013 — Confirmation Required Result

When confirmation is required, the proposal SHALL be eligible to transition:

```text
validated → awaiting_confirmation
```

### CP-014 — Confirmation Not Required Result

When confirmation is not required, the proposal SHALL be eligible to transition:

```text
validated → approved
```

This transition records deterministic policy approval, not human approval.

### CP-015 — Awaiting Confirmation Decisions

A proposal in `awaiting_confirmation` MAY receive one of the following human decisions:

```text
approved
rejected
cancelled
```

These decisions SHALL correspond to the legal transitions defined by LEA-SPEC-0003.

---

## 9. Confirmation Evaluation

### CP-016 — Evaluation Record

A confirmation evaluation SHALL contain:

- `proposal_id`;
- `risk_level`;
- `confirmation_policy`;
- `requirement`;
- `evaluated_at`;
- a machine-readable `reason_code`;
- a human-readable explanation.

### CP-017 — Reason Codes

Initial reason codes SHALL include:

```text
policy_always
low_risk_not_required
medium_risk_required
medium_risk_never
high_risk_override
critical_risk_override
invalid_proposal_status
```

### CP-018 — Timestamp

`evaluated_at` SHALL be timezone-aware and stored in UTC.

### CP-019 — Time-Zone Presentation

When evaluation timestamps are presented to users, LEA SHOULD convert them to the user’s configured local time zone.

Localisation SHALL not alter the canonical UTC timestamp.

When no user time zone is available, LEA SHALL display the timestamp as UTC and identify it as UTC.

### CP-020 — Evaluation Purity

Confirmation evaluation SHALL NOT:

- mutate the proposal;
- transition the proposal automatically;
- execute the action;
- invoke plugins;
- access the network;
- write files;
- request user input;
- modify external state.

---

## 10. Human Confirmation Record

### CP-021 — Confirmation Record Fields

A human confirmation record SHALL contain:

- `proposal_id`;
- `decision`;
- `actor`;
- `decided_at`;
- optional `reason`.

### CP-022 — Actor

The `actor` field SHALL identify the human or authenticated user responsible for the decision.

It SHALL be a non-empty string.

The actor identifier SHALL not by itself prove authentication.

### CP-023 — Human Decisions

A human decision SHALL use one of:

```text
approved
rejected
cancelled
```

### CP-024 — Approval

An approved decision SHALL allow:

```text
awaiting_confirmation → approved
```

### CP-025 — Rejection

A rejected decision SHALL allow:

```text
awaiting_confirmation → rejected
```

### CP-026 — Cancellation

A cancelled decision SHALL allow:

```text
awaiting_confirmation → cancelled
```

### CP-027 — Decision Reason

A reason MAY contain a concise human-readable explanation.

It SHALL not be treated as executable input.

### CP-028 — Decision Timestamp

`decided_at` SHALL be timezone-aware and stored in UTC.

Naive timestamps SHALL be rejected.

### CP-029 — Presentation Localisation

User-facing displays SHOULD convert decision timestamps to the user’s configured local time zone while preserving the canonical UTC instant.

---

## 11. Confirmation Result

### CP-030 — Successful Evaluation

A successful confirmation evaluation SHALL contain:

- `success=true`;
- a confirmation evaluation record;
- no issues.

### CP-031 — Failed Evaluation

A failed confirmation evaluation SHALL contain:

- `success=false`;
- no evaluation record;
- one or more confirmation issues.

### CP-032 — Confirmation Issue

A confirmation issue SHALL contain:

- machine-readable `code`;
- human-readable `message`;
- `proposal_id`;
- optional `field`.

### CP-033 — Initial Issue Codes

Initial confirmation issue codes SHALL include:

```text
invalid_proposal_status
invalid_actor
invalid_decision
invalid_timestamp
inconsistent_result
```

### CP-034 — Result Consistency

A successful result SHALL contain an evaluation record and no issues.

A failed result SHALL contain at least one issue and no evaluation record.

Invalid record construction SHALL raise `ActionContractError`.

---

## 12. Applying Confirmation Policy

### CP-035 — Explicit Application

Policy evaluation SHALL not transition a proposal by itself.

A separate deterministic function MAY apply the evaluation result through the transition policy.

### CP-036 — No-Confirmation Path

When confirmation is not required, application of the policy SHALL create:

- a transitioned proposal in `approved` state;
- an action-transition record;
- the confirmation-evaluation record.

### CP-037 — Confirmation-Required Path

When confirmation is required, application of the policy SHALL create:

- a transitioned proposal in `awaiting_confirmation` state;
- an action-transition record;
- the confirmation-evaluation record.

### CP-038 — Human Decision Application

Applying a human confirmation decision SHALL create:

- a new proposal with the corresponding state;
- an action-transition record;
- a confirmation record.

### CP-039 — Original Proposal

The original proposal SHALL remain unchanged.

### CP-040 — Side Effects

Applying confirmation policy or recording a human decision SHALL NOT execute the proposed action.

---

## 13. Serialisation

### CP-041 — JSON Conversion

All confirmation-policy records SHALL provide deterministic conversion to JSON-compatible dictionaries.

### CP-042 — Enum Representation

Enums SHALL be represented using their string values.

### CP-043 — Timestamp Representation

Timestamps SHALL be represented in ISO 8601 format with explicit UTC timezone information.

### CP-044 — No Python Internals

Serialised records SHALL not contain:

- enum implementation details;
- dataclass internals;
- Python object representations;
- executable objects;
- tracebacks.

---

## 14. Security Considerations

A confirmation record does not by itself prove that the actor was authenticated.

Authentication and permission checks SHALL be defined separately.

A confirmation decision SHALL not:

- execute an action;
- bypass handler validation;
- bypass domain permissions;
- replace action-result verification.

High-risk and critical-risk confirmation requirements are hard safety rules in the initial policy.

Future adaptive confidence SHALL NOT bypass critical-risk human confirmation unless an explicit later specification changes that rule.

Confirmation reasons may contain sensitive information and SHOULD be protected in future audit storage.

---

## 15. Tests

Automated tests SHALL cover at least:

1. every cell in the canonical confirmation matrix;
2. low-risk `never`;
3. low-risk `when_required`;
4. low-risk `always`;
5. medium-risk `never`;
6. medium-risk `when_required`;
7. high-risk override of `never`;
8. critical-risk override of `never`;
9. `always` across every risk level;
10. invalid proposal-state evaluation;
11. immutable evaluation records;
12. UTC-aware evaluation timestamps;
13. rejection of naive timestamps;
14. successful result consistency;
15. failed result consistency;
16. approval record creation;
17. rejection record creation;
18. cancellation record creation;
19. rejection of empty actor identifiers;
20. preservation of the original proposal;
21. transition to `approved` when confirmation is unnecessary;
22. transition to `awaiting_confirmation` when confirmation is required;
23. application of approved human decisions;
24. application of rejected human decisions;
25. application of cancelled human decisions;
26. deterministic serialisation;
27. absence of action-execution side effects.

---

## 16. Out of Scope

This specification does not define:

- user authentication;
- user roles;
- permission scopes;
- Telegram buttons;
- command-line prompts;
- approval expiry;
- multiple approvers;
- delegated approval;
- confidence scoring;
- automatic learning;
- action execution;
- plugin handlers;
- persistent audit storage;
- cryptographic signatures;
- notifications.

---

## 17. Success Criteria

This specification is satisfied when:

- the canonical confirmation matrix exists;
- high-risk and critical-risk proposals always require confirmation;
- confirmation decisions are deterministic;
- human decisions are immutable and structured;
- proposal transitions follow LEA-SPEC-0003;
- the original proposal remains unchanged;
- timestamps are UTC-aware;
- serialisation is deterministic;
- no action execution is introduced;
- all automated tests pass;
- Ruff, mypy and pytest pass through `scripts/check.sh`.

---

## 18. Future Considerations

Future specifications MAY introduce:

- adaptive confidence;
- trusted automation thresholds;
- authenticated actors;
- role-based approval;
- delegated approval;
- multiple approvers;
- approval expiry;
- confirmation reminders;
- confirmation through Telegram;
- signed approval records;
- persistent audit storage;
- per-action confirmation overrides;
- user-configurable time zones;
- localised confirmation displays.

---

## 19. References

- LEA-SPEC-0002 — Action Proposal Contract Specification
- LEA-SPEC-0003 — Action State Transition Specification
- RFC 2119 — Key words for use in RFCs to Indicate Requirement Levels
- RFC 8174 — Ambiguity of Uppercase vs Lowercase in RFC 2119 Key Words
