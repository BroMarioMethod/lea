---
schema_version: 1
document_id: LEA-SPEC-0018
document_type: specification
document_version: 1
title: "Calendar Collaboration and Recurring Events"
milestone: 4.1
status: proposed
---
# LEA-SPEC-0018 — Calendar Collaboration and Recurring Events

## Purpose

Milestone 4.1 extends the verified Milestone 4 calendar foundation with
recurring events and human collaboration while preserving explicit proposals,
approval, execution, auditability, provider isolation and Android acceptance.

## MVP scope

The MVP shall provide:

- recurring timed and all-day event authoring with validated recurrence rules;
- recurrence-aware show, modify and cancel operations;
- invitation and attendee records with stable participant identity;
- attendee response states (`needs-action`, `accepted`, `declined`,
  `tentative`);
- proposal-backed changes for event, recurrence and attendee mutations;
- explicit timezone and recurrence expansion semantics;
- CLI and Telegram parity for supported operations;
- synchronization and conflict diagnostics that never silently overwrite;
- DAVx⁵ acceptance for recurring and attendee changes;
- preservation of the Milestone 4 ownership, backup, restore and removal
  guarantees.

## Provider and security boundaries

The provider-neutral calendar contract remains authoritative. Provider-specific
recurrence or attendee extensions must be normalized or rejected explicitly.
No raw provider command is exposed through the CLI or Telegram.

Google Calendar OAuth and additional calendar providers may be developed as
beta integrations behind an explicit experimental feature boundary. They are
not part of the 4.1 MVP acceptance gate, must not weaken the local Radicale
path, and must not cause credentials or tokens to enter Git or ordinary logs.

## Non-goals

4.1 does not include public Radicale exposure, automatic VPN provisioning,
Gmail access, free/busy federation, bulk destructive operations, or Android
application installation. Free/busy federation is a candidate for 4.2.

## Proposal and execution rules

Interactive recurrence and attendee mutations are persistent proposals. Approval
never performs an external mutation. Execution is deterministic, idempotent
where the provider permits it, and records redaction-safe diagnostics. A stale
event or changed recurrence base must fail for operator review rather than
silently rewriting a different event.

## Acceptance criteria

4.1 is complete only when:

- recurrence rules validate and round-trip without timezone drift;
- recurring instances can be listed and shown deterministically;
- modify and cancel operations target the series or an explicit instance;
- attendee invitations and response states survive explicit synchronization;
- CLI and Telegram flows enforce the same policy and proposal boundaries;
- server-to-Android and Android-to-server recurring/attendee acceptance passes;
- conflicts and unsupported provider features fail safely with useful,
  redaction-safe diagnostics;
- backup/restore preserves recurrence and attendee data;
- the full automated gate and final physical test-card procedure pass;
- experimental OAuth/provider work is excluded from the release artifact unless
  separately approved as a beta build.

## Delivery slices

```text
4.1.1 recurrence domain contracts and iCalendar mapping
4.1.2 recurrence validation, expansion and timezone semantics
4.1.3 recurring-series and instance mutation proposals
4.1.4 attendee and response contracts
4.1.5 CLI and Telegram collaboration commands
4.1.6 synchronization and conflict diagnostics
4.1.7 DAVx⁵ recurring/attendee acceptance
4.1.8 backup, restore and regression hardening
4.1.9 final test-card and release verification
```
