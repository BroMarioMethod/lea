license: AGPL-3.0-only
---
id: LEA-SPEC-0017
title: Calendar Provider, Managed Toolchain and CalDAV Synchronisation
version: 0.2.1
status: Accepted
review_required: false
---

# Calendar Provider, Managed Toolchain and CalDAV Synchronisation

## Status

| Item | Value |
|---|---|
| Status | Accepted |
| Requires Review | No |
| Milestone | 4.0 |
| Implementation | Started |
| Primary local tools | khal and vdirsyncer |
| Primary CalDAV server | Radicale |
| Android synchronisation | DAVx⁵ |

## 1. Purpose

This specification defines LEA's provider-neutral calendar boundary, its
deterministic khal implementation, managed calendar-client toolchain,
vdirsyncer synchronisation boundary and initial Radicale deployment model.

The design preserves LEA's local-first execution boundary:

- calendar reads use explicit read capabilities;
- calendar mutations become persistent proposals;
- approval does not itself mutate a calendar;
- only explicit execution reaches the deterministic provider;
- synchronisation is an explicit operation;
- audit persistence remains a separate evidence boundary;
- timestamps remain timezone-aware and are stored canonically.

## 2. Architecture

```text
Android calendar application
        ↕
Android calendar provider
        ↕
DAVx⁵
        ↕ CalDAV
Radicale
        ↕ CalDAV
vdirsyncer
        ↕
local vdir calendar collections
        ↕
khal
        ↕
CalendarProvider
        ↕
LEA proposals, permissions and audit
```

Radicale, the managed calendar client toolchain and the Android client are
separate deployment components with separate security and lifecycle
boundaries.

## 3. Managed calendar client toolchain

LEA shall manage compatible versions of khal and vdirsyncer as one calendar
client toolchain.

The installer shall support three explicit installation modes:

```text
verified-network
bundled-wheelhouse
external-executables
```

### 3.1 Verified-network mode

Verified-network mode is the normal online installation path.

It may download packages from an explicitly configured package index because a
normal LEA installation already requires network access to clone or download
the repository.

The installer shall nevertheless remain deterministic:

- khal and vdirsyncer versions are pinned;
- transitive dependencies are locked;
- downloaded distributions are verified against recorded hashes;
- source distributions are rejected unless explicitly approved;
- installation occurs inside an isolated LEA-managed Python environment;
- the exact trusted `uv` executable and Python interpreter are supplied;
- installed commands undergo version and smoke checks;
- activation occurs only after all verification succeeds;
- an installation record identifies the activated toolchain.

Network access must be explicit and bounded. The installer shall not silently
fall back to unpinned versions, alternate indexes or arbitrary packages.

### 3.2 Bundled-wheelhouse mode

Bundled-wheelhouse mode provides an offline-capable installation path.

A release archive may include, or be distributed alongside, a verified
wheelhouse containing all pinned distributions needed by the calendar
toolchain.

This mode is useful when:

- the installation host has no internet connection;
- a user downloads the complete LEA release archive on another machine;
- reproducibility must not depend on package-index availability;
- clean-room or recovery installation is required.

The bundled mode shall use the same version, hash, smoke-test, activation and
installation-record requirements as verified-network mode.

### 3.3 External-executables mode

External-executables mode is an explicit administrator-selected fallback.

It must receive exact absolute paths to both khal and vdirsyncer and verify
their compatibility before activation.

LEA shall not rely on whichever `khal` or `vdirsyncer` command occurs first in
`PATH`.

## 4. Canonical managed paths

The initial system layout is:

```text
/opt/lea-tools/calendar/<toolchain-version>/
/etc/lea/calendar/
/var/lib/lea/calendar/
/var/lib/lea/install/calendar-toolchain.json
```

A managed Python environment shall be located inside the versioned toolchain
root. Its exact internal name may be implementation-defined, but activated
command paths shall be explicit and recorded, resembling:

```text
/opt/lea-tools/calendar/<toolchain-version>/.venv/bin/khal
/opt/lea-tools/calendar/<toolchain-version>/.venv/bin/vdirsyncer
```

Calendar configuration, synchronisation metadata, event data and credentials
must not be stored inside the source repository or activated tool directory.

## 5. Package and artefact policy

The managed calendar toolchain shall use:

- an exact khal version;
- an exact vdirsyncer version;
- a fully locked transitive dependency set;
- SHA-256 verification for downloaded or bundled distributions;
- a declared Python version and supported platform;
- wheel-only installation by default;
- no implicit use of system site packages;
- no mutation of LEA's own application virtual environment.

The installer may use a requirements file or equivalent lock artefact generated
during release preparation.

The lock artefact must be reviewable and stored in the repository. Binary wheel
files need not be committed to Git.

## 6. Installation workflow

The preferred verified-network workflow is:

```text
validate configuration
    → inspect trusted uv and Python executables
    → create private staging directory
    → create isolated Python environment
    → download exact locked distributions
    → verify hashes
    → install wheel-only dependency set
    → inspect managed Python version
    → verify khal version
    → verify vdirsyncer version
    → run smoke tests
    → provision runtime layout
    → atomically activate versioned toolchain
    → write installation record
```

The bundled-wheelhouse workflow replaces the download phase with verification
and safe extraction of the supplied wheelhouse archive.

The initial bundled archive format shall be a TAR-compatible archive containing
a flat set of regular `.whl` files, optionally beneath one common wrapper
directory. It may additionally contain one `manifest.json` or
`wheelhouse-manifest.json` regular file. Absolute paths, traversal, nested
wheel directories, duplicate destinations, symbolic links, hard links and
special filesystem objects shall be rejected.

A command policy may resemble:

```text
uv venv
    --no-project
    --no-python-downloads
    --relocatable
    <staged-environment>

uv pip sync
    --python <staged-python>
    --require-hashes
    --only-binary :all:
    --strict
    <verified-requirements>
```

Verified-network mode may use an explicitly configured package index.

Bundled-wheelhouse mode shall additionally use:

```text
--no-index
--find-links <verified-wheel-directory>
--offline
```

Exact arguments remain private to the installer and shall be covered by tests.

Managed environments that will be atomically moved from private staging into
their versioned toolchain root shall be created with relocatable entry points.

## 7. Installation records and activation

The installation record shall contain at least:

- schema version;
- component identifier;
- toolchain version;
- installation mode;
- platform identifier;
- Python version;
- khal version;
- vdirsyncer version;
- exact khal executable path;
- exact vdirsyncer executable path;
- lock or manifest SHA-256;
- smoke-test status;
- canonical UTC installation timestamp.

Activation shall be idempotent when the existing installation and record match
the requested toolchain exactly.

Mismatched existing files, versions or hashes shall fail closed and shall not be
overwritten silently.

## 8. Runtime data layout

The initial calendar runtime layout shall provide separate paths for:

```text
/etc/lea/calendar/khal.conf
/etc/lea/calendar/vdirsyncer.conf
/var/lib/lea/calendar/vdirs/
/var/lib/lea/calendar/khal/
/var/lib/lea/calendar/vdirsyncer-status/
```

Secret values shall be stored separately from ordinary configuration.

Password or token contents must never be committed, embedded in generated
documentation, rendered in user-facing diagnostics or passed through shell
command construction.

## 9. Calendar provider boundary

LEA shall expose a provider-neutral boundary resembling:

```text
inspect()
list_calendars()
list_events(query)
show_event(calendar_id, event_uid)
create_event(request)
modify_event(request)
cancel_event(calendar_id, event_uid)
```

The provider shall use LEA-owned immutable request, result and event contracts.

Existing-event mutations shall use stable calendar and event identifiers.
Mutable display text must not be treated as identity.

## 10. khal adapter

The initial provider shall invoke an exact managed khal executable using an
explicit configuration file and environment.

The adapter shall:

- avoid shell command construction;
- use argument sequences and `shell=False`;
- capture UTF-8 output;
- apply finite timeouts;
- fail closed on malformed or ambiguous output;
- use isolated configuration and data paths;
- read back canonical state after mutations where supported;
- avoid interactive editor behaviour;
- avoid implicit calendar selection.

Where khal lacks an adequately structured mutation or read interface, LEA may
use a strictly validated iCalendar library behind the same provider boundary.
Such access must remain deterministic and operate only within configured vdir
collections.

## 11. Synchronisation boundary

Vdirsyncer synchronisation is separate from local calendar mutation.

LEA shall not silently synchronise after every read or write. Supported
operations shall distinguish:

```text
calendar local mutation
calendar synchronisation
calendar synchronisation inspection
```

Synchronisation may involve network access and conflicts and therefore requires
its own result, permission, audit and failure semantics.

## 12. Radicale boundary

Radicale is a separately managed CalDAV server component.

Its installer and service lifecycle shall not be embedded within the khal
provider. Radicale shall provide:

- authenticated user accounts;
- collection-level access control;
- private persistent storage;
- backup-compatible data;
- health inspection;
- controlled network exposure.

Initial live acceptance should occur on the private LAN. Remote access should
prefer a private VPN boundary rather than exposing CalDAV directly to the
public internet.

## 13. Android boundary

DAVx⁵ is an Android-side synchronisation application and is not installed by
the Raspberry Pi installer.

LEA documentation shall guide an authorised user through:

- adding the CalDAV account;
- selecting permitted calendars;
- enabling Android calendar synchronisation;
- verifying two-way event propagation;
- revoking access safely.

Phone credentials and device-specific identifiers remain outside Git.

## 14. Permissions

The initial permission namespace shall include separate capabilities equivalent
to:

```text
Calendars.Read
Calendars.Write
Calendars.Delete
Calendars.Sync
```

Read and write permissions are independent. Neither implies the other.

Calendar collection access shall also be restricted by configured user policy.
A general write capability must not grant access to every user's private
calendar.

## 15. Proposal and risk policy

Interactive calendar mutations shall use persistent proposals.

Initial risk guidance:

```text
calendar.create    low or medium
calendar.modify    medium
calendar.cancel    medium
calendar.delete    high when permanent deletion is supported
calendar.sync      medium
```

Channel-originated mutations require explicit confirmation even when a
provider-neutral builder would otherwise use `when_required`.

## 16. Time handling

Persistent timestamps shall be timezone-aware.

LEA shall distinguish:

- all-day dates;
- local timed events with an IANA timezone;
- canonical UTC instants;
- floating times, which shall initially be rejected unless explicitly
  supported.

Presentation uses the configured display timezone without changing the stored
instant.

Daylight-saving transitions, recurrence and timezone conversion require
dedicated tests before broad live use.

## 17. Initial non-goals

Milestone 4.0 initially excludes:

- Google-specific OAuth integration;
- Gmail email access;
- public internet exposure of Radicale;
- automatic VPN provisioning;
- recurring-event authoring;
- invitation delivery;
- attendee response processing;
- free/busy federation;
- arbitrary raw khal or vdirsyncer commands;
- silent conflict resolution;
- bulk destructive operations;
- Android application installation.

## 18. Delivery slices

```text
4.0.1 Managed calendar toolchain contracts and provisioning
4.0.2 Calendar domain contracts and provider boundary
4.0.3 Local vdir and khal adapter
4.0.4 Read-only calendar actions
4.0.5 Proposal builders and mutation handlers
4.0.6 Explicit vdirsyncer synchronisation
4.0.7 Radicale provisioning and access control
4.0.8 CLI and Telegram calendar commands
4.0.9 Android DAVx⁵ live acceptance
```

## 19. Acceptance criteria

Milestone 4.0 is complete only when:

- the managed calendar toolchain installs reproducibly;
- verified-network installation uses pinned and hash-verified distributions;
- bundled-wheelhouse installation works without network access;
- khal and vdirsyncer are invoked through exact managed paths;
- local calendar operations pass isolated tests;
- mutations cannot occur before explicit execution;
- synchronisation is explicit and audited;
- Radicale user isolation is verified;
- Android two-way synchronisation passes;
- secrets remain outside Git;
- installation, upgrade and removal paths are documented and tested.
