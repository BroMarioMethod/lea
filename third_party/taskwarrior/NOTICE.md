# Taskwarrior Third-Party Notice

LEA integrates with Taskwarrior as a distinct third-party component.

## Component

- **Name:** Taskwarrior
- **Version:** 3.4.2
- **Upstream project:** GothenburgBitFactory/taskwarrior
- **Licence:** MIT
- **Upstream source archive:** `task-3.4.2.tar.gz`
- **Verified source SHA-256:** `d302761fcd1268e4a5a545613a2b68c61abd50c0bcaade3b3e68d728dd02e716`
- **Verified archive size during the Raspberry Pi pilot:** approximately 940 KiB

The authoritative licence text is preserved in `LICENSE`.

## Separation from LEA

Taskwarrior is not relicensed under LEA's AGPL-3.0-only licence. LEA invokes a
validated Taskwarrior executable through a provider adapter. Taskwarrior source,
binaries, licence notices and provenance remain distinct from `src/lea`.

## Distribution modes

LEA supports:

1. a verified LEA-provided binary;
2. a pinned local source build;
3. an administrator-supplied executable at an explicit absolute path.

Release artefacts must preserve this notice, the upstream licence and the
checksum belonging to each distributed artefact.

## Source-build network dependency

A clean Taskwarrior 3.4.2 source build uses CMake FetchContent to retrieve the
Corrosion integration from its HTTPS Git repository. LEA therefore validates
the exact Git executable, the system CA bundle and verified HTTPS reachability
before beginning a clean online source build.

This network-assisted build path does not weaken verification of the
Taskwarrior source archive. The archive is SHA-256 verified before extraction.
A future offline build bundle may pin and package all transitive build inputs.

## Release provenance

Each LEA release that includes a Taskwarrior binary should record:

- target platform;
- Taskwarrior version;
- source archive checksum;
- compiler and build-tool versions;
- build command or reproducible build workflow;
- produced executable checksum;
- build date;
- builder or CI identity;
- smoke-test result.

No unrecorded binary may be selected through `PATH`.
