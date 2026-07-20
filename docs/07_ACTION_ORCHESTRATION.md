# Action Orchestration Service

LEA's action orchestration service coordinates the existing deterministic
proposal, validation, confirmation, execution and audit components. It does not
replace those contracts; it calls them in a controlled application workflow.

## Public service

```python
from lea.orchestration import ActionOrchestrator

orchestrator = ActionOrchestrator(
    registry,
    audit_sink,
    clock,
    audit_event_id_source,
)
```

Dependencies are explicit:

- `ActionHandlerRegistry`;
- an append-only audit sink;
- a timezone-aware UTC clock;
- a canonical audit-event UUID source.

The orchestrator does not select filesystem paths, read environment variables,
discover plugins, communicate with users or call AI models.

## Lifecycle

The workflow is deliberately split into three operations:

```text
submit
→ confirm, when required
→ execute, when approved
```

Submission cannot silently execute an action. Confirmation cannot silently
become execution.

## Submission

```python
result = orchestrator.submit(proposal)
```

Submission performs:

1. canonical proposal serialisation;
2. deterministic proposal validation;
3. proposal-created audit persistence;
4. validation-completed audit persistence;
5. transition from `proposed` to `validated`;
6. validation-transition audit persistence;
7. confirmation-policy application;
8. confirmation-policy audit persistence.

A valid low-risk proposal may progress:

```text
proposed → validated → approved
```

A proposal requiring confirmation progresses:

```text
proposed → validated → awaiting_confirmation
```

High- and critical-risk proposals are never automatically approved.

Submission never invokes an action handler.

## Confirmation

```python
result = orchestrator.confirm(
    proposal,
    decision,
    actor,
    reason="Optional human reason",
)
```

Confirmation accepts an explicit human decision, records the actor, obtains the
decision timestamp from the injected UTC clock, applies the existing
confirmation-decision contract and persists one composite
`confirmation_decision_applied` audit event.

Successful outcomes are:

```text
approved
rejected
cancelled
```

Confirmation never invokes an action handler.

## Execution

```python
result = orchestrator.execute(proposal)
```

Execution obtains explicit start and completion timestamps, calls the existing
approved-only execution boundary, invokes the exact registered handler and
persists one composite execution audit event.

Successful execution progresses:

```text
approved → executing → succeeded
```

A handled execution failure progresses:

```text
approved → executing → failed
```

Any non-approved proposal is rejected before handler invocation.

## Structured outcomes

Stable orchestration outcomes include:

```text
submitted
validation_failed
confirmation_required
approved
rejected
cancelled
execution_succeeded
execution_failed
audit_failed
invalid_operation
```

Each public operation returns an immutable result containing the resulting
proposal, relevant lower-level workflow result, successfully persisted audit
events and a structured issue where applicable.

## Deterministic dependencies

### UTC clock

The clock must return a timezone-aware UTC `datetime`.

Naive datetimes, non-UTC values and non-datetime values fail closed. Public
orchestration methods do not call the system clock directly.

### Audit-event identifier source

The identifier source must return canonical lower-case UUID strings.

Invalid, non-string or non-canonical values fail closed before the related
audit event reaches the sink. Public orchestration methods do not generate
random audit-event identifiers directly.

### Audit sink

The minimum contract is:

```python
def append(event: AuditEvent) -> object:
    ...
```

The return value is ignored.

Both `JsonlAuditStore` and `IntegrityJsonlAuditStore` satisfy this contract. An
in-memory test double may also be used.

## Audit ordering

Submission persists:

```text
proposal_created
validation_completed
transition_completed
confirmation_policy_applied
```

Confirmation persists one composite event:

```text
confirmation_decision_applied
```

Execution persists one composite event:

```text
execution_completed
```

Composite events already contain their canonical lower-level records and
transitions. The orchestrator avoids duplicate audit representations.

## Partial audit persistence

A multi-event submission may persist a valid prefix before a later append
fails. The returned `persisted_events` tuple contains only events whose sink
call completed successfully.

For example:

```text
proposal_created         persisted
validation_completed     persisted
transition_completed     failed
```

The result reports exactly the first two events.

The orchestrator does not retry, overwrite or repair audit history.

## Audit failure after side effects

An execution handler can complete an external side effect before the later
audit append fails.

In that case:

- the deterministic execution result is preserved;
- the resulting proposal may already be `succeeded` or `failed`;
- the orchestration outcome is `audit_failed`;
- no claim is made that the audit event was persisted;
- the failure is exposed through a structured orchestration issue.

## No cross-system atomicity

Milestone 1.7 does not provide one transaction spanning proposal values, audit
persistence, handler side effects, external databases or external APIs.

The current design cannot roll back an irreversible external action when a
later audit append fails.

Future runtime work may require idempotency keys, durable job records,
transactional outboxes, compensating actions, retry policies, side-effect
reconciliation and a dedicated runtime coordinator.

## Error containment

Expected workflow failures are returned as structured results.

Handler exceptions remain contained by the existing execution boundary.
Unexpected clock, identifier-source and audit-sink failures are converted into
stable orchestration issues. Sensitive exception text is not copied directly
into public messages.

## AI and adapters

AI output remains outside the deterministic orchestration core.

A model or user-interface adapter may propose an `ActionProposal`, but it
cannot bypass canonical validation, confirmation policy, explicit human
confirmation, approved-only execution or audit persistence.

Messaging, command-line, Telegram and LAN adapters should call the orchestrator
rather than reproduce workflow rules.

## Current limitations

The orchestration service does not provide:

- background workers or queues;
- scheduling;
- automatic retries;
- plugin discovery;
- persistent proposal repositories;
- multi-process coordination;
- distributed locking;
- side-effect rollback;
- cross-system transactions;
- autonomous approval;
- direct AI inference;
- user-interface interaction.
