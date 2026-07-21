# LEA-SPEC-0012: Taskwarrior Installer Contract

- **Status:** Accepted
- **Version:** 1.0
- **Date:** 21 July 2026
- **Related ADR:** `ADR-0012_TASKWARRIOR_DISTRIBUTION.md`
- **Related provider specification:** `LEA-SPEC-0011_TASK_PROVIDER_TASKWARRIOR_CLI.md`

## 1. Purpose

This specification defines the deterministic contract for installing, validating and configuring the Taskwarrior runtime used by LEA.

It does not define a general-purpose Taskwarrior installer. It defines only the Taskwarrior installation required by LEA.

## 2. Supported installation modes

The installer must support exactly these modes:

```text
bundled-binary
source-build
external-executable
```

The default mode is `bundled-binary`.

An automatic mode may select `bundled-binary` first and fall back to `source-build` only when the user explicitly permits compilation.

The installer must never silently switch to an executable found through `PATH`.

## 3. Required inputs

### 3.1 Common inputs

- installation root;
- LEA service user and group;
- Taskwarrior version;
- configuration directory;
- state directory;
- tools directory;
- non-interactive or interactive execution mode.

### 3.2 Bundled-binary inputs

- platform identifier;
- binary artefact path;
- expected SHA-256 checksum;
- licence and provenance records.

### 3.3 Source-build inputs

- source archive path or pinned source URL;
- expected SHA-256 checksum;
- build directory;
- installation prefix;
- build concurrency;
- explicit dependency policy.

### 3.4 External-executable inputs

- absolute executable path.

## 4. Canonical paths

Default production paths:

```text
Taskwarrior executable:
/opt/lea-tools/taskwarrior/<version>/bin/task

Taskwarrior configuration:
/etc/lea/taskwarrior/taskrc

Taskwarrior state root:
/var/lib/lea/taskwarrior

Taskwarrior home:
/var/lib/lea/taskwarrior/home

Taskwarrior data:
/var/lib/lea/taskwarrior/data

Installation record:
/var/lib/lea/install/taskwarrior.json
```

Paths may be overridden only by explicit installer arguments or configuration.

Every persisted path must be absolute.

## 5. Platform identifiers

The installer must normalise platforms to explicit canonical identifiers.

Initial canonical identifiers:

```text
linux-x86_64
linux-aarch64
```

The installer must recognise common architecture aliases and normalise them before artefact selection.

At minimum:

```text
x86_64  -> linux-x86_64
amd64   -> linux-x86_64
aarch64 -> linux-aarch64
arm64   -> linux-aarch64
```

This includes the 64-bit Raspberry Pi 4B pilot platform running DietPi.

Unknown platforms must fail with a structured unsupported-platform result unless source-build mode is explicitly selected.

## 6. Installation phases

The installer must execute these phases in order:

1. preflight;
2. source or artefact selection;
3. integrity verification;
4. staged installation;
5. permissions and ownership;
6. version validation;
7. isolated configuration creation;
8. lifecycle smoke test;
9. atomic activation;
10. installation-record creation;
11. final report.

A failure before atomic activation must not replace a previously working installation.

## 7. Preflight contract

Preflight must validate:

- the installer has required privileges;
- destination parent directories are writable or creatable;
- required disk space is available;
- platform is supported for the selected mode;
- no required input is blank;
- all configured paths are absolute;
- the requested version is supported;
- temporary directories are on a usable filesystem.

Source-build preflight must report missing build dependencies before compilation begins.

## 8. Integrity verification

LEA-provided binaries and pinned source archives must be verified with SHA-256 before use.

A checksum mismatch must:

- stop installation;
- delete or quarantine the staged artefact;
- preserve any active installation;
- return a structured failure;
- record no successful installation state.

Checksums must be compared using lower-case hexadecimal form.

## 9. Binary installation

Bundled binaries must be copied into a staging directory under the target tools root.

The installer must:

- avoid executing directly from a download or repository path;
- set executable permissions explicitly;
- avoid world-writable permissions;
- preserve the Taskwarrior licence and provenance files;
- verify the staged executable before activation.

The final versioned executable must not be overwritten in place. Replacement must use a new staged directory followed by atomic activation.

## 10. Source-build contract

The source build must:

- unpack only after checksum verification;
- reject unsafe archive paths;
- build in a temporary directory;
- avoid modifying the source archive;
- use an explicit installation prefix;
- capture build stdout, stderr, duration and exit status;
- enforce a finite build timeout;
- avoid shell-string construction where practical;
- install only after a successful build;
- verify the installed executable independently.

The source build must not install Taskwarrior into `/usr/bin` or another unversioned system path.

## 11. External executable contract

An external executable is accepted only when:

- the configured path is absolute;
- the file exists;
- it is a regular file;
- it is executable by the LEA runtime user;
- `_version` succeeds;
- the returned version matches the supported policy;
- the isolated lifecycle smoke test succeeds.

The executable is not copied unless an explicit installer option requests managed copying.

## 12. Version validation

Version detection must invoke:

```text
task _version
```

with LEA's explicit runtime configuration arguments and environment.

For Milestone 2.2, supported versions are:

```text
3.4.x
```

`--version` must not be used by the LEA adapter because Taskwarrior 3.4.2 may return a non-zero status when runtime `rc.*` arguments are present.

## 13. Runtime configuration

The installer-created `taskrc` must initially include:

```text
confirmation=no
hooks=0
verbose=nothing
```

The runtime invocation must additionally supply:

- exact `rc:<taskrc-path>`;
- exact `rc.data.location:<data-path>`;
- `rc.confirmation:no`;
- `rc.verbose:nothing`;
- explicit `HOME`;
- explicit `TASKRC`.

The taskrc file and state directories must be owned by the LEA service account and must not be writable by unrelated users.

## 14. Lifecycle smoke test

The smoke test must use a temporary isolated Taskwarrior state directory and must not modify production task data.

It must perform:

1. `_version`;
2. create one task;
3. parse the created UUID;
4. export the exact task;
5. modify the exact task;
6. complete the exact task;
7. create a second task;
8. delete the second task;
9. verify returned statuses and UUIDs.

The smoke test must clean up its temporary directory on success and ordinary failure.

## 15. Created UUID parsing

Taskwarrior 3.4.2 may return creation output in this form:

```text
Created task <uuid>.
```

The installer and provider may also accept a raw canonical UUID for compatibility with controlled test doubles.

No other output form may be accepted.

## 16. Installation record

A successful installation must write a machine-readable record containing at least:

```json
{
  "schema_version": 1,
  "component": "taskwarrior",
  "version": "3.4.2",
  "mode": "bundled-binary",
  "platform": "linux-aarch64",
  "executable": "/opt/lea-tools/taskwarrior/3.4.2/bin/task",
  "sha256": "<lower-case hexadecimal checksum>",
  "taskrc": "/etc/lea/taskwarrior/taskrc",
  "home": "/var/lib/lea/taskwarrior/home",
  "data": "/var/lib/lea/taskwarrior/data",
  "smoke_test": "passed",
  "installed_at": "<UTC timestamp>"
}
```

The record must be written atomically.

Displayed timestamps must be localised for the user, while stored timestamps may remain UTC.

## 17. Idempotency

Re-running the installer with the same validated version and checksum must be safe.

The installer should report:

```text
already-installed
```

when the active installation already matches the requested state.

Configuration and permission drift may be repaired when doing so does not overwrite user-owned data.

Production task data must never be deleted merely because installation is repeated.

## 18. Upgrade behaviour

An upgrade must:

- install the new version beside the existing version;
- validate it independently;
- run the smoke test;
- atomically switch the active configured path;
- retain the previous version until activation succeeds;
- permit rollback to the previous validated executable.

The installer must not migrate or directly edit TaskChampion SQLite.

## 19. Uninstall behaviour

Uninstall must distinguish between:

- executable and installer-managed files;
- configuration;
- production task data.

By default, uninstall must preserve production task data.

Task-data removal requires an explicit destructive option and confirmation outside automated agent execution.

## 20. Logging

Every installation phase must emit structured logs containing:

- operation identifier;
- component;
- phase;
- start and finish timestamps;
- result;
- error code when applicable;
- executed program and argument list, excluding secrets;
- duration;
- relevant validated paths.

Logs must not contain arbitrary environment-variable dumps.

## 21. Failure codes

The installer contract reserves these codes:

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

Error messages must be actionable and must not expose private data.

## 22. Security requirements

The installer must:

- never use `PATH` to select the runtime Taskwarrior executable;
- avoid `shell=True`;
- reject relative executable paths;
- reject unsafe archive members;
- verify integrity before execution;
- use restrictive permissions;
- isolate smoke-test and production storage;
- avoid direct TaskChampion database access;
- avoid deleting existing task data during failed installation;
- fail closed when version or provenance cannot be established.

## 23. Benchmark requirement

The installer documentation must include the benchmark command:

```bash
uv run python scripts/benchmark_taskwarrior_provider.py --iterations 5
```

The recorded Raspberry Pi pilot baseline was measured on:

```text
Device: Raspberry Pi 4B
Memory: 4 GB
Operating system: DietPi, 64-bit
Architecture: ARM64 / AArch64
Taskwarrior: 3.4.2
Iterations: 5
```

| Operation | Median |
|---|---:|
| Inspect | 16.84 ms |
| Create | 38.81 ms |
| List | 19.84 ms |
| Modify | 39.05 ms |
| Complete | 39.26 ms |
| Delete | 38.92 ms |

This baseline satisfies the initial Raspberry Pi 4B benchmark requirement for the pilot environment. Additional benchmark runs should still be recorded for release artefacts and materially different Raspberry Pi configurations.

Benchmark results are evidence, not hard runtime guarantees.

## 24. Acceptance criteria

This specification is satisfied when:

- all three installation modes are implemented;
- checksums are verified;
- exact paths are persisted;
- `_version` is used;
- isolated configuration and storage are created;
- lifecycle smoke testing passes;
- installation records are atomic;
- repeated installation is safe;
- upgrade rollback is possible;
- uninstall preserves task data by default;
- structured failure codes are tested;
- Linux x86-64 and AArch64 release paths are documented;
- Raspberry Pi 4B results are recorded;
- the complete LEA test suite passes.
