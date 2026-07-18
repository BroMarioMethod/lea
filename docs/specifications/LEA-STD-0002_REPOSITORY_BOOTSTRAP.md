---
title: Repository Bootstrap Standard
document_id: LEA-STD-0002
version: 0.1.1
status: Accepted
authors:
  - Marius du Preez
  - OpenAI ChatGPT
license: GPL-3.0
created: 2026-07-18
last_updated: 2026-07-18
review_required: false
---

# Repository Bootstrap Standard

## Document Status

| Item | Value |
|---|---|
| Status | Accepted |
| Requires Review | No |
| Implementation | Complete |
| Test Status | Manually Tested |

---

## 1. Purpose

This standard defines the required behaviour of LEA's repository bootstrap process.

The bootstrap process SHALL create or repair the canonical repository structure defined by LEA-STD-0001 without overwriting valid existing project content.

This standard defines observable behaviour independently of the implementation language.

---

## 2. Why?

A deterministic bootstrap process allows contributors to establish a valid LEA repository without manually creating every directory and placeholder file.

The process also provides a safe, repeatable method for repairing missing repository structure.

Separating the repository layout definition from bootstrap behaviour allows the layout to evolve without requiring equivalent changes to the bootstrap implementation logic.

---

## 3. Scope

This standard defines:

- bootstrap inputs;
- required directory and file creation;
- repeated execution behaviour;
- repair behaviour;
- protection of existing content;
- status output;
- exit status behaviour;
- validation expectations;
- testing requirements.

This standard does not define:

- deployment directories;
- runtime data;
- Python environment creation;
- package installation;
- operating-system service configuration;
- user accounts or filesystem ownership;
- repository migration between incompatible layout versions.

---

## 4. Engineering Principles

### EP-001 — Idempotency

Running the bootstrap process repeatedly against a valid repository SHALL produce no destructive changes.

### EP-002 — Repair Without Replacement

The bootstrap process SHALL restore missing required repository paths while preserving existing files and directories.

### EP-003 — Declarative Layout

The required repository structure SHALL be represented as machine-readable configuration.

The bootstrap implementation SHALL interpret the configuration rather than embedding the complete canonical layout directly in executable logic.

### EP-004 — Safe Failure

When the bootstrap process cannot complete safely, it SHALL stop and report the reason without knowingly leaving corrupted project content.

### EP-005 — Observable Behaviour

Every attempted bootstrap action SHALL produce a clear human-readable status.

---

## 5. Requirements

### RB-001 — Canonical Layout Source

The bootstrap process SHALL read the required repository layout from:

```text
config/repository_layout.toml
```

This file SHALL be the machine-readable canonical source used by repository bootstrap and validation tools.

### RB-002 — Repository Root

The bootstrap process SHALL operate on an explicitly resolved repository root.

The default repository root MAY be the current working directory.

The implementation SHALL NOT silently assume `/opt/lea` when operating on another repository path.

### RB-003 — Required Directories

The bootstrap process SHALL create every required directory declared in `config/repository_layout.toml` when that directory does not already exist.

### RB-004 — Required Files

The bootstrap process SHALL create required repository skeleton files declared in `config/repository_layout.toml` when those files do not already exist.

### RB-005 — Existing Files

The bootstrap process SHALL NOT overwrite a non-empty existing file.

### RB-006 — Existing Directories

An existing directory matching a required directory path SHALL be treated as valid.

### RB-007 — Path-Type Conflict

If a required directory path already exists as a file, the bootstrap process SHALL report an error and SHALL NOT replace it automatically.

If a required file path already exists as a directory, the bootstrap process SHALL report an error and SHALL NOT replace it automatically.

### RB-008 — Repair Behaviour

When required paths are missing, repeated execution SHALL recreate only the missing paths.

Existing valid repository content SHALL remain unchanged.

### RB-009 — Placeholder Files

Empty directories that must be tracked by Git SHALL contain a `.gitkeep` file unless the directory already contains tracked or project-relevant content.

The bootstrap process SHALL NOT create `.gitkeep` in a non-empty directory.

### RB-010 — Parent Directories

The bootstrap process SHALL create missing parent directories before creating a required child path.

### RB-011 — Default File Content

Where the layout configuration defines default file content, the bootstrap process SHALL write that content only when creating a new file.

Where no default content is defined, the bootstrap process MAY create an empty placeholder file.

### RB-012 — Status Output

Each action SHALL produce one of the following status labels:

```text
[ OK ]
[SKIP]
[ERROR]
```

The status label SHALL be followed by the affected relative path.

Example:

```text
[ OK ] scripts/
[SKIP] README.md
[ERROR] config/
```

### RB-013 — Status Meaning

`[ OK ]` SHALL indicate that a required path was created successfully.

`[SKIP]` SHALL indicate that an existing valid path was preserved.

`[ERROR]` SHALL indicate that an operation could not be completed safely.

### RB-014 — Summary Output

After processing the layout, the bootstrap process SHALL report totals for:

- paths created;
- paths skipped;
- errors encountered.

### RB-015 — Exit Status

The bootstrap process SHALL return exit status `0` when all required paths exist or were created successfully.

It SHALL return a non-zero exit status when one or more errors prevent the repository from satisfying the declared layout.

### RB-016 — Relative Paths

Paths in `config/repository_layout.toml` SHALL be relative to the resolved repository root.

Absolute paths and parent-directory traversal using `..` SHALL be rejected.

### RB-017 — Runtime Exclusion

The bootstrap process SHALL NOT create runtime-only directories such as model storage, logs, caches or generated indexes unless a future repository standard explicitly adds them to the Git repository layout.

### RB-018 — Secrets

The bootstrap process SHALL NOT create files containing real credentials, tokens or secrets.

An `.env.example` file MAY contain documented placeholder values.

### RB-019 — Git Independence

The bootstrap process SHALL be capable of creating the repository skeleton before Git has been initialised.

It SHALL NOT require access to a remote Git repository.

### RB-020 — Network Independence

The repository bootstrap process SHALL NOT require Internet or network access.

### RB-021 — Language Convention

Bootstrap messages, generated documentation and comments SHALL use UK English.

Metric and SI units SHALL be used where measurements are required.

---

## 6. Repository Layout Configuration

The layout configuration SHALL distinguish between:

- directories;
- required files;
- tracked empty directories;
- optional default file content.

The initial format SHALL remain deliberately minimal.

A representative structure is:

```toml
schema_version = 1

directories = [
    ".github/workflows",
    "config",
    "context",
    "docs/adr",
    "docs/assets",
    "docs/rfc",
    "docs/specifications",
    "knowledge",
    "plugins",
    "prompts",
    "scripts",
    "src/lea",
    "tests",
    "tools",
]

required_files = [
    ".env.example",
    ".gitignore",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
]

tracked_empty_directories = [
    ".github/workflows",
    "context",
    "docs/adr",
    "docs/assets",
    "docs/rfc",
    "knowledge",
    "plugins",
    "prompts",
    "scripts",
    "src/lea",
    "tests",
    "tools",
]
```

The exact configuration format SHALL be validated by implementation tests.

Python project files such as `pyproject.toml` and `uv.lock` SHALL be created during Python project initialisation and SHALL NOT be fabricated as empty placeholders by the initial bootstrap implementation.

---

## 7. Processing Sequence

The bootstrap implementation SHALL perform operations in this order:

1. Resolve the repository root.
2. Locate and parse `config/repository_layout.toml`.
3. Validate the configuration and all declared paths.
4. Create missing required directories.
5. Create missing required files.
6. Create `.gitkeep` files in qualifying empty tracked directories.
7. Validate the resulting repository structure.
8. Print the summary.
9. Return the appropriate exit status.

Configuration validation SHALL occur before repository modifications begin wherever practical.

---

## 8. Safety Rules

The bootstrap process SHALL NOT:

- delete existing files or directories;
- overwrite non-empty files;
- rename conflicting paths automatically;
- follow a declared path outside the repository root;
- download dependencies;
- initialise or modify Git history;
- create runtime state;
- insert credentials;
- change filesystem ownership or permissions without an explicit future requirement.

---

## 9. Testing Requirements

Automated tests SHALL verify at least the following cases:

1. Bootstrap into a nearly empty repository.
2. Bootstrap into an already valid repository.
3. Repair one missing directory.
4. Repair one missing required file.
5. Preserve an existing non-empty file.
6. Preserve an existing non-empty directory.
7. Detect a required directory represented by a file.
8. Detect a required file represented by a directory.
9. Reject an absolute configured path.
10. Reject a configured path containing parent traversal.
11. Return exit status `0` after successful creation.
12. Return a non-zero exit status after an unrecoverable conflict.
13. Operate without network access.

Tests SHALL use temporary directories and SHALL NOT modify the active LEA repository.

---

## 10. Ownership

| Asset | Owner | Git |
|---|---|---|
| Bootstrap standard | Developer | Yes |
| Layout configuration | Developer | Yes |
| Bootstrap implementation | Developer | Yes |
| Generated repository skeleton | Developer | Yes |
| Existing user-maintained content | User | According to repository policy |
| Bootstrap status output | Runtime | No |

---

## 11. Out of Scope

This standard does not define:

- deployed application bootstrap;
- Raspberry Pi operating-system preparation;
- Python installation;
- `uv` installation;
- model installation;
- database initialisation;
- Git repository creation;
- remote repository configuration;
- upgrade migrations;
- backup restoration.

---

## 12. Success Criteria

This standard is satisfied when:

- the layout configuration can be parsed deterministically;
- bootstrap creates every missing required repository path;
- repeated execution causes no destructive changes;
- damaged structure can be repaired;
- existing content is preserved;
- unsafe path conflicts are reported;
- output follows the required status format;
- all defined bootstrap tests pass.

---

## 13. Future Considerations

Future revisions MAY add:

- layout configuration version migration;
- checksums for managed template files;
- dry-run operation;
- machine-readable JSON output;
- optional repository profiles;
- generated layout documentation;
- permission validation;
- a dedicated repository validation command;
- automatic comparison between LEA-STD-0001 and the machine-readable layout.

---

## 14. References

- LEA-STD-0001 — Repository Layout Standard
- RFC 2119 — Key words for use in RFCs to Indicate Requirement Levels
- RFC 8174 — Ambiguity of Uppercase vs Lowercase in RFC 2119 Key Words
