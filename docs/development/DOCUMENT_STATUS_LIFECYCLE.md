# LEA Document Status Lifecycle

## Purpose

This document defines the lifecycle terminology used by LEA standards,
specifications, architecture decisions and operational documentation.

Document status, implementation progress and verification evidence are separate
concerns. A document must not use its lifecycle status as a substitute for
implementation or test status.

## Document lifecycle statuses

LEA uses the following document statuses:

| Status | Meaning |
|---|---|
| Proposed | Draft content that has not yet been accepted as governing project direction. |
| Accepted | Approved project direction and the current normative basis for implementation. |
| Superseded | Replaced by a newer accepted document or decision. |
| Rejected | Considered but explicitly not accepted. |

`Complete`, `Completed`, `Implemented` and `Verified` are not document lifecycle
statuses.

## Implementation statuses

Where useful, a document may report implementation separately using:

| Status | Meaning |
|---|---|
| Not Started | No implementation work has begun. |
| In Progress | Some required behaviour exists, but the documented scope is incomplete. |
| Implemented | The documented implementation scope exists in code or operational assets. |

Implementation status does not prove that the implementation has passed its
required acceptance procedure.

## Verification statuses

Where useful, a document may report verification separately using:

| Status | Meaning |
|---|---|
| Not Tested | No relevant verification evidence exists. |
| Partially Verified | Some documented behaviours have passed, but required coverage remains. |
| Verified | All required acceptance evidence for the declared scope has passed. |

A verification statement should identify the tested profile and any excluded or
deferred behaviour.

## Required interpretation

A specification with:

```text
Document Status: Accepted
Implementation: In Progress
Verification: Partially Verified
```

is valid and unambiguous:

- the specification governs current development;
- implementation is incomplete;
- some acceptance evidence exists.

A document must not be marked `Verified` solely because automated unit tests
pass. Verification must match the document's declared acceptance criteria.

## Historical terminology

Existing documents may contain older terminology while they are being
normalised. When such documents are edited, their metadata and status tables
should be updated to follow this lifecycle.
