# Milestone 4.0 Release-candidate Maintenance Log

This is a temporary, Git-tracked working record for release-candidate test-card
runs. Add each observed defect, diagnosis, correction and verification here
while the candidate is being hardened. Review it before merge; transfer durable
rules into specifications or operational documentation, then remove this file
only when every entry is resolved and preserved where necessary.

Do not record secrets, bcrypt verifiers, Telegram tokens, phone identifiers,
live event identifiers or other test-user data.

## Run record template

### Run YYYY-MM-DD — `<candidate commit>`

- Environment/card:
- Installer command/profile:
- Observed result:
- Defect or insight:
- Root cause:
- Changed files/commit:
- Automated regression coverage:
- Physical retest result:
- Status: `open`, `fixed-awaiting-card`, or `verified`

## Consolidated findings

### Run 2026-08-04 — `79d42d5` full repair-card calendar acceptance

- Environment/card: physical repaired release-candidate test card and Android
  device on the private LAN.
- Installer command/profile: release-candidate `repair`, system profile,
  Telegram disabled for this calendar-specific run.
- Observed result: managed-client health and lifecycle, authenticated Radicale,
  reciprocal two-account isolation, explicit discovery and synchronization,
  both Android synchronization directions, consistent backup, isolated restore
  and Android acceptance-record creation passed.
- Defect or insight: Radicale deployment still required an operator script and
  separately installed executable; initial health raced service readiness;
  initial discovery required interactive remote-collection creation; expected
  provider failures lost their issue code; and the first manual backup archive
  inherited an unsafe mode before correction.
- Root cause: the separately managed Radicale library boundary was not yet a
  complete reproducible operator workflow, and first-run and backup invariants
  lacked end-to-end regression coverage.
- Changed files/commit: initial development hardening is `158a9d1`; the durable
  findings are also recorded in knowledge document
  `4a2c1e2b-6d37-4a50-9f42-2f6fb94da801`.
- Automated regression coverage: ownership application, bounded readiness,
  redaction-safe action failures and explicit missing-collection diagnostics;
  complete gate at `158a9d1` passed with 2,510 tests and one documented skip.
- Physical retest result: the original repaired-card run passed at `79d42d5`.
  The hardening commit and all later candidate changes still require the ordered
  fresh-install procedure.
- Status: `fixed-awaiting-card` for ownership/readiness/diagnostics;
  `open` for reproducible Radicale packaging, supported deployment, explicit
  collection bootstrap and supported backup/restore tooling.

### Run 2026-08-05 — repaired Milestone 4 candidate

- Environment/card: physical release-candidate test card and Android device.
- Installer command/profile: release-candidate repair installation.
- Observed result: the repaired installer installed the managed khal/vdirsyncer
  toolchain and established DAVx⁵ synchronisation after the permission and
  ownership corrections.
- Defect or insight: a root-run installer must prove final file ownership and
  group readability, and a tool integration must be connected through the
  complete CLI/engine/orchestration chain before consuming another card run.
- Root cause: captured in the consolidated permission and end-to-end wiring
  findings below.
- Changed files/commit: repair series `d0c09a5` through `79d42d5`; merge
  preparation and durable documentation in `d4ea7b4` and its follow-up.
- Automated regression coverage: full repository gate plus release-candidate
  wrapper, CLI, orchestration, provisioning, record and post-install tests.
- Physical retest result: repair installation, khal/vdirsyncer installation and
  DAVx⁵ connectivity succeeded with corrected permissions.
- Status: `verified` for repair installation, managed toolchain execution,
  ownership/permission correction and DAVx⁵ connectivity. Explicit two-way
  event, isolation, backup/restore and fresh-install evidence remain separate
  release-checklist items.

### Root-created managed-file permissions and ownership

- Observed result: files created by the root installer could have mode `0640`
  yet remain unreadable by the intended process because owner/group identity
  was wrong. `$USER:lea` and `lea:lea` are distinct contracts and cannot be
  treated as interchangeable.
- Root cause: creation ownership and the invoking shell's umask were allowed to
  influence final runtime state; some checks considered mode without proving
  owner, group and effective service readability.
- Correction: every managed-file path must explicitly apply and verify mode,
  owner and group after creation or atomic replacement. Tests that bypass the
  persistence layer must reproduce the contracted permissions rather than
  weakening loader security.
- Regression coverage: release-candidate provisioning, Telegram configuration,
  installation-record and acceptance-record tests.
- Status: `verified` on the repaired physical release-candidate card.

### Calendar release assets were not connected end to end

- Observed result: calendar components existed but the release-candidate wrapper
  and installation flow did not consistently carry the required assets through
  installation and acceptance.
- Root cause: implementation slices validated lower-level installers before
  proving public CLI-to-engine/orchestrator wiring.
- Correction: calendar lock, digest, trusted executables and pinned versions are
  carried through the wrapper, request, orchestration, installer records and
  post-install acceptance validation.
- Regression coverage: release-candidate CLI, calendar orchestration,
  post-install, wrapper and acceptance-asset validation tests.
- Status: `verified` on the repaired physical release-candidate card.

### Runtime installation records required stricter access handling

- Observed result: installation-record access could inherit unsuitable root
  installation metadata.
- Correction: managed records enforce their contracted regular-file, ownership
  and mode requirements and reject unsafe paths.
- Regression coverage: release-candidate system provisioning and calendar and
  Taskwarrior record tests.
- Status: `fixed-awaiting-card`.

### Final calendar acceptance required hardening

- Observed result: the first acceptance path did not cover all installed
  calendar assets and lifecycle evidence expected from the release candidate.
- Correction: acceptance validates installed calendar assets and records while
  preserving explicit discovery, synchronisation and mutation boundaries.
- Regression coverage: release-candidate acceptance validator, calendar
  post-install and proposal lifecycle tests.
- Status: `fixed-awaiting-card`.

## Mandatory pre-card gate for the next integration

Before another physical-card run, the integration must have automated proof of:

1. public wrapper and CLI parsing;
2. immutable request construction and validation;
3. engine/orchestrator planning and dispatch;
4. installer execution, activation and installation-record persistence;
5. post-install health and disposable acceptance;
6. uninstall/purge dispatch where the integration owns managed resources;
7. root-created file modes, owner/group identities and service readability;
8. complete `scripts/check.sh` success on the exact candidate commit.
