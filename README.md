# LEA

**LEA** is a local-first, specification-driven personal operating system for knowledge work.

Its purpose is to orchestrate deterministic tools, structured knowledge and AI reasoning into a cohesive, transparent and auditable workflow.

LEA is designed to help entrepreneurs and knowledge workers spend less time on administration and more time on purposeful work.

## Project status

LEA is in early development.

The current repository foundation includes:

- a deterministic repository bootstrap process;
- an installable Python package;
- dependency management with `uv`;
- formatting and linting with Ruff;
- strict type checking with mypy;
- automated testing with pytest;
- a shared local quality-check script;
- GitHub Actions continuous integration.

The current core action workflow includes:

- immutable action proposals;
- deterministic proposal validation;
- structured validation issues;
- explicit risk levels and confirmation policies;
- deterministic proposal-state transitions;
- terminal-state and invalid-transition protection;
- confirmation-policy evaluation;
- mandatory human confirmation for high- and critical-risk proposals;
- immutable approval, rejection and cancellation records;
- deterministic application of confirmation decisions;
- UTC-aware audit timestamps;
- explicit deterministic action-handler registration;
- exact action-name dispatch without fuzzy matching or plugin discovery;
- an approved-only action-execution boundary;
- immutable `approved → executing → succeeded` workflow progression;
- structured failed execution with `executing → failed`;
- safe containment of handler exceptions and invalid output;
- deterministic JSON-compatible serialisation;
- immutable audit-event records with canonical event types;
- deterministic audit-event factories for existing workflow records;
- append-only UTF-8 JSONL audit persistence;
- ordered audit retrieval and exact proposal filtering;
- structured malformed-record errors with physical line numbers;
- explicit runtime paths, optional parent creation and optional `fsync`;
- immutable SHA-256 integrity envelopes;
- deterministic previous-event hash chaining;
- read-only integrity verification in physical file order;
- detection of edited payloads, broken links, inserted records and reordered records;
- explicit legacy and mixed-format handling;
- refusal to extend invalid integrity chains.

Approval permits workflow progression only. It does not execute an action.

Domain-specific handlers, plugin discovery, authenticated audit integrity,
authentication and user interfaces remain under development.

## Design principles

LEA is being developed around the following principles:

- **Local-first** — core functionality should operate without Internet access where practical.
- **Specification-driven** — behaviour is defined before implementation.
- **Human-controlled** — AI proposes actions; deterministic code validates and applies them.
- **Auditable** — important decisions and state changes should be traceable.
- **Replaceable components** — models, tools and communication adapters should be independently replaceable.
- **Single canonical source** — persistent information should have one authoritative source.
- **Configuration as data** — configuration should be represented declaratively where practical.
- **Repository and runtime separation** — source-controlled project files remain separate from deployed state.
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
- quotations, invoices, purchase orders and related business documents;
- accounts receivable and accounts payable workflows;
- structured personal and organisational knowledge;
- meeting summaries and reports;
- progressive automation based on earned confidence;
- multiple communication adapters.

These capabilities are planned and should not yet be considered production-ready.

## Repository layout

Key repository locations include:

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

Development and continuous-integration checks also run on other compatible Linux environments.

## Development setup

Clone the repository and enter it:

```bash
git clone https://github.com/BroMarioMethod/lea.git
cd lea
```

Create and synchronise the development environment:

```bash
uv sync --locked
```

Run LEA’s current command-line entry point:

```bash
uv run lea
```

At present, this command only confirms that the package is installed correctly.

## Quality checks

Run the complete local quality gate:

```bash
scripts/check.sh
```

This performs:

```text
Ruff formatting verification
Ruff linting
mypy strict type checking
pytest automated tests
```

The same script is executed by GitHub Actions.

## Repository bootstrap

The repository structure can be created or repaired with:

```bash
scripts/bootstrap_repository.sh /path/to/repository
```

The bootstrap process reads:

```text
config/repository_layout.toml
```

It creates missing required paths while preserving existing valid content.

## Documentation

Engineering standards and behavioural specifications are stored under:

```text
docs/specifications/
```

Current accepted standards and specifications include:

- `LEA-STD-0001` — Repository Layout Standard
- `LEA-STD-0002` — Repository Bootstrap Standard
- `LEA-SPEC-0001` — Core Application Skeleton Specification
- `LEA-SPEC-0002` — Action Proposal Contract Specification
- `LEA-SPEC-0003` — Action State Transition Specification
- `LEA-SPEC-0004` — Confirmation and Approval Policy Specification
- `LEA-SPEC-0005` — Action Execution Boundary Specification
- `LEA-SPEC-0006` — Action Audit Trail Specification
- `LEA-SPEC-0007` — Audit Integrity and Verification Specification

Behaviour is specified before implementation and updated when automated test
coverage confirms completion.

Operational guidance for audit storage is available in:

```text
docs/05_AUDIT_STORAGE.md
```

Operational guidance for integrity-enabled audit verification is available in:

```text
docs/06_AUDIT_INTEGRITY.md
```

The current audit integrity implementation uses an unauthenticated SHA-256 hash
chain. It detects many unrecomputed changes but does not prevent or prove
against complete file replacement or valid tail truncation.

## Contributing

Contribution guidelines are being developed in:

```text
CONTRIBUTING.md
```

Until that document is populated, contributors should:

- create a focused branch for each change;
- keep commits atomic;
- use Conventional Commit messages;
- run `scripts/check.sh` before opening a pull request;
- avoid committing secrets or runtime-generated files;
- use UK English in documentation and comments.

## Licence

LEA is licensed under the GNU General Public License version 3 only.

See:

```text
LICENSE
```

## Development milestones

Completed milestones are recorded as annotated Git tags using the following
naming convention:

```text
milestone-X.Y
milestone-X.Y.Z
```

Milestone tags identify stable points in the project history. Current
development work is represented by active branches and pull requests.

View the available milestones locally with:

```bash
git tag
```

