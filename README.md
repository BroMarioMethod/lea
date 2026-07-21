# LEA

**LEA** is a local-first, specification-driven personal operating system for knowledge work.

Its purpose is to orchestrate deterministic tools, structured knowledge and AI reasoning into a cohesive, transparent and auditable workflow.

LEA is designed to help entrepreneurs and knowledge workers spend less time on administration and more time on purposeful work.

## Project status

LEA is in early development.

The repository foundation includes:

- an installable Python package;
- dependency management with `uv`;
- Ruff formatting and linting;
- strict mypy type checking;
- pytest automation;
- a shared local quality-check script;
- GitHub Actions continuous integration.

The action workflow includes immutable proposals, validation, risk and confirmation policy, deterministic state transitions, explicit approval decisions, approved-only execution, append-only audit persistence, integrity hash chaining and deterministic orchestration.

The runtime foundation includes:

- immutable system, development and test layouts;
- strict UTF-8 TOML loading from explicit absolute paths;
- rejection of unknown and missing fields;
- deterministic templates and serialisation;
- safe configuration initialisation without overwrite;
- runtime-directory bootstrap with dry-run support;
- read-only health checks;
- UTC-to-IANA-timezone presentation;
- coordinated setup and verification;
- read-only inspection;
- deterministic reports;
- `lea runtime` administration commands;
- preserved dispatch through both `lea` and `python -m lea`.

Approval permits workflow progression only. It does not execute an action.

Domain-specific handlers, plugin discovery, authenticated audit integrity, authentication and user interfaces remain under development.

## Design principles

LEA is developed around these principles:

- **Local-first** — core functionality should operate without Internet access where practical.
- **Specification-driven** — behaviour is defined before implementation.
- **Human-controlled** — AI proposes actions; deterministic code validates and applies them.
- **Auditable** — important decisions and state changes should be traceable.
- **Replaceable components** — models, tools and communication adapters should be independently replaceable.
- **Single canonical source** — persistent information should have one authoritative source.
- **Configuration as data** — configuration should be declarative where practical.
- **Repository and runtime separation** — source-controlled files remain separate from deployed state.
- **UK English** — documentation, comments and user-facing text use UK English.
- **Metric and SI units** — metric and SI units are used where measurements are required.

## Intended capabilities

The long-term vision includes:

- workflow orchestration;
- local AI model integration;
- task and project management;
- calendar coordination;
- accounting integration;
- customer relationship management;
- quotations, invoices and purchase orders;
- accounts receivable and payable workflows;
- structured personal and organisational knowledge;
- meeting summaries and reports;
- progressive automation based on earned confidence;
- multiple communication adapters.

These capabilities are planned and are not yet production-ready.

## Repository layout

```text
config/          Version-controlled configuration
context/         Reusable AI context components
docs/            Standards and project documentation
knowledge/       Human-readable canonical knowledge
plugins/         External-tool adapters
prompts/         Prompt templates
scripts/         Executable automation
src/lea/         Python package source
tests/           Automated tests
tools/           Reusable development utilities
```

The canonical repository structure is defined in:

```text
docs/specifications/LEA-STD-0001_REPOSITORY_LAYOUT.md
```

## Requirements

The current development environment requires:

- Linux;
- Python 3.13 or later;
- `uv`;
- Git.

The initial target platform is a Raspberry Pi 4B running 64-bit DietPi.

## Development setup

```bash
git clone https://github.com/BroMarioMethod/lea.git
cd lea
uv sync --locked
```

Run the existing application entry point:

```bash
uv run lea
```

Inspect runtime commands:

```bash
uv run lea runtime --help
```

The package route is equivalent:

```bash
uv run python -m lea runtime --help
```

## Runtime administration

Available commands:

```text
inspect
health
initialise
bootstrap
setup
verify
```

Example dry run:

```bash
mkdir -p /tmp/lea-test/config

uv run lea runtime verify \
    --profile test \
    --root /tmp/lea-test \
    --display-timezone Africa/Gaborone \
    --dry-run
```

Detailed guidance:

```text
docs/08_RUNTIME_CONFIGURATION.md
```

## Quality checks

Run:

```bash
scripts/check.sh
```

This performs Ruff formatting verification, Ruff linting, strict mypy checking and pytest tests. GitHub Actions runs the same script.

## Repository bootstrap

```bash
scripts/bootstrap_repository.sh /path/to/repository
```

The process reads:

```text
config/repository_layout.toml
```

It creates missing required paths while preserving existing valid content.

## Documentation

Engineering standards and behavioural specifications are stored under:

```text
docs/specifications/
```

Current accepted or completed standards and specifications include:

- `LEA-STD-0001` — Repository Layout Standard
- `LEA-STD-0002` — Repository Bootstrap Standard
- `LEA-SPEC-0001` — Core Application Skeleton Specification
- `LEA-SPEC-0002` — Action Proposal Contract Specification
- `LEA-SPEC-0003` — Action State Transition Specification
- `LEA-SPEC-0004` — Confirmation and Approval Policy Specification
- `LEA-SPEC-0005` — Action Execution Boundary Specification
- `LEA-SPEC-0006` — Action Audit Trail Specification
- `LEA-SPEC-0007` — Audit Integrity and Verification Specification
- `LEA-SPEC-0008` — Action Orchestration Service Specification
- `LEA-SPEC-0009` — Runtime Layout and Configuration Specification

Operational guides:

```text
docs/05_AUDIT_STORAGE.md
docs/06_AUDIT_INTEGRITY.md
docs/07_ACTION_ORCHESTRATION.md
docs/08_RUNTIME_CONFIGURATION.md
```

The audit integrity implementation uses an unauthenticated SHA-256 hash chain. It detects many unrecomputed changes but does not protect against complete file replacement or valid tail truncation.

The orchestration service does not provide transactional atomicity across proposal values, audit persistence and external side effects. A handler may complete an irreversible side effect before a later audit append fails.

## Contributing

Until `CONTRIBUTING.md` is populated:

- create a focused branch for each change;
- keep commits atomic;
- use Conventional Commit messages;
- run `scripts/check.sh` before opening a pull request;
- avoid committing secrets or runtime-generated files;
- use UK English in documentation and comments.

## Licence

LEA is licensed under the GNU Affero General Public License version 3 only.

See:

```text
LICENSE
```

## Development milestones

Completed milestones are recorded as annotated Git tags:

```text
milestone-X.Y
milestone-X.Y.Z
```

View them with:

```bash
git tag
```

