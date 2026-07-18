# Contributing to LEA

Thank you for considering a contribution to LEA.

LEA is a local-first, specification-driven personal operating system for knowledge work. Contributions should preserve its transparency, maintainability, auditability and human-controlled design.

The project is currently in early development. Interfaces and internal structures may change as the architecture matures.

## Code of conduct

Contributors SHALL communicate respectfully and discuss technical disagreements in good faith.

Criticism should address ideas, designs and implementations rather than individuals.

A dedicated Code of Conduct may be introduced in a future milestone.

## Language and measurement conventions

Project documentation, code comments, commit messages and user-facing text SHALL use UK English.

Metric and SI units SHALL be used where measurements are required, except where an external protocol or source datum requires another unit.

Examples:

```text
behaviour, not behavior
licence, not license, when used as a noun
organisation, not organization
metre, not meter
kilometre, not kilometer
```

Programming-language keywords, external API field names and quoted source text SHALL remain unchanged.

## Development requirements

The current development environment requires:

- Linux;
- Python 3.13 or later;
- `uv`;
- Git.

Clone and enter the repository:

```bash
git clone https://github.com/BroMarioMethod/lea.git
cd lea
```

Synchronise the locked development environment:

```bash
uv sync --locked
```

Run the complete quality gate:

```bash
scripts/check.sh
```

## Development process

LEA follows this development sequence:

1. Define or update the relevant specification.
2. Discuss unresolved design concerns.
3. Implement the smallest complete change.
4. Add or update tests.
5. Run all quality checks.
6. Update affected documentation.
7. Commit the work atomically.
8. Open a pull request.
9. Merge only after review and successful continuous integration.

Minor corrections MAY omit a new formal specification when existing requirements already define the intended behaviour.

## Branch conventions

Changes SHALL be developed on focused branches created from an up-to-date `main` branch.

Examples:

```text
feature/workflow-engine
feature/telegram-adapter
fix/setup-uv-action
docs/development-guide
refactor/plugin-loader
```

Recommended branch prefixes are:

| Prefix | Purpose |
|---|---|
| `feature/` | New functionality |
| `fix/` | Defect corrections |
| `docs/` | Documentation-only changes |
| `refactor/` | Internal restructuring without intended behaviour changes |
| `test/` | Test additions or corrections |
| `chore/` | Maintenance and repository housekeeping |

Create a branch with:

```bash
git switch -c feature/example
```

Branches SHOULD contain one cohesive change.

## Commit conventions

Commits SHALL be atomic: each commit should represent one logical change and leave the repository in a valid state.

LEA uses Conventional Commit-style messages:

```text
type: concise imperative description
```

Examples:

```text
feat: implement repository bootstrap
fix: pin setup-uv action version
docs: add project overview
test: cover repository path conflicts
refactor: separate workflow validation
ci: add automated quality checks
build: establish Python development foundation
legal: add GPL-3.0-only licence
```

Common commit types include:

| Type | Purpose |
|---|---|
| `feat` | New user-facing or system functionality |
| `fix` | Defect correction |
| `docs` | Documentation |
| `test` | Tests |
| `refactor` | Internal restructuring |
| `ci` | Continuous-integration changes |
| `build` | Packaging, dependency or build-system changes |
| `config` | Project configuration |
| `chore` | Maintenance |
| `legal` | Licensing or legal documents |

The description SHOULD:

- use the imperative mood;
- begin with a lower-case letter;
- avoid a trailing full stop;
- describe what the commit changes.

## Specifications and architecture decisions

Engineering standards and feature specifications reside in:

```text
docs/specifications/
```

Architecture Decision Records reside in:

```text
docs/adr/
```

Requests for Comments reside in:

```text
docs/rfc/
```

Implementations SHALL conform to accepted standards.

When an implementation requires a lasting architectural decision that is not already documented, the contributor SHOULD create or update the appropriate engineering document.

## Source code

Python source code resides in:

```text
src/lea/
```

Tests reside in:

```text
tests/
```

LEA uses a `src/` package layout. Code SHOULD be executed through the project environment:

```bash
uv run python
uv run lea
```

Avoid relying on globally installed Python packages.

## Python standards

Python code SHALL:

- support the Python version declared in `pyproject.toml`;
- include type annotations for public and internal functions;
- pass strict mypy checks;
- follow Ruff formatting and linting rules;
- avoid hidden global state where practical;
- keep deterministic execution separate from AI-generated proposals;
- use clear names rather than unnecessary abbreviations;
- include docstrings where intent is not self-evident.

## Tests

Every behavioural change SHOULD include automated tests.

Tests SHALL:

- be deterministic;
- avoid network access unless explicitly marked as an integration test;
- avoid modifying the active repository;
- use temporary directories for filesystem tests;
- clean up created resources;
- verify observable behaviour rather than implementation details where practical.

Run tests directly with:

```bash
uv run pytest
```

Run the complete project quality gate with:

```bash
scripts/check.sh
```

## Quality checks

Before committing or opening a pull request, run:

```bash
scripts/check.sh
```

This executes:

```text
Ruff formatting verification
Ruff linting
mypy strict type checking
pytest automated tests
```

All checks SHALL pass.

GitHub Actions runs the same script for pull requests and pushes to `main`.

## Pull requests

Pull requests SHOULD:

- address one cohesive concern;
- explain the purpose of the change;
- identify relevant specifications or issues;
- summarise implementation decisions;
- describe how the change was tested;
- disclose known limitations or follow-up work;
- contain no unrelated formatting or refactoring changes.

A pull request SHALL NOT be merged while required checks are failing or pending.

Merge commits are currently preferred so feature boundaries remain visible in project history.

## Generated and local files

Contributors SHALL NOT commit:

- `.env`;
- credentials or tokens;
- `.venv/`;
- Python bytecode;
- test and analysis caches;
- downloaded model files;
- generated indexes;
- application logs;
- machine-specific runtime state.

The shared exclusions are defined in:

```text
.gitignore
```

Personal exclusions that do not apply to every contributor SHOULD be added to:

```text
.git/info/exclude
```

## Security

Never include secrets in commits, issues, logs or pull requests.

When a security concern could expose user data or system access, do not publish full exploit details in a public issue. A formal private vulnerability-reporting process will be introduced before production releases.

## Licensing

By contributing to LEA, contributors agree that their contributions will be distributed under the GNU General Public License version 3 only.

See:

```text
LICENSE
```

## Current project maturity

LEA is not yet production-ready.

Contributors should avoid presenting planned capabilities as implemented functionality and should clearly distinguish:

- completed behaviour;
- experimental behaviour;
- planned behaviour;
- future considerations.
