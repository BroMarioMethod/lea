---
title: Repository Layout Standard
document_id: LEA-STD-0001
version: 0.1.0
status: Accepted
authors:
  - Marius du Preez
  - OpenAI ChatGPT
license: GPL-3.0
created: 2026-07-18
last_updated: 2026-07-18
review_required: false
---

# Repository Layout Standard

## Document Status

| Item | Value |
|---|---|
| Status | Accepted |
| Requires Review | No |
| Implementation | Not Started |
| Test Status | Not Tested |

---

## 1. Purpose

This standard defines the canonical Git repository layout for the LEA project.

The repository structure SHALL provide a predictable, maintainable and scalable foundation for contributors, development tooling and documentation.

Every directory and root-level file SHALL have a clearly defined purpose.

This standard defines **what** the repository SHALL contain. It does not prescribe the implementation used to create the repository structure.

---

## 2. Why?

A consistent repository layout reduces contributor confusion, prevents unrelated concerns from becoming mixed together and allows development tools to locate project resources predictably.

LEA SHALL follow familiar Linux and Python project conventions wherever those conventions support clarity, maintainability and interoperability.

The Git repository SHALL be kept separate from deployed runtime state. Models, logs, caches, indexes and other machine-specific data belong to the deployment or workspace layout, which will be defined separately.

---

## 3. Scope

This standard defines:

- the canonical project root;
- the required top-level repository directories;
- required documentation subdirectories;
- the purpose of each directory;
- ownership classifications;
- Git tracking expectations;
- lifecycle classifications;
- the distinction between repository contents and runtime state.

This standard does not define:

- the deployed filesystem layout;
- Linux service accounts or filesystem permissions;
- Python packaging configuration;
- dependency management;
- the internal structure of LEA domains;
- the bootstrap implementation.

---

## 4. Engineering Principles

### EP-001 — Single Canonical Source

Every piece of persistent information SHALL have one canonical source.

Derived indexes, caches and projections MAY exist, but they SHALL be reproducible from their canonical source.

### EP-002 — Configuration and Behaviour

Configuration SHALL be represented as data where practical.

Behaviour SHALL be implemented in code.

### EP-003 — Repository and Runtime Separation

Version-controlled repository contents SHALL remain separate from runtime-generated and machine-specific state.

### EP-004 — Human Ownership

AI-generated changes SHALL remain proposals until they are validated and accepted through deterministic application logic or explicit human approval.

The AI SHALL NOT become the permanent owner of user information.

### EP-005 — Replaceable Components

Repository organisation SHALL support replacing models, messaging adapters, accounting tools, calendar providers and other integrations without restructuring unrelated LEA components.

---

## 5. Requirements

### RL-001 — Project Root

The canonical project root for the initial DietPi installation SHALL be:

```text
/opt/lea
```

Alternative development locations MAY be supported later, provided that LEA does not rely on hard-coded repository paths internally.

### RL-002 — Source Code

Python source code SHALL reside in:

```text
src/
```

The primary Python package SHALL reside in:

```text
src/lea/
```

### RL-003 — Documentation

Project documentation SHALL reside in:

```text
docs/
```

### RL-004 — Standards and Specifications

Engineering standards and product specifications SHALL reside in:

```text
docs/specifications/
```

### RL-005 — Architecture Decision Records

Architecture Decision Records SHALL reside in:

```text
docs/adr/
```

### RL-006 — Requests for Comments

Request for Comments documents SHALL reside in:

```text
docs/rfc/
```

### RL-007 — Documentation Assets

Images, diagrams and other documentation assets SHALL reside in:

```text
docs/assets/
```

### RL-008 — User Knowledge

Human-readable user knowledge SHALL reside in:

```text
knowledge/
```

Markdown SHALL be the canonical source of truth for LEA-managed knowledge unless a domain standard explicitly identifies another canonical tool.

Derived SQLite indexes, embeddings and search databases MAY be generated, but SHALL NOT replace the canonical source.

### RL-009 — AI Context Components

Reusable AI behaviour and context components SHALL reside in:

```text
context/
```

Examples include system rules, response conventions, confidence thresholds and tool-use policies.

### RL-010 — Prompt Templates

Complete or partially assembled prompt templates SHALL reside in:

```text
prompts/
```

`context/` SHALL contain reusable context components, while `prompts/` SHALL contain templates used to construct model requests.

### RL-011 — Plugins

Integration and adapter implementations SHALL reside in:

```text
plugins/
```

Plugins SHALL NOT invoke one another directly.

Cross-domain actions SHALL be coordinated by LEA's workflow or execution layer.

### RL-012 — Tests

Automated tests SHALL reside in:

```text
tests/
```

### RL-013 — Configuration

Version-controlled default and structural configuration SHALL reside in:

```text
config/
```

Secrets and machine-specific configuration SHALL NOT be committed to Git.

### RL-014 — Automation Scripts

Executable development, installation and maintenance scripts SHALL reside in:

```text
scripts/
```

Scripts SHALL act as executable entry points.

### RL-015 — Development Tools

Reusable developer utilities and helper implementations SHALL reside in:

```text
tools/
```

Scripts MAY call utilities in `tools/`.

Utilities in `tools/` SHALL NOT depend on shell scripts as their implementation layer.

### RL-016 — GitHub Automation

GitHub-specific workflows and templates SHALL reside in:

```text
.github/
```

### RL-017 — Root Documentation

The repository root SHALL contain:

```text
README.md
LICENSE
CONTRIBUTING.md
```

### RL-018 — Python Project Metadata

Once the Python project is initialised, its project and dependency metadata SHALL reside in:

```text
pyproject.toml
uv.lock
```

`uv.lock` SHALL be generated and maintained by `uv`.

### RL-019 — Environment Example

The repository root SHALL contain:

```text
.env.example
```

`.env.example` SHALL document supported environment variables without containing real secrets.

A machine-specific `.env` file SHALL NOT be committed to Git.

### RL-020 — Runtime Exclusion

The Git repository SHALL NOT treat the following as canonical repository content:

- downloaded model files;
- application logs;
- caches;
- temporary runtime state;
- generated indexes;
- local databases that can be regenerated;
- credentials or tokens.

Their deployed locations SHALL be defined by a future Deployment Layout Standard.

### RL-021 — Empty Directories

Where an empty directory is required to exist in Git, it SHALL contain an appropriate placeholder file such as:

```text
.gitkeep
```

The placeholder SHALL be removed when the directory contains tracked files.

### RL-022 — Language and Measurement Convention

Project documentation, user-facing text and code comments SHALL use UK English.

Metric and SI units SHALL be used wherever measurement units are required, except where an external protocol, accounting record or source datum requires another unit.

---

## 6. Canonical Repository Layout

```text
/opt/lea/
├── .github/
│   └── workflows/
├── config/
├── context/
├── docs/
│   ├── adr/
│   ├── assets/
│   ├── rfc/
│   └── specifications/
├── knowledge/
├── plugins/
├── prompts/
├── scripts/
├── src/
│   └── lea/
├── tests/
├── tools/
├── .env.example
├── .gitignore
├── CONTRIBUTING.md
├── LICENSE
├── README.md
├── pyproject.toml
└── uv.lock
```

`pyproject.toml` and `uv.lock` SHALL be created during Python project initialisation rather than manually populated by the repository bootstrap process unless the bootstrap standard explicitly requires otherwise.

---

## 7. Directory Classification

Ownership describes responsibility for creating and maintaining repository contents. It does not describe Linux filesystem ownership or permissions.

Lifecycle has the following meanings:

- **Static** — expected to change infrequently after establishment;
- **Dynamic** — expected to evolve during development or normal use;
- **Generated** — produced automatically and reproducible from another source.

| Directory | Purpose | Owner | Git | Lifecycle |
|---|---|---|---|---|
| `.github/` | GitHub workflows and templates | Developer | Yes | Dynamic |
| `config/` | Version-controlled defaults and structural configuration | Developer | Yes | Dynamic |
| `context/` | Reusable AI context and behaviour components | Developer | Yes | Dynamic |
| `docs/` | Project documentation and engineering records | Developer | Yes | Dynamic |
| `knowledge/` | Human-readable user knowledge | User | Yes, subject to repository policy | Dynamic |
| `plugins/` | External-tool adapters and integrations | Developer | Yes | Dynamic |
| `prompts/` | Prompt templates | Developer | Yes | Dynamic |
| `scripts/` | Executable automation entry points | Developer | Yes | Dynamic |
| `src/` | LEA application source code | Developer | Yes | Dynamic |
| `tests/` | Automated verification | Developer | Yes | Dynamic |
| `tools/` | Reusable development utilities | Developer | Yes | Dynamic |

---

## 8. Ownership Model

| Owner | Modification authority | Description |
|---|---|---|
| Developer | Contributors through Git | Source code, standards, tests and project configuration |
| User | The user or an explicitly authorised workflow | User knowledge and accepted records |
| Runtime | Deterministic application processes | Regenerable caches, indexes, logs and temporary state |
| AI proposal | No direct permanent authority | Proposed content or actions requiring validation or approval |

AI proposal is a transient state, not permanent ownership.

Once an AI proposal is accepted and applied, ownership transfers to the appropriate User, Developer or Runtime category.

---

## 9. Out of Scope

This standard does not define:

- the internal structure of `knowledge/`;
- CRM record formats;
- plugin interfaces;
- model storage locations;
- log storage locations;
- runtime database locations;
- backups;
- Linux service definitions;
- development branch conventions;
- commit message conventions;
- deployment permissions.

These concerns SHALL be defined in later standards, specifications or guides.

---

## 10. Success Criteria

This standard is satisfied when:

- every required repository directory has been created;
- required root-level placeholder files exist;
- empty tracked directories contain placeholders;
- runtime-only data is excluded from Git;
- repository contents match the canonical layout;
- the layout can be recreated deterministically;
- repository validation reports no missing required paths.

---

## 11. Future Considerations

Future revisions MAY define:

- a machine-readable repository layout configuration;
- repository validation and repair;
- migration between layout versions;
- support for development roots other than `/opt/lea`;
- generated documentation based on layout configuration;
- additional repository hosting providers.

A future Deployment Layout Standard SHALL define predictable Linux locations for:

- application state;
- logs;
- models;
- indexes;
- caches;
- secrets;
- backups.

---

## 12. References

- RFC 2119 — Key words for use in RFCs to Indicate Requirement Levels
- RFC 8174 — Ambiguity of Uppercase vs Lowercase in RFC 2119 Key Words
- GNU General Public License, version 3
