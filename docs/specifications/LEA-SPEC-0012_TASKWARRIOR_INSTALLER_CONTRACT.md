# LEA-SPEC-0012: Taskwarrior Installer Contract

- **Status:** Accepted
- **Version:** 1.1
- **Date:** 22 July 2026
- **Related ADR:** `ADR-0012_TASKWARRIOR_DISTRIBUTION.md`
- **Related provider specification:** `LEA-SPEC-0011_TASK_PROVIDER_TASKWARRIOR_CLI.md`

## 1. Purpose

This specification defines the deterministic contract for installing,
validating and configuring the Taskwarrior runtime used by LEA.

It does not define a general-purpose Taskwarrior installer. It defines only the
Taskwarrior installation required by LEA.

## 2. Supported installation modes

The installer supports exactly:

```text
bundled-binary
source-build
external-executable
```

The default and recommended mode is `bundled-binary`.

The generic entry point dispatches strictly by the configured mode. It must not
silently switch modes and must never select an executable through `PATH`.

## 3. Required inputs

### 3.1 Common inputs

- LEA service user and group;
- Taskwarrior version;
- platform identifier;
- configuration directory;
- state directory;
- tools directory;
- installation-record path.

### 3.2 Bundled-binary inputs

- binary artefact path;
- expected SHA-256 checksum;
- licence and provenance records.

### 3.3 Source-build inputs

- local pinned source archive path;
- expected SHA-256 checksum;
- build directory;
- build concurrency;
- explicit build dependency policy;
- finite dependency, network, build and smoke-test timeouts.

### 3.4 External-executable inputs

- absolute executable path.

## 4. Canonical paths

```text
Executable:          /opt/lea-tools/taskwarrior/<version>/bin/task
Configuration:       /etc/lea/taskwarrior/taskrc
State root:          /var/lib/lea/taskwarrior
Home:                /var/lib/lea/taskwarrior/home
Data:                /var/lib/lea/taskwarrior/data
Installation record: /var/lib/lea/install/taskwarrior.json
```

Every persisted path must be absolute.

## 5. Platform identifiers

Initial canonical identifiers:

```text
linux-x86_64
linux-aarch64
```

Required aliases:

```text
x86_64  -> linux-x86_64
amd64   -> linux-x86_64
aarch64 -> linux-aarch64
arm64   -> linux-aarch64
```

Unknown platforms fail closed unless a supported explicitly selected
source-build policy applies.

## 6. Installation phases

Managed installation executes:

1. configuration validation;
2. existing-installation inspection;
3. preflight;
4. source or artefact selection;
5. integrity verification;
6. staging or source extraction;
7. build where applicable;
8. isolated lifecycle smoke test;
9. runtime-layout provisioning;
10. atomic activation;
11. installation-record persistence;
12. cleanup and final result.

A failure before activation must preserve a previously working installation.

## 7. Preflight contract

Preflight validates:

- required paths are absolute;
- destination parents are writable or creatable;
- required inputs are present;
- requested version and platform are supported;
- source-build dependencies exist;
- source-build timeouts and concurrency are positive;
- source-build network trust is valid before a clean online build.

Privilege elevation and ownership changes belong to a later privileged
installation boundary. Tests use isolated writable paths.

## 8. Integrity verification

Bundled binaries and pinned source archives are SHA-256 verified before use.

A mismatch stops installation, preserves any active installation, creates no
success record and removes installer-managed staging.

## 9. Binary installation

Bundled binaries are copied into private staging beneath the tools root,
verified independently, smoke-tested and atomically activated.

Final version directories are not overwritten in place.

## 10. Source-build contract

Source-build mode must:

- verify the archive before extraction;
- reject unsafe archive members;
- safely materialise only verified internal regular-file symlinks;
- build in an installer-managed temporary directory;
- use exact build-tool paths;
- require C++17, Rust 1.81.0 or newer and `pkg-config` UUID support;
- use explicit CMake source, build and installation paths;
- capture stdout, stderr, duration and exit status;
- enforce a finite timeout;
- avoid shell-string construction and `shell=True`;
- independently checksum and smoke-test the built executable;
- stage only the verified executable before atomic activation;
- clean extracted source and staging;
- avoid `/usr/bin` and other unversioned system paths.

A clean online Taskwarrior 3.4.2 build also validates:

```text
/usr/bin/git
/etc/ssl/certs/ca-certificates.crt
https://github.com/corrosion-rs/corrosion.git
```

TLS certificate verification must remain enabled.

On a Raspberry Pi 4B with 4 GB RAM, build concurrency 1 is the recommended
default. Concurrency 2 is validated but provides less memory headroom.

The build phase timeout is initially 7 200 seconds.

## 11. External executable contract

An external executable is accepted only when its exact absolute path identifies
a regular executable file, `_version` reports a supported version and the
isolated lifecycle smoke test succeeds.

The external executable is not copied or modified.

## 12. Version validation

Version detection invokes:

```text
task _version
```

For Milestone 2.2, supported versions are `3.4.x`.

`--version` is not used because Taskwarrior 3.4.2 may return a non-zero status
when runtime `rc.*` arguments are supplied.

## 13. Runtime configuration

The installer-created taskrc contains:

```text
confirmation=no
hooks=0
verbose=nothing
```

Runtime invocation additionally supplies exact configuration, data, HOME and
TASKRC values.

LEA-managed state is isolated from users' personal Taskwarrior data.

## 14. Lifecycle smoke test

The isolated smoke test performs:

1. `_version`;
2. create;
3. exact UUID parse and list;
4. modify;
5. complete;
6. create a second task;
7. delete the second task;
8. verify UUIDs and statuses.

Temporary state is removed on success and ordinary failure.

## 15. Created UUID parsing

Accepted forms are:

```text
Created task <canonical-uuid>.
<canonical-uuid>
```

The raw UUID form exists only for controlled compatibility. No other output is
accepted.

## 16. Installation record

A successful installation writes an atomic strict JSON record containing:

- schema version;
- component;
- version;
- mode;
- canonical platform;
- exact executable path;
- executable SHA-256;
- taskrc, home and data paths;
- smoke-test result;
- canonical UTC timestamp.

Displayed timestamps are localised for the user.

## 17. Idempotency

Re-running against a matching validated installation returns
`already_installed`.

A matching source installation is detected before network checks or compilation.
Production task data is never deleted merely because installation is repeated.

## 18. Upgrade behaviour

The long-term upgrade contract remains:

- install beside the current version;
- validate independently;
- activate atomically;
- preserve the previous executable until success;
- permit rollback;
- never edit TaskChampion SQLite directly.

Automated upgrade orchestration is deferred beyond Milestone 2.2.

## 19. Uninstall behaviour

The long-term uninstall contract distinguishes executable files, configuration
and production data. Production task data is preserved by default.

Uninstall implementation and destructive data removal are deferred beyond
Milestone 2.2 and require their own approval and specification.

## 20. Logging

Every installation phase is designed for structured logs containing operation
identifier, component, phase, timestamps, result, failure code, validated
program arguments, duration and relevant paths.

The installer must not log arbitrary environment dumps.

Structured installer event integration is deferred to the shared runtime logging
milestone; immutable result contracts already expose phase diagnostics.

## 21. Failure codes

```text
taskwarrior_install_invalid_argument
taskwarrior_install_permission_denied
taskwarrior_install_unsupported_platform
taskwarrior_install_unsupported_version
taskwarrior_install_artefact_missing
taskwarrior_install_checksum_mismatch
taskwarrior_install_archive_unsafe
taskwarrior_install_dependency_missing
taskwarrior_install_build_failed
taskwarrior_install_build_timeout
taskwarrior_install_copy_failed
taskwarrior_install_version_check_failed
taskwarrior_install_smoke_test_failed
taskwarrior_install_activation_failed
taskwarrior_install_record_failed
taskwarrior_install_already_installed
```

## 22. Security requirements

The installer must:

- avoid runtime executable discovery through `PATH`;
- avoid `shell=True`;
- reject relative executable paths;
- reject unsafe archive members;
- verify integrity before execution;
- use restrictive permissions;
- isolate smoke-test and production storage;
- avoid direct TaskChampion database access;
- preserve existing task data on failure;
- fail closed when version, integrity or provenance is unverified;
- require verified TLS for clean online source builds.

## 23. Raspberry Pi evidence

Provider benchmark:

```bash
uv run python scripts/benchmark_taskwarrior_provider.py --iterations 5
```

Platform:

```text
Raspberry Pi 4B
4 GB RAM
DietPi 64-bit
ARM64 / AArch64
Taskwarrior 3.4.2
5 iterations
```

| Operation | Median |
|---|---:|
| Inspect | 16.84 ms |
| Create | 38.81 ms |
| List | 19.84 ms |
| Modify | 39.05 ms |
| Complete | 39.26 ms |
| Delete | 38.92 ms |

Real clean source-installer evidence with concurrency 2:

| Phase | Duration |
|---|---:|
| Configure | 22.16 s |
| Build | 3 004.38 s |
| Install | 0.20 s |
| Complete first installation | 3 029.81 s |
| Idempotent second installation | 0.5132 s |

The second run performed no build and returned the same installation record.

## 24. Third-party provenance

The repository contains:

```text
third_party/taskwarrior/VERSION
third_party/taskwarrior/SHA256SUMS
third_party/taskwarrior/LICENSE
third_party/taskwarrior/NOTICE.md
```

Taskwarrior remains under its upstream MIT licence. LEA's AGPL-3.0-only licence
does not replace it.

The verified Taskwarrior 3.4.2 source checksum is:

```text
d302761fcd1268e4a5a545613a2b68c61abd50c0bcaade3b3e68d728dd02e716
```

## 25. Milestone 2.2 acceptance criteria

Milestone 2.2 is complete when:

- provider-neutral task contracts and the Taskwarrior CLI provider exist;
- create, list, modify, complete and delete are deterministic;
- all three installation modes are implemented;
- generic mode dispatch exists;
- SHA-256 verification, safe extraction and isolated staging exist;
- source dependencies and verified network trust are checked;
- lifecycle smoke testing is shared across modes;
- activation and records are atomic and idempotent;
- real Raspberry Pi provider and source-build evidence is recorded;
- licence, provenance and operator documentation are included;
- the complete test and CI gates pass.

The following are explicitly deferred:

- uninstall implementation;
- automated upgrades and rollback UX;
- destructive task-data removal;
- publication automation for Linux binary artefacts;
- fully offline transitive source-build bundles.

These deferrals do not weaken the requirement that future lifecycle operations
preserve production task data by default.
