# Taskwarrior Installation for LEA

## Purpose

LEA uses Taskwarrior 3.4.x through an explicit provider and installer contract.
It does not use a user's personal Taskwarrior configuration or database.

The normal runtime path is:

```text
/opt/lea-tools/taskwarrior/<version>/bin/task
```

The LEA-managed runtime layout is:

```text
/etc/lea/taskwarrior/taskrc
/var/lib/lea/taskwarrior/home
/var/lib/lea/taskwarrior/data
/var/lib/lea/install/taskwarrior.json
```

All paths may be overridden only through explicit validated configuration.

## Installation modes

### Bundled binary

This is the recommended default.

LEA verifies a platform-specific artefact with SHA-256, copies it into private
staging, runs a complete isolated lifecycle smoke test, provisions the runtime
layout and atomically activates the versioned installation.

Initial canonical platform identifiers are:

```text
linux-aarch64
linux-x86_64
```

### Pinned source build

Use source-build mode when no verified binary exists or when an administrator
explicitly chooses local compilation.

The source archive must be local, absolute and accompanied by its expected
SHA-256 checksum. The verified Taskwarrior 3.4.2 archive is:

```text
Filename: task-3.4.2.tar.gz
SHA-256: d302761fcd1268e4a5a545613a2b68c61abd50c0bcaade3b3e68d728dd02e716
```

A clean online build requires these exact dependencies on the Debian-family
pilot platform:

```text
/usr/bin/cmake
/usr/bin/c++
/usr/bin/make
/usr/bin/cargo
/usr/bin/rustc
/usr/bin/pkg-config
/usr/bin/git
/etc/ssl/certs/ca-certificates.crt
```

It also requires `pkg-config --exists uuid`, Rust 1.81.0 or newer and verified
HTTPS access to the Corrosion repository used by Taskwarrior's CMake build.

LEA does not disable TLS verification and does not use `shell=True`.

For a Raspberry Pi 4B with 4 GB RAM, use:

```text
Recommended default build concurrency: 1
Validated faster build concurrency: 2
Build phase timeout: 7 200 seconds
```

Concurrency 2 completed successfully but used swap and left less memory
headroom. Concurrency 1 is the safer production default.

### External executable

An administrator may register an existing executable using an explicit absolute
path. LEA does not discover it through `PATH` and does not copy or alter it.

The executable must:

- exist as a regular executable file;
- report a supported version through `_version`;
- pass the complete isolated lifecycle smoke test.

## Generic entry point

Callers should use the generic dispatcher:

```python
install_taskwarrior(config)
```

It selects exactly one installer according to `config.mode`.

The mode-specific functions remain available for focused tests and controlled
administrative workflows.

## Installation phases

The managed binary and source-build paths use the following sequence:

```text
configuration validation
→ preflight
→ integrity verification
→ private staging or safe source extraction
→ version and lifecycle validation
→ runtime-layout provisioning
→ atomic activation
→ installation-record persistence
```

A failure before activation preserves the existing working installation.

## Safe source extraction

LEA manually extracts verified TAR members and rejects:

- absolute archive paths;
- path traversal;
- hard links;
- special files;
- duplicate destinations;
- symbolic links that escape the archive;
- symbolic links to missing or non-regular members.

Safe internal symbolic links in the official archive are materialised as regular
files. No archive symlink is created on the host filesystem.

## Runtime isolation

LEA invokes Taskwarrior with explicit values for:

- executable path;
- `HOME`;
- `TASKRC`;
- taskrc path;
- data location;
- confirmation behaviour;
- verbosity.

The initial taskrc contains:

```text
confirmation=no
hooks=0
verbose=nothing
```

LEA does not read or modify `/home/<user>/.task` and never accesses
TaskChampion SQLite directly.

## Lifecycle smoke test

The smoke test uses disposable storage and performs:

1. `_version`;
2. task creation;
3. exact UUID parsing and listing;
4. task modification;
5. task completion;
6. second task creation;
7. second task deletion.

Production task data is not touched.

## Idempotency

A repeated installation of the same validated installation returns
`already_installed` without rebuilding or replacing the executable.

The real Raspberry Pi source-installer pilot produced:

```text
First installation:
  total duration: 3 029.81 seconds
  configure: 22.16 seconds
  build: 3 004.38 seconds
  install: 0.20 seconds

Second installation:
  duration: 0.5132 seconds
  build performed: no
  record matched: yes
```

## Provider benchmark

Run:

```bash
uv run python scripts/benchmark_taskwarrior_provider.py --iterations 5
```

Pilot platform:

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

## Troubleshooting

### Source build reports an invalid CA certificate bundle

Validate:

```bash
grep -c '^-----BEGIN CERTIFICATE-----$' /etc/ssl/certs/ca-certificates.crt
grep -c '^-----END CERTIFICATE-----$' /etc/ssl/certs/ca-certificates.crt
```

The counts must be equal and non-zero. Rebuild the Debian certificate store
rather than disabling TLS verification.

### Corrosion cannot be cloned

Test verified access directly:

```bash
git ls-remote https://github.com/corrosion-rs/corrosion.git HEAD
```

Do not configure `http.sslVerify=false`.

### The build appears frozen

The installer captures build output. A clean Raspberry Pi build can spend about
50 minutes compiling Rust and C++ dependencies without printing to the calling
terminal.

Inspect it from another session:

```bash
ps -eo pid,ppid,stat,etime,%cpu,%mem,rss,cmd --sort=-%cpu |
    grep -E 'cmake|cargo|rustc|cc1plus|c\+\+'
```

Active compiler processes indicate progress.

### Out-of-memory risk

Use build concurrency 1 on a 4 GB Raspberry Pi. Avoid running local model
inference during compilation. Source compilation is an administrative fallback,
not a normal runtime workload.

### Existing personal tasks

LEA's installer must not remove or migrate personal Taskwarrior data. Uninstall
and destructive data-removal workflows are deferred and require a separate
specification.

## Deferred lifecycle operations

Milestone 2.2 establishes installation, validation, activation and idempotency.

The following are intentionally deferred:

- automated upgrade orchestration;
- rollback command UX;
- uninstall implementation;
- destructive task-data removal;
- automated publication of platform release artefacts;
- fully offline packaging of transitive source-build dependencies.

Production task data must be preserved by default in every later lifecycle
operation.
