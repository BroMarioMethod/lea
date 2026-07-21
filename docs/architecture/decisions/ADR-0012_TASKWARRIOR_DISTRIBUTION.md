# ADR-0012: Taskwarrior Distribution Strategy

- **Status:** Accepted
- **Date:** 21 July 2026
- **Decision owners:** LEA maintainers
- **Related specification:** `LEA-SPEC-0011_TASK_PROVIDER_TASKWARRIOR_CLI.md`

## Context

LEA requires a supported Taskwarrior 3.4.x executable for its task-provider adapter.

Relying only on the operating system package manager is insufficient because:

- supported distributions may provide older Taskwarrior releases;
- package availability varies by architecture and distribution;
- LEA requires a known executable path;
- LEA must isolate its configuration and task database from a user's personal Taskwarrior installation;
- installation must remain practical for non-technical users;
- source compilation requires a larger toolchain and increases installation time and failure risk.

LEA should therefore provide a convenient default installation path while retaining deterministic, auditable fallbacks.

## Decision

LEA will use a three-tier Taskwarrior distribution strategy.

### Tier 1: Verified release binary

The default installer will prefer a LEA release artefact containing a Taskwarrior binary built for a supported platform.

Initial supported targets:

- Linux x86-64;
- Linux AArch64.

The installer must:

1. detect the host platform;
2. select an exact supported artefact;
3. verify its recorded SHA-256 checksum;
4. copy it to the versioned LEA tools directory;
5. verify executable permissions;
6. execute `_version`;
7. reject unsupported versions;
8. run an isolated lifecycle smoke test;
9. record the installed executable path and checksum.

The canonical installation path is:

```text
/opt/lea-tools/taskwarrior/<version>/bin/task
```

LEA must never discover Taskwarrior through `PATH` during normal runtime.

### Tier 2: Pinned source build

When no verified binary exists for the target platform, an administrator may request a source build.

The source-build path must use:

- an exact Taskwarrior release version;
- a pinned source archive;
- a recorded SHA-256 checksum;
- an isolated temporary build directory;
- an explicit installation prefix;
- a post-install `_version` check;
- the same lifecycle smoke test used for binary installation.

The source archive remains a separate third-party component and must not be mixed into `src/lea`.

The preferred repository layout is:

```text
third_party/
└── taskwarrior/
    ├── VERSION
    ├── SHA256SUMS
    ├── LICENSE
    ├── NOTICE.md
    └── sources/
```

The source archive may be:

- committed directly when repository-size impact is acceptable; or
- downloaded by a release/build process from a pinned location and verified before use.

A Git submodule will not be used because it adds clone, update and reproducibility failure modes for users.

### Tier 3: Administrator-supplied executable

An administrator may supply an existing Taskwarrior executable through an explicit absolute path.

The installer must validate:

- the path is absolute;
- the file exists;
- the file is executable;
- `_version` returns a supported 3.4.x version;
- an isolated lifecycle smoke test passes.

LEA must store and use the exact validated path. It must not fall back to `PATH`.

## Isolation requirements

LEA will not use a user's personal Taskwarrior configuration or database.

The production layout will use:

```text
/etc/lea/taskwarrior/taskrc
/var/lib/lea/taskwarrior/
/var/lib/lea/taskwarrior/home/
/var/lib/lea/taskwarrior/data/
```

The exact final layout may be refined by the installer specification, but the following rules are fixed:

- configuration is LEA-managed;
- storage is LEA-managed;
- hooks are disabled unless a later specification explicitly enables them;
- confirmations are disabled for approved deterministic actions;
- runtime execution uses explicit `HOME`, `TASKRC` and data-location values;
- direct access to TaskChampion SQLite is prohibited in the CLI adapter.

## Licensing and provenance

Taskwarrior remains a distinct third-party component.

LEA distributions containing Taskwarrior source or binaries must preserve:

- Taskwarrior's licence text;
- upstream copyright notices;
- source-version provenance;
- build provenance;
- checksums for distributed artefacts.

LEA's AGPL-3.0-only licence does not replace the licence of bundled third-party components.

## Consequences

### Positive

- normal users avoid installing compilers and build dependencies;
- supported installations are fast and predictable;
- runtime behaviour uses a known Taskwarrior version;
- LEA remains portable to unsupported systems through source builds;
- administrators retain control over externally managed installations;
- personal Taskwarrior data remains isolated.

### Negative

- release engineering must build and verify multiple platform artefacts;
- third-party provenance and checksums must be maintained;
- source-build support adds installer complexity;
- unsupported architectures may require a lengthy local build;
- security updates require refreshing bundled artefacts and checksums.

## Rejected alternatives

### Use the distribution package only

Rejected because package versions and availability vary and may not satisfy LEA's supported baseline.

### Search for `task` through `PATH`

Rejected because it is non-deterministic and may select an unsupported or user-managed executable.

### Require every user to compile Taskwarrior

Rejected because it imposes unnecessary toolchain, time and troubleshooting costs.

### Use a Git submodule

Rejected because it complicates cloning, offline installation and version reproducibility.

### Reimplement Taskwarrior or TaskChampion

Rejected for Milestone 2.2 because the existing Taskwarrior CLI satisfies the required operations and measured performance is acceptable.

A future direct TaskChampion provider remains possible when evidence justifies it.

## Acceptance criteria

This decision is implemented when:

- the installer contract supports all three tiers;
- exact-path validation exists;
- checksum verification exists for LEA-provided artefacts;
- source-build behaviour is deterministic;
- isolated lifecycle smoke testing exists;
- licence and provenance files are included;
- installation documentation describes each path;
- supported release artefacts can be produced reproducibly.
