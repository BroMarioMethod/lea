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
- Status: `fixed-awaiting-card`.

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
- Status: `fixed-awaiting-card`.

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
