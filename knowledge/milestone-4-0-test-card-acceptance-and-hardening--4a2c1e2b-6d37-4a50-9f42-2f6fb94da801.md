---
schema_version: 1
document_id: 4a2c1e2b-6d37-4a50-9f42-2f6fb94da801
document_type: project
document_version: 1
title: "Milestone 4.0 test-card acceptance and hardening"
sensitivity: medium
created_at: 2026-08-05T00:00:00Z
updated_at: 2026-08-05T00:00:00Z
links: []
external_references: []
---
# Milestone 4.0 test-card acceptance and hardening

## Accepted source state

- Branch: `milestone-4.0/calendar-provider`.
- Test-card acceptance source commit: `79d42d5`.
- The branch was pushed and the development card was verified at the same commit.
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

The live acceptance record and protected backup remain on the test card. They
are operational evidence and must not be committed to Git.

## Findings that block merge

### 1. Reproducible Radicale supply chain

The release assets did not contain a reviewed, pinned Radicale distribution.
Live acceptance required a separate network installation of exact version
3.5.4. Add a reproducible release asset with independently reviewed hashes,
exact dependencies and an installation record. Do not infer trust by hashing an
artifact only after downloading it.

### 2. Supported deployment entry point

Radicale and CalDAV provisioning were exposed as library boundaries but lacked
a supported operator command or release-candidate workflow. Live deployment
required a temporary script. Provide a deterministic, redaction-safe command
that accepts explicit trusted paths and approvals and never emits secrets.

### 3. Root-run ownership

The default Radicale orchestration provisions mode-0600 credentials without
applying service ownership. When invoked as root, the `lea` service cannot read
them. Ownership must be applied transactionally to configuration, secret and
storage paths before service activation, with regression coverage.

### 4. Service readiness race

The first health inspection ran immediately after systemd reported activation
and failed before Radicale began listening. Add a bounded monotonic readiness
loop with explicit attempt/timeout diagnostics. Do not use an unbounded sleep
or weaken the health requirement.

### 5. First-collection bootstrap

Initial discovery encountered a local collection that did not yet exist on the
new server. vdirsyncer requested interactive confirmation; the non-interactive
action handler failed with `handler_exception`. Collection creation must be a
separate explicit, approved operation or an exact declared bootstrap input. It
must remain non-interactive during execution.

### 6. Action diagnostics

Expected provider failures must retain redaction-safe phase, exit and issue
information rather than collapsing to a generic handler exception. Passwords,
authorization headers and event identifiers must remain excluded.

### 7. Backup safety

The manually created credential-bearing archive inherited mode 0644 and had to
be corrected to root:root mode 0600. Supported backup tooling must create the
archive securely from the first write, stop or snapshot Radicale consistently,
preserve ownership and modes, verify an isolated restore, and avoid secret
output.

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

## Merge rule

Do not merge or tag Milestone 4.0 until all blocking findings above have an
automated regression test, the full quality gate passes, and the final live
test-card rerun is documented without secret or event-identity material.
