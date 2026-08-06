---
schema_version: 1
document_id: 7c3f8e91-2a64-4b75-a9c2-61fd908e4b36
document_type: project
document_version: 1
title: "Milestone 4 test-card prerequisites developer handoff"
sensitivity: medium
created_at: 2026-08-05T00:00:00Z
updated_at: 2026-08-05T00:00:00Z
links:
  - 4a2c1e2b-6d37-4a50-9f42-2f6fb94da801
external_references: []
---
# Milestone 4 test-card prerequisites developer handoff

## Request

Provide a reproducible, documented release-asset set and supported deployment
path so the physical test card can execute
`docs/development/MILESTONE_4_TEST_CARD.md` from Gate 1 through the final live
rerun at candidate commit `158a9d14cb0baefb9b283b034138857cc10fdb5c` or a
reviewed successor.

This handoff is credential-free. Do not add passwords, bcrypt verifiers,
private server URLs, device identifiers, event identifiers or live event
summaries.

## Gate 1 observation

After pulling `milestone-4.0/calendar-provider`, the candidate source tree was
clean and local/remote tips matched at `158a9d1`. Host inspection identified:

- AArch64;
- Debian GNU/Linux 13.6;
- Python 3.13.5;
- uv 0.11.32;
- a present system D-Bus socket.

The documented `/opt/lea-release-assets` directory was absent. Consequently,
the required external Taskwarrior archive was unavailable and root installation
could not safely begin.

The repository does contain the reviewed calendar lock at
`third_party/calendar/requirements-linux-aarch64-py313.txt`, with digest:

```text
f5f7a0749b993e49bbd50b8807242611fff1dbc2477a59a4a292c0aa42420ba5
```

`install.sh` uses that repository path, while `docs/03_INSTALLATION.md` and the
test-card Gate 1 currently describe
`/opt/lea-release-assets/calendar-requirements.lock`. The developer must choose
one canonical, reviewed source and make the wrapper, advanced CLI example,
test-card runbook, validator and tests agree.

## Required release assets

### Taskwarrior

Provide the exact reviewed archive at:

```text
/opt/lea-release-assets/task-3.4.2.tar.gz
```

Required SHA-256:

```text
d302761fcd1268e4a5a545613a2b68c61abd50c0bcaade3b3e68d728dd02e716
```

Document the trusted source, review procedure, expected owner/group and mode,
and a repeatable method for placing it on a clean card without changing the
expected digest.

### Calendar client toolchain

Retain the exact pinned Python 3.13 AArch64 lock, its independently reviewed
digest, khal `0.11.4` and vdirsyncer `0.19.3`. Resolve the path inconsistency
described above. The selected path must be absolute when passed into the Python
installer, regular, non-symbolic and readable by the privileged installer.

Do not generate or modify the reviewed lock during the test-card run.

### Radicale

Provide a reproducible Radicale `3.5.4` release asset or reviewed locked
distribution set with:

- exact dependency versions;
- independently reviewed hashes recorded before card installation;
- supported AArch64/Python compatibility;
- an absolute, non-symbolic executable path;
- an installation record covering version and artifact identity;
- offline or explicitly verified installation behavior;
- no trust decision based only on hashing an artifact after downloading it.

The prior live run used a separate network installation because this asset did
not exist. That procedure is not final release evidence.

## Required supported deployment path

Provide one documented operator-facing command or release-candidate workflow
that connects all of these stages:

1. wrapper/public CLI parsing;
2. immutable request validation;
3. engine/orchestration planning;
4. reviewed Taskwarrior, calendar and Radicale asset selection;
5. privileged provisioning with explicit mode and owner/group application;
6. Radicale and CalDAV configuration without secret output;
7. bounded Radicale readiness;
8. explicit, non-interactive first-collection bootstrap;
9. post-install health, reciprocal isolation and disposable acceptance;
10. installation-record and redaction-safe diagnostic persistence;
11. backup and isolated-restore tooling;
12. repair, upgrade, rollback and removal dispatch.

Library-only entry points and temporary deployment scripts are insufficient.
The physical tester must not need to invent Python code or undocumented shell
commands.

## Root-installation requirements

For every created or atomically replaced file, verify numeric mode, owner,
group and effective service readability. Explicitly distinguish `root:lea`, an
operator account with group `lea`, and `lea:lea`. Cover configuration, CalDAV
password, Radicale users file and storage, installation records, acceptance
records, backups and rollback records.

Credential-bearing backup output must be `root:root` mode `0600` from its first
write. It must never be created permissively and repaired afterward.

## Systemd verification boundary

The restricted development session could observe the D-Bus socket but could
not query the host system bus. The developer must ensure the physical-card
operator can run and record:

```bash
systemctl is-active dbus.service
systemctl is-system-running
systemctl is-enabled lea-radicale.service
systemctl is-active lea-radicale.service
```

Do not weaken or remove these checks merely to accommodate a restricted
development sandbox.

## Automated acceptance criteria

Before requesting another physical run:

- asset/path consistency has regression coverage;
- missing, mismatched, symbolic or insecure assets fail before mutation;
- every public input reaches orchestration, activation and post-install checks;
- root ownership and service readability have regression coverage;
- readiness is bounded and reports redaction-safe timeout diagnostics;
- first-collection bootstrap never prompts during action execution;
- backup creation is secure from the first write and isolated restore is tested;
- `scripts/check.sh` passes at the exact pushed candidate commit;
- the Git-tracked test-card document contains the final exact commands.

## Developer delivery checklist

- [ ] place or provide the reviewed Taskwarrior archive and verify its digest;
- [ ] resolve the calendar-lock canonical-path inconsistency;
- [ ] add the reviewed Radicale distribution and installation record;
- [ ] expose the supported Radicale/CalDAV deployment workflow;
- [ ] complete non-interactive first-collection bootstrap;
- [ ] provide secure backup and isolated-restore tooling;
- [ ] add regression tests for each prerequisite and prior live defect;
- [ ] update `MILESTONE_4_TEST_CARD.md` with exact supported commands;
- [ ] run and record the complete automated gate;
- [ ] push the candidate and identify its full commit hash for the tester.

## Physical rerun required after delivery

The previous live evidence was collected at `79d42d5`. Commit `158a9d1` changes
Radicale ownership, readiness and execution diagnostics, so the final evidence
must be repeated on the exact delivered candidate. Repeat clean install,
repair, reboot persistence, both Android synchronization directions,
reciprocal user isolation, secure backup, isolated restore, upgrade/rollback
and removal. Do not merge or tag from older live evidence.
