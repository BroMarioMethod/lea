---
schema_version: 1
document_id: 4a2c1e2b-6d37-4a50-9f42-2f6fb94da801
document_type: project
document_version: 1
title: "Milestone 4.0 test-card acceptance and hardening"
sensitivity: medium
created_at: 2026-08-05T00:00:00Z
updated_at: 2026-08-06T00:00:00Z
links: []
external_references: []
---
# Milestone 4.0 test-card acceptance and hardening

## Accepted source state

- Branch: `milestone-4.0/calendar-provider`.
- Test-card acceptance source commit: `50b8bde8ee55c2c3cd5d2cf03d2073caa2f1bc47`.
- The branch was pushed and the final test-card rerun was verified at this exact commit.
- This document intentionally contains no credentials, bcrypt verifiers, event
  identifiers or device identifiers.

## Live acceptance completed

The Raspberry Pi test card completed these observed checks:

- managed khal and vdirsyncer repair, health and disposable lifecycle;
- Radicale 3.5.4 activation on a private-LAN address;
- authenticated access and reciprocal denial between two test accounts;
- explicit collection discovery and synchronization;
- server-to-Android propagation through DAVx5 with the expected local time;
- Android-to-server propagation verified through both calendar event listing
  and single-event inspection;
- a stopped-service, ownership-preserving backup;
- isolated restore into a staging root;
- restored Radicale health, authentication and reciprocal isolation;
- fresh synchronization from restored storage with both acceptance events
  present; and
- creation of the credential-free Android acceptance record.
- final clean fresh-install and exact pinned provider provisioning;
- post-reboot service enablement, runtime recreation and two-way sync;
- idempotent supported upgrade verification; and
- supported Radicale removal followed by managed LEA purge, with source and
  release assets preserved.

The live acceptance record and protected backup remain on the test card. They
are operational evidence and must not be committed to Git.

## Implemented findings

### 1. Reproducible Radicale supply chain

The branch now contains a reviewed, pinned Radicale 3.5.4 distribution lock,
exact release hash and installation record.

### 2. Supported deployment entry point

The public `lea calendar-provider install`, `bootstrap`, `backup`,
`restore-isolated` and `remove` commands provide the supported workflow.

### 3. Root-run ownership

Root-run provisioning applies and verifies owner, group, mode and effective
`lea` readability before activation, with regression coverage.

### 4. Service readiness race

Service readiness uses bounded probing with redaction-safe diagnostics.

### 5. First-collection bootstrap

First collection creation is an explicit, approved, non-interactive bootstrap.

### 6. Action diagnostics

Provider failures retain redaction-safe phase, exit and issue information.

### 7. Backup safety

Backup tooling creates credential-bearing archives as root:root 0600 before the
first write, preserves ownership and modes, and verifies isolated restore.

## Required development slices

1. Define pinned Radicale release-asset and installer contracts.
2. Add the supported Radicale and CalDAV deployment command.
3. Correct ownership and transactional activation.
4. Add bounded service readiness inspection.
5. Add explicit non-interactive collection bootstrap.
6. Preserve redaction-safe provider diagnostics.
7. Add secure backup and isolated-restore tooling.
8. Add regression tests for every live finding.
9. Add a credential-free Milestone 4.0 release checklist and acceptance report.
10. Run the complete repository quality gate.
11. Repeat clean install, repair, reboot persistence, two-way synchronization,
    reciprocal isolation and isolated restore on the test card before merge.

## Final verification and merge rule

The complete quality gate passed with 2525 tests passed and 7 environment-
appropriate skips. The final live test-card rerun is documented on the exact
commit above without secret or event-identity material. Maintainers must still
review the commit and complete organization-required CI and PR checks before
merging or tagging Milestone 4.0.

A distinct live replacement rollback was not fabricated because no second
supported calendar version was available; replacement rollback behavior is
covered by automated tests.
