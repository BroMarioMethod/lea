# ADR-0012: Taskwarrior Distribution Strategy

- **Status:** Accepted
- **Version:** 1.1
- **Date:** 22 July 2026
- **Decision owners:** LEA maintainers
- **Related specifications:** `LEA-SPEC-0011_TASK_PROVIDER_TASKWARRIOR_CLI.md`,
  `LEA-SPEC-0012_TASKWARRIOR_INSTALLER_CONTRACT.md`

## Context

LEA requires a supported Taskwarrior 3.4.x executable at an exact path, with
configuration and state isolated from users' personal Taskwarrior installations.

Distribution package versions vary, source compilation is expensive on small
hardware, and runtime discovery through `PATH` is non-deterministic.

## Decision

LEA uses a three-tier distribution strategy.

### Tier 1: verified release binary

This is the recommended default.

LEA verifies the platform artefact checksum, stages it beneath the tools root,
runs the shared lifecycle smoke test and atomically activates:

```text
/opt/lea-tools/taskwarrior/<version>/bin/task
```

Initial targets are Linux AArch64 and Linux x86-64.

Release publication automation is deferred, but the installer contract and
provenance structure required to consume those artefacts are implemented.

### Tier 2: pinned source build

An administrator may explicitly request a source build.

The build uses:

- Taskwarrior 3.4.2;
- a local pinned source archive;
- the recorded SHA-256 checksum;
- safe manual extraction;
- exact build-tool paths;
- explicit CMake source, build and installation paths;
- finite probes and build timeout;
- a private temporary build tree;
- post-build checksum and lifecycle validation;
- the same staging and activation boundary as bundled binaries.

The clean Taskwarrior 3.4.2 CMake build retrieves Corrosion through verified
HTTPS. Source-build preflight therefore validates `/usr/bin/git`, the Debian CA
bundle and canonical Git `HEAD` reachability before compilation.

A fully offline transitive build bundle is a future extension.

The Raspberry Pi 4B pilot completed a clean build in approximately 50 minutes.
Concurrency 1 is the safe default for 4 GB systems; concurrency 2 is validated
but used swap and reduced headroom.

### Tier 3: administrator-supplied executable

An administrator may register an exact absolute executable path.

LEA validates its file type, executability, `_version` output and complete
isolated lifecycle behaviour. It neither copies nor alters the executable.

## Runtime isolation

LEA uses:

```text
/etc/lea/taskwarrior/taskrc
/var/lib/lea/taskwarrior/home
/var/lib/lea/taskwarrior/data
```

Runtime calls use explicit executable, HOME, TASKRC, taskrc and data paths.
Direct TaskChampion SQLite access is prohibited.

## Licensing and provenance

Taskwarrior remains a distinct MIT-licensed third-party component.

The repository preserves:

```text
third_party/taskwarrior/VERSION
third_party/taskwarrior/SHA256SUMS
third_party/taskwarrior/LICENSE
third_party/taskwarrior/NOTICE.md
```

LEA's AGPL-3.0-only licence does not replace Taskwarrior's licence.

The source archive is not committed merely because it is small. Release and
installation processes may retrieve or supply the pinned archive separately,
but must verify it before use.

## Consequences

### Positive

- normal users can use fast verified binaries;
- exact paths and versions are deterministic;
- source builds remain available for unsupported targets;
- administrators may retain external package ownership;
- personal Taskwarrior state remains isolated;
- one smoke-test contract validates every mode;
- repeated source installation avoids recompilation.

### Negative

- release engineering must eventually publish multiple artefacts;
- provenance must be maintained for every binary;
- clean source builds require a toolchain and verified network access;
- the Raspberry Pi build takes roughly 50 minutes;
- a fully offline source build requires future transitive dependency packaging.

## Rejected alternatives

### Distribution package only

Rejected because supported versions and architectures vary.

### Search `PATH`

Rejected because it may select an unsupported or user-managed executable.

### Require source builds for all users

Rejected because compilation is slow and resource-intensive.

### Git submodule

Rejected because it complicates cloning, reproducibility and offline setup.

### Reimplement Taskwarrior or TaskChampion

Rejected for Milestone 2.2. The existing CLI meets the required operations and
its measured Raspberry Pi performance is acceptable.

## Deferred lifecycle work

Automated upgrades, rollback UX, uninstall, destructive data removal, release
publication automation and fully offline build packaging are deferred.

The fixed policy remains that user and production task data are preserved by
default.

## Acceptance criteria

This decision is implemented for Milestone 2.2 when:

- all three installer tiers work;
- generic mode dispatch exists;
- integrity, safe extraction, exact-path and TLS trust checks exist;
- shared isolated smoke testing exists;
- activation and records are atomic and idempotent;
- provenance and operator documentation are present;
- real Raspberry Pi evidence is recorded;
- the full quality gate passes.

Producing public platform binaries is a release-engineering follow-on, not a
blocker for the provider and installer milestone.
