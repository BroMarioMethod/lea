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

## Lessons, causes and prevention controls

The following table preserves the operational lessons from the test-card run.
Each prevention item is enforced by the implementation, a regression test, or
the documented operator workflow.

| Lesson / observed bug | Cause | Intervention | Future prevention |
| --- | --- | --- | --- |
| A release candidate could not be reproduced safely. | Radicale and Taskwarrior inputs were not initially represented as reviewed, exact release assets. | Added canonical archives/locks, exact SHA-256 records and pinned installation metadata. | Installation rejects missing, unpinned, unhashed or mismatched inputs. |
| Provider setup required a temporary script. | Radicale/CalDAV orchestration existed only behind library boundaries. | Added supported public `lea calendar-provider install`, `bootstrap`, `backup`, `restore-isolated` and `remove` commands. | Runbook and CLI contract tests exercise the supported operator path. |
| Root-created credentials were unreadable by `lea`. | Provisioning set file modes but did not consistently apply service ownership and effective readability. | Added transactional owner/group/mode application plus an actual `lea` readability probe. | Provisioning fails closed before activation when metadata or service access is wrong. |
| Readiness was racy immediately after systemd activation. | “Active” was treated as equivalent to “listening”. | Added bounded readiness probing with phase-safe diagnostics. | Health and acceptance require bounded network readiness, not an unbounded sleep. |
| First discovery tried to ask an interactive collection-creation question. | Collection creation was implicitly delegated to vdirsyncer discovery. | Added explicit authenticated MKCALENDAR bootstrap with a required approval flag. | First-collection mutation is separate, non-interactive and idempotent. |
| Provider failures collapsed into generic handler errors. | Action execution did not preserve structured phase, exit and issue context at the public boundary. | Added execution-boundary error/result models and redaction-safe diagnostics. | Regression tests ensure credentials, headers and event identity are never emitted. |
| The calendar-lock path differed between installer, docs and test card. | Multiple path assumptions were allowed to drift. | Centralized the canonical `/opt/lea-release-assets/calendar-requirements.lock` path and updated documentation/tests. | Path and hash contracts are checked in the quality gate. |
| Repair rejected the activated CalDAV configuration as drift. | The installer compared the local-only template literally after activation had added the supported CalDAV document. | Added strict recognition of only the exact supported activated CalDAV form. | Arbitrary drift remains rejected; the supported activated state is idempotently repairable. |
| A credential-bearing backup initially inherited unsafe permissions. | Archive creation began before root-only mode and ownership were established. | Added root-only archive creation before the first byte, ownership/mode preservation and isolated restore verification. | Backup tests require `0600 root:root`; restore requires a new isolated destination. |
| Purge left an orphaned Radicale distribution. | The first removal boundary deleted the record and state but not the exact pinned distribution root. | Extended the public purge contract to remove the explicitly declared distribution root with path-safety checks. | Removal tests cover exact distribution cleanup, symlink rejection and preservation of unrelated paths. |
| Real Taskwarrior integration tests failed on the locked-down host. | `Path.is_file()` raised `PermissionError` while the test intended to detect an inaccessible optional external binary. | Hardened availability probes to treat filesystem access errors as an environment skip. | Production lockdown is no longer misreported as a product failure; the real binary still runs when accessible. |
| A no-op upgrade did not create a pre-upgrade record backup. | No component replacement occurred, so the replacement transaction correctly did not create replacement evidence. | Kept the behavior explicit and documented; covered replacement rollback with deterministic tests. | Do not infer live replacement rollback evidence from a no-op upgrade; use a distinct supported version when available. |

These controls are intentionally layered: immutable release inputs, explicit
operator approvals, fail-closed root provisioning, bounded readiness, secure
recovery, structured diagnostics, and regression tests. A future integration
must preserve all layers rather than adding another temporary bypass.

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
