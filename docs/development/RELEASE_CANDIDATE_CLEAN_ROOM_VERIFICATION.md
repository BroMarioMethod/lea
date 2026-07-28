# Release-candidate Clean-room Verification

## Status

| Item | Value |
|---|---|
| Document Status | Accepted |
| Verification Status | Partially Verified |
| Verification Date | 28 July 2026 |
| Tested Profile | Fresh DietPi installation without Telegram |
| Platform | Raspberry Pi 4B, AArch64 |
| Operating System | Debian GNU/Linux 13.6 through DietPi |
| Repository Commit | `dc17c74` |
| Merged Main Commit | `11aaa22` |

## Purpose

This record documents the clean-room evidence gathered for the LEA test-user
release-candidate installer.

The tested profile deliberately disabled Telegram. It verifies the local
release-candidate installation, managed Taskwarrior runtime, lifecycle
acceptance, purge, repair and reboot-persistence paths. It does not verify live
Telegram onboarding or Telegram service operation.

## Source artefact

Taskwarrior was built from the pinned source archive:

```text
task-3.4.2.tar.gz
```

Expected SHA-256:

```text
d302761fcd1268e4a5a545613a2b68c61abd50c0bcaade3b3e68d728dd02e716
```

The archive checksum was verified before installation.

## Clean host baseline

The final clean-room installation used:

```text
Raspberry Pi 4B
AArch64
4 CPU cores
approximately 3.8 GiB RAM
Debian GNU/Linux 13.6
DietPi
Python 3.13.5
uv 0.11.33
Taskwarrior 3.4.2
```

The host used systemd and a working system D-Bus.

The test exposed an important DietPi prerequisite: a fresh DietPi image may
ship with D-Bus or related systemd facilities disabled or masked according to
its first-boot configuration. LEA requires a working system bus for managed
systemd service operations.

## Installation result

The final fresh installation completed successfully with:

```text
Mode: fresh-install
Display timezone: Africa/Gaborone
Telegram: disabled
Taskwarrior build concurrency: 1
```

Completed installer stages:

1. host preflight;
2. system-account provisioning;
3. managed filesystem provisioning;
4. base configuration;
5. Taskwarrior source build and activation;
6. read-only post-install health;
7. disposable functional acceptance.

The Taskwarrior source-build phases completed in approximately:

| Phase | Duration |
|---|---:|
| Configure | 55.9 seconds |
| Build | 2 462.8 seconds |
| Install | 0.2 seconds |

## Post-install verification

The following managed resources were present with the expected ownership and
permissions:

```text
/etc/tmpfiles.d/lea.conf
/run/lea
/etc/lea/lea.toml
/etc/lea/taskwarrior/taskrc
/var/lib/lea/install/release-candidate.json
/var/lib/lea/install/taskwarrior.json
/opt/lea-tools/taskwarrior/3.4.2/bin/task
```

The managed executable reported:

```text
3.4.2
```

Post-install health passed:

```text
runtime_health
taskwarrior_record_valid
taskwarrior_inspection
installation_record
```

Functional acceptance passed:

```text
taskwarrior_lifecycle
```

## Reboot verification

After reboot:

- systemd reported `running`;
- `/run/lea` was recreated by the installed tmpfiles rule;
- the managed Taskwarrior executable remained available;
- installation records remained valid;
- read-only health passed;
- disposable Taskwarrior lifecycle acceptance passed.

## Additional lifecycle evidence

Before the final fresh-card run, the installer was also exercised through:

- failed-install diagnostics;
- repair;
- post-reboot health and acceptance;
- managed purge;
- fresh reinstall;
- repeated reboot verification.

The purge preserved:

```text
/opt/lea
/opt/lea-release-assets
```

while removing managed LEA product state.

## Verified scope

This evidence verifies:

- fresh installation without Telegram;
- managed account and filesystem provisioning;
- base runtime configuration;
- pinned Taskwarrior source installation;
- Taskwarrior activation and installation records;
- installer progress and long-running build heartbeats;
- read-only post-install health;
- disposable Taskwarrior functional acceptance;
- safe repair behaviour;
- managed purge behaviour;
- runtime-directory recreation after reboot;
- post-reboot health and acceptance.

## Outstanding verification

The following release-candidate requirements remain unverified:

- live Telegram bot-token validation;
- authorised Telegram user and private-chat registration;
- installation of real Telegram secrets outside Git;
- Telegram systemd service enablement and startup;
- Telegram `/status` and task interaction;
- Telegram operation after reboot;
- live confirmation that secrets are absent from diagnostics and process exposure;
- final one-command user-facing installer and uninstaller entry points;
- final release tag and release checklist.

Real Telegram values must be configured only during the controlled live
runtime smoke test. Tokens and real identifiers must remain outside Git.

## Conclusion

The non-Telegram release-candidate installation profile is verified on a fresh
DietPi system.

Milestone 2.7 remains partially verified until the user-facing installer
interface and live Telegram acceptance requirements are completed.
