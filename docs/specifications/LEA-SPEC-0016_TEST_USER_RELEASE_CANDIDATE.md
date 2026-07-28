# LEA-SPEC-0016 — Test-user Release Candidate

**Document Status:** Accepted  
**Implementation Status:** In Progress  
**Verification Status:** Partially Verified  
**Verified Profile:** Fresh DietPi installation without Telegram  
**Last Verified:** 28 July 2026  
**Milestone:** 2.7 — Test-user Release Candidate  
**Repository:** LEA  
**Licence:** AGPL-3.0-only  
**Language:** UK English

## 1. Purpose

This specification defines the first LEA release candidate that can be installed, configured, operated, diagnosed and removed by a test user who is not the primary developer.

Milestone 2.7 converts the current development installation into a repeatable, guided and supportable product installation. It does not add new business-domain integrations. Its purpose is to prove that the existing runtime, Taskwarrior integration and Telegram channel can be deployed safely on a clean DietPi system without undocumented manual preparation.

## 2. Goals

Milestone 2.7 shall provide:

1. a guided installation process suitable for a fresh DietPi installation;
2. guided Telegram bot and owner registration;
3. deterministic creation of LEA users, groups, directories and configuration;
4. installation and verification of required runtime components;
5. safe reruns, upgrades, recovery and rollback;
6. owner and tester trust boundaries;
7. health checks and redacted diagnostics;
8. a clean-room acceptance procedure;
9. a release-candidate checklist and versioned release artefact.

## 3. Non-goals

This milestone does not include:

- the deferred LAN adapter;
- calendar, contacts, CRM, accounting or document-delivery integrations;
- a graphical installer;
- Docker-based deployment;
- secrets in logs, command arguments or environment variables;
- automatic migration of arbitrary pre-release installations without an explicit migration contract.

## 4. Supported baseline

The initial release-candidate baseline is:

- Raspberry Pi 4B, 64-bit, 4 GB RAM;
- DietPi on a supported Debian base;
- systemd as PID 1;
- local installation under `/opt/lea`;
- system configuration under `/etc/lea`;
- persistent state under `/var/lib/lea`;
- logs under `/var/log/lea`;
- transient runtime state under `/run/lea`;
- Telegram as the supported user-facing channel;
- Taskwarrior as the first external tool integration.

Other Debian-derived systems may work, but are not accepted as clean-room targets until separately validated.

## 5. Trust model

### 5.1 Installer operator

The installer operator has administrative access to the host and may create system users, install packages, configure services and register the first LEA owner.

The installer shall require explicit elevation for privileged mutations and shall not retain administrative credentials.

### 5.2 Owner

The first Telegram identity registered during onboarding shall default to the `owner` role only after the operator confirms the detected identity.

The owner may receive the complete capability set permitted by the installed configuration. Capability checks, action validation, approval rules and audit logging remain mandatory.

### 5.3 Tester

A tester is an explicitly authorised, restricted user.

A tester shall:

- be explicitly added;
- receive an explicit capability bundle;
- be denied owner-only administration operations;
- remain subject to validation, approval and audit controls;
- be removable without changing the owner identity.

Tester access shall not be inferred from usernames, display names, telephone numbers, contacts or Telegram group membership.

### 5.4 Unauthorised identities

Updates from identities absent from the authorised-user configuration shall not be dispatched to application commands.

Any denial response shall not reveal configuration, owner identity, capability details, filesystem paths, secrets or diagnostics.

## 6. Guided installation

The release candidate shall expose one documented installation entry point.

The installer shall guide the operator through:

1. platform and prerequisite checks;
2. installation-mode confirmation;
3. LEA system account and group creation;
4. repository or release installation;
5. Python runtime and virtual-environment preparation;
6. Taskwarrior installation or verification;
7. runtime-directory creation;
8. base LEA configuration;
9. optional Telegram onboarding;
10. systemd unit installation;
11. health verification;
12. acceptance-test summary.

It shall clearly distinguish planned changes, completed changes, skipped optional steps, recoverable failures, fatal failures and manual actions still required.

## 7. Installer safety requirements

The installer shall:

- be deterministic for the same inputs and host state;
- validate inputs before privileged mutation where practical;
- use explicit absolute paths;
- avoid shell interpolation of untrusted values;
- write configuration atomically;
- create backups before replacing managed files;
- set ownership and permissions explicitly;
- refuse unsafe symlinks for managed paths;
- avoid following user-controlled paths as root;
- avoid printing secrets;
- avoid secrets in process arguments and environment variables;
- leave a structured installation result;
- support a non-mutating preflight mode;
- return a non-zero status on incomplete installation;
- remain safe to rerun after partial failure.

Existing installations shall not be overwritten without explicit confirmation or an explicit upgrade mode.

## 8. Guided Telegram onboarding

Telegram onboarding is a required milestone outcome.

### 8.1 User flow

The flow shall:

1. ask whether Telegram should be configured;
2. explain how to create a bot through BotFather;
3. accept the token through hidden terminal input;
4. validate it through Telegram `getMe`;
5. display the bot username without displaying the token;
6. instruct the operator to send `/start`;
7. poll for a matching private-chat update;
8. extract the numeric user ID and conversation ID;
9. display the detected identity for confirmation;
10. assign an explicit role;
11. preview managed file and service changes;
12. write configuration and secret files atomically;
13. install or restart the Telegram service;
14. verify service health and outbound response;
15. report success or actionable recovery instructions.

### 8.2 Identity rules

Registration shall use numeric Telegram identifiers.

Usernames, display names, telephone numbers and profile text shall not be authoritative identity keys.

The first owner registration shall require a private conversation where the user ID and conversation ID are equal, unless a later specification permits another conversation type.

The flow shall reject:

- channel posts;
- group and supergroup updates;
- bot identities;
- ambiguous candidates;
- stale updates whose relationship to the current registration attempt cannot be established;
- identities already registered under conflicting roles.

### 8.3 Token handling

The token shall:

- be entered using hidden input;
- be held in memory only as long as required;
- never be echoed;
- never appear in logs or exceptions;
- never be passed as a command-line argument;
- never be committed;
- be written to `/etc/lea/secrets/telegram-bot-token`;
- be owned by `lea:lea`;
- use mode `0600`.

Temporary token files, when unavoidable, shall use equivalent or stricter permissions and be removed on success and failure.

### 8.4 Managed Telegram files

The flow shall create or update:

- `/etc/lea/lea.toml`;
- `/etc/lea/telegram/telegram.toml`;
- `/etc/lea/telegram/authorised-users.toml`;
- `/etc/lea/telegram/worker.env`;
- `/etc/lea/secrets/telegram-bot-token`.

Non-secret configuration files shall normally be owned by `root:lea` with mode `0640`.

Updates shall preserve unrelated supported settings and shall not duplicate an existing identity.

### 8.5 Rerun behaviour

Rerunning onboarding shall support:

- inspecting current Telegram configuration;
- validating the existing token without displaying it;
- replacing the token after explicit confirmation;
- registering another authorised identity;
- changing a non-owner role;
- disabling Telegram without deleting configuration;
- repairing permissions;
- reinstalling or restarting the service;
- cancelling without mutation.

Removing or replacing the final owner requires a separate explicit administrative flow.

## 9. System account and filesystem contract

The installation shall create or verify:

- system user `lea`;
- system group `lea`;
- non-login shell;
- no normal home-directory requirement.

Required paths include:

- `/opt/lea`;
- `/etc/lea`;
- `/etc/lea/secrets`;
- `/etc/lea/telegram`;
- `/var/lib/lea`;
- `/var/lib/lea/audit`;
- `/var/lib/lea/proposals`;
- `/var/lib/lea/knowledge`;
- `/var/lib/lea/indexes`;
- `/var/lib/lea/adapters`;
- `/var/lib/lea/backups`;
- `/var/lib/lea/telegram`;
- `/var/log/lea`.

`/run/lea` shall be created by systemd through `RuntimeDirectory=lea` with mode `0750`.

The installer shall verify ownership, mode and access after creation.

## 10. Service installation

The installer shall install the committed `lea-telegram.service` asset and shall:

- verify it with `systemd-analyze verify`;
- reload systemd;
- enable it only after required configuration exists;
- start or restart it;
- verify `ActiveState=active` and `SubState=running`;
- confirm that it runs as `lea:lea`;
- verify automatic runtime-directory creation;
- provide recent redacted journal output on failure.

A failed unit verification shall fail the Telegram installation step.

## 11. Configuration contracts

Generated configuration shall be validated through the same application contracts used at runtime.

The installer shall not maintain an independent interpretation of LEA configuration where reusable validators already exist.

Configuration generation shall use stable schema versions, explicit time zones and absolute paths, while rejecting unknown or unsafe values.

## 12. Installation record

The installer shall maintain a machine-readable installation record under a managed LEA state path.

The record shall include, where applicable:

- schema version;
- LEA version;
- installation timestamp in UTC;
- installation mode;
- platform summary;
- installed component versions;
- managed paths;
- enabled services;
- completed installer steps;
- recoverable warnings;
- migration history.

It shall not contain tokens, message contents, passwords, complete environment dumps or unnecessary personal data.

Displayed timestamps shall be localised to the configured display time zone.

## 13. Upgrade requirements

The release candidate shall define an upgrade path that:

- performs preflight checks;
- identifies installed and target versions;
- backs up managed configuration;
- validates schema compatibility;
- applies deterministic migrations;
- installs updated code and service assets;
- runs health checks;
- reports restart or reboot requirements;
- preserves authorised identities and secrets unless explicitly changed;
- supports rollback when completion is unsafe.

An upgrade shall not continue silently after a failed migration.

## 14. Rollback and recovery

Recovery shall be documented and tested for:

- interrupted installation;
- invalid Telegram token;
- no `/start` update received;
- ambiguous identity;
- failed configuration validation;
- incorrect ownership or permissions;
- failed systemd verification;
- service start failure;
- missing `/run/lea`;
- failed Taskwarrior installation or inspection;
- damaged installation records;
- failed upgrades.

Rollback shall restore the most recent valid managed configuration where possible and shall not delete user data without explicit approval.

## 15. Uninstallation

The uninstall flow shall distinguish:

- disabling services;
- removing code;
- removing generated configuration;
- removing secrets;
- retaining or deleting user data;
- retaining or deleting audit records;
- removing the `lea` account.

Destructive removal shall require explicit confirmation.

## 16. Diagnostics and support bundle

LEA shall provide a command or script that can create a redacted support bundle.

It may include:

- LEA version;
- operating-system summary;
- Python and dependency versions;
- service state;
- runtime health;
- configuration schema summaries;
- ownership and mode summaries;
- recent redacted logs;
- installation-record summary;
- failed acceptance checks.

It shall exclude or redact:

- tokens, API keys and passwords;
- private message bodies;
- full authorised-user identifiers unless explicitly approved;
- unnecessary names;
- arbitrary environment values;
- unrelated files.

The operator shall see the planned bundle contents before creation.

## 17. Clean-room test target

The milestone shall be tested on the freshly flashed second SD card using the same Raspberry Pi.

The clean-room operator shall not manually pre-create:

- `/opt/lea`;
- `/etc/lea`;
- `/var/lib/lea`;
- `/var/log/lea`;
- the `lea` user or group;
- Taskwarrior runtime files;
- systemd service files.

Only documented DietPi baseline preparation is permitted before running the installer.

Any undocumented manual correction is a release-candidate defect.

## 18. Clean-room acceptance criteria

A clean-room installation passes only when:

1. the documented entry point starts;
2. preflight recognises the supported host;
3. required packages and runtimes are installed or verified;
4. the `lea` account and managed directories are correct;
5. Telegram onboarding validates a real token;
6. a real `/start` message registers the confirmed owner;
7. managed files have correct ownership and permissions;
8. the Telegram service is enabled and active;
9. `/status` responds;
10. `/tasks` returns a structured response;
11. runtime health is healthy;
12. the host reboots without manual repair;
13. `/run/lea` is recreated automatically;
14. Telegram starts automatically after reboot;
15. commands respond after reboot;
16. no token appears in arguments, environment output, logs or support data;
17. installer rerun is safe and does not duplicate configuration;
18. one deliberately induced failure is recoverable using the documentation;
19. the full repository gate passes for the tested commit;
20. the acceptance result is recorded without secrets.

## 19. Test strategy

Automated tests shall cover:

- installer input validation;
- plan generation;
- privileged-operation boundaries;
- filesystem ownership and modes;
- atomic writes;
- backup and rollback;
- token redaction;
- Telegram `getMe` validation;
- owner discovery;
- stale, group and ambiguous update rejection;
- owner and tester role assignment;
- idempotent reruns;
- systemd installation plans;
- installation-record serialisation;
- diagnostic redaction;
- acceptance-result serialisation.

Network tests shall use deterministic fakes by default. Live Bot API testing belongs to controlled clean-room acceptance.

## 20. Current verification state

The local installation profile has passed clean-room verification on a fresh
DietPi system with Telegram disabled.

Verified behaviour includes:

- fresh installation;
- repair;
- managed purge;
- pinned Taskwarrior 3.4.2 source installation;
- post-install health;
- disposable Taskwarrior lifecycle acceptance;
- runtime-directory recreation after reboot;
- post-reboot health and acceptance.

- user-facing installer and uninstaller wrapper execution from outside the
  repository;
- safe wrapper cancellation and managed purge;
- preservation of the source repository and release assets during purge;
- fresh reinstall through the user-facing installer wrapper;
- persistent acceptance-record generation;
- service-user access to the managed executable, configuration and runtime
  directory;

- live Telegram onboarding with the intended private owner identity;
- Telegram service deployment, enablement and active operation;
- `/status` and `/tasks` interaction before and after reboot;
- live confirmation that the bot token was absent from process arguments,
  process environment and recent journal output;
- Telegram-enabled release-candidate acceptance before and after reboot;
- induced Telegram worker failure followed by automatic systemd recovery;

The complete evidence is recorded in:

```text
docs/development/RELEASE_CANDIDATE_CLEAN_ROOM_VERIFICATION.md
```

The full milestone is not yet verified because the final release checklist
and release tagging remain outstanding.

## 21. Proposed implementation slices

### Slice 1 — Milestone specification

- accept this specification;
- define scope and completion criteria.

### Slice 2 — Installer contracts and plans

- installation request and result contracts;
- step, issue and mutation-plan contracts;
- installer state transitions;
- no privileged mutation.

### Slice 3 — Host preflight

- supported-platform inspection;
- dependency and privilege checks;
- existing-installation detection;
- non-mutating report.

### Slice 4 — System account and filesystem provisioning

- deterministic user, group and directory plan;
- ownership and permissions;
- idempotent execution.

### Slice 5 — Base configuration generation

- `/etc/lea/lea.toml`;
- installation record;
- atomic writes and backups;
- runtime validation.

### Slice 6 — Taskwarrior installation integration

- reuse the existing source installer;
- create the system-profile installation record;
- verify the exact managed executable;
- smoke-test the system runtime.

### Slice 7 — Telegram onboarding contracts

- token-validation boundary;
- identity-discovery boundary;
- registration request and result contracts;
- deterministic fakes.

### Slice 8 — Guided Telegram onboarding

- hidden token entry;
- `getMe` validation;
- `/start` discovery;
- identity confirmation;
- role selection.

### Slice 9 — Telegram configuration installation

- token and TOML writes;
- permissions;
- safe reruns;
- service environment generation.

### Slice 10 — systemd installation and verification

- unit installation;
- daemon reload;
- enable, start and health verification;
- failure diagnostics.

### Slice 11 — Diagnostics and support bundle

- redaction contracts;
- bundle manifest;
- service and runtime summaries;
- no secret leakage.

### Slice 12 — Upgrade, rollback and uninstall

- backup inventory;
- migration boundary;
- rollback;
- explicit retention choices.

### Slice 13 — Acceptance harness and documentation

- clean-room acceptance script;
- installation guide;
- Telegram onboarding guide;
- recovery guide;
- tester guide.

### Slice 14 — First clean-room installation

- install on the second SD card;
- record defects;
- return to the primary card for corrections.

### Slice 15 — Release-candidate validation

- repeat installation from a fresh baseline;
- run the full gate;
- complete the release checklist;
- version and tag the candidate.

## 22. Completion criteria

Milestone 2.7 is complete when:

- this specification is accepted;
- the installer and guided onboarding are implemented;
- all automated checks pass;
- a fresh DietPi installation succeeds without undocumented preparation;
- Telegram owner registration succeeds through the guided flow;
- the service survives reboot;
- diagnostics are useful and redacted;
- rerun and one recovery scenario are demonstrated;
- installation and recovery documentation are accepted;
- the release checklist is complete;
- the release candidate is merged and tagged.

## 23. Deferred work

The following remain deferred:

- Milestone 2.6 LAN adapter;
- browser-based onboarding;
- QR-code registration;
- multi-host orchestration;
- automatic remote updates;
- non-Debian package formats;
- container images;
- additional business-tool integrations.
