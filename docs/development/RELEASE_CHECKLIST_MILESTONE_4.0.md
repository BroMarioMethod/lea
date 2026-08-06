# Milestone 4.0 Release Checklist

| Field | Value |
|---|---|
| Milestone | `4.0` — Calendar Provider and CalDAV Synchronisation |
| Candidate branch | `milestone-4.0/calendar-provider` |
| Proposed tag | `milestone-4.0` |
| Primary server | Radicale |
| Managed clients | khal and vdirsyncer |
| Android client | DAVx⁵ |

## Release scope

Milestone 4.0 adds the provider-neutral calendar boundary, managed and pinned
khal/vdirsyncer toolchain, local vdir operations, proposal-backed mutations,
explicit synchronisation, separately managed Radicale deployment, CLI and
Telegram calendar routes, and recorded Android two-way acceptance.

The normative acceptance criteria are in
`docs/specifications/LEA-SPEC-0017_CALENDAR_PROVIDER_CALDAV_SYNC.md`. Operators
must use `docs/development/CALENDAR_PROVIDER_OPERATIONS.md` for installation,
Radicale provisioning, DAVx⁵ pairing, backup, upgrade and removal.
The ordered physical-card procedure is
`docs/development/MILESTONE_4_TEST_CARD.md`.

## Automated merge gate

- [x] Ruff formatting passes.
- [x] Ruff linting passes.
- [x] mypy passes.
- [x] Telegram deployment validation passes.
- [x] release-candidate acceptance-asset validation passes.
- [x] the complete pytest suite passes at accepted source `50b8bde`: 2,525
  passed and 7 expected environment skips on 2026-08-06.
- [x] calendar CLI arguments reach the request, orchestration engine, installer
  dispatch, installation record and post-install acceptance checks.
- [x] root-run file creation and replacement produce the required `0640`/`0600`
  modes, owner/group identities and service readability.
- [x] `scripts/check.sh` passes on the prepared candidate tree.
- [x] the final candidate has a clean merge simulation into current `main`.
- [ ] `scripts/check.sh` passes on the resulting merge commit.

Record the candidate commit, merge commit, command output and date in the pull
request or release evidence. Do not mark a check from an earlier commit.

## Clean-host and live acceptance gate

- [x] fresh installation succeeds on the supported clean DietPi host;
- [x] no correction from the tracked RC maintenance log remains unresolved;
- [x] the pinned Taskwarrior and calendar toolchains pass post-install checks;
- [x] khal and vdirsyncer execute only from their recorded managed paths;
- [x] Radicale health and reciprocal two-user collection isolation pass;
- [x] LEA-to-Android timed-event synchronisation passes with timezone intact;
- [x] Android-to-LEA event synchronisation passes;
- [x] the mode-0640 Android acceptance record is retained outside Git;
- [x] backup and isolated restore verification pass;
- [x] an approved upgrade preserves rollback evidence and passes acceptance;
- [x] non-purge removal preserves data and secrets as documented;
- [x] confirmed purge removes only managed targets and revoked credentials fail;
- [ ] required Telegram-enabled acceptance passes before and after reboot.

Live checks require the real host, Radicale service, test accounts and Android
device. Unit or mocked integration tests do not satisfy them. Evidence must not
contain passwords, bcrypt verifiers, phone identifiers or live event IDs.

## Documentation gate

- [x] the Milestone 4.0 specification defines scope and acceptance criteria;
- [x] the operations runbook covers install, Radicale, DAVx⁵, acceptance,
  backup, upgrade, rollback and removal;
- [x] the installation guide identifies calendar release assets and boundaries;
- [x] the README links the Milestone 4.0 specification, runbook and checklist;
- [x] the test-card procedure defines ordered gates, commands, expected results,
  evidence rules and stop conditions;
- [x] every correction discovered during the completed repair-card acceptance
  is documented.
- [x] final-card findings through accepted source `50b8bde` and branch tip
  `458973f` are recorded in the RC maintenance log and credential-free
  acceptance knowledge.

## Merge and release decision

The branch is merge-ready only after the automated merge gate passes. Merging
does not by itself complete Milestone 4.0. Create and push `milestone-4.0` only
after every clean-host and live acceptance item is checked against retained,
non-secret evidence from the final merged commit.
