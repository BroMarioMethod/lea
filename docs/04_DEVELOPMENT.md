# Development

## Status

LEA is in early development.

This guide documents the current development workflow, quality checks and Git practices used by contributors.

## Development principles

Development should favour small, complete and verifiable changes.

The preferred sequence is:

1. Start from an up-to-date `main` branch.
2. Create a focused branch.
3. Define or confirm the relevant requirements.
4. Implement the smallest complete change.
5. Add or update tests.
6. Run the full quality gate.
7. Update affected documentation.
8. Commit atomically.
9. Push the branch.
10. Open a pull request.
11. Merge only after review and successful continuous integration.

## Prepare the repository

Enter the repository:

```bash
cd /opt/lea
```

Confirm the current branch and working state:

```bash
git branch --show-current
git status
```

Update `main` before starting new work:

```bash
git switch main
git pull --ff-only
```

`--ff-only` prevents Git from creating an unexpected merge commit while updating the local branch.

## Create a development branch

Create a focused branch:

```bash
git switch -c feature/example
```

Recommended prefixes include:

```text
feature/
fix/
docs/
refactor/
test/
chore/
```

A branch should address one cohesive concern.

## Synchronise the development environment

Use the committed lockfile:

```bash
uv sync --locked
```

This creates or updates the local `.venv/` environment without modifying the dependency resolution.

Use `uv run` to execute project commands:

```bash
uv run python
uv run lea
uv run pytest
```

Avoid relying on globally installed project dependencies.

## Source layout

Python source code resides in:

```text
src/lea/
```

Tests reside in:

```text
tests/
```

LEA uses a `src/` package layout. This helps ensure tests and scripts import the installed package rather than accidentally importing source files directly from the repository root.

## Quality gate

Run the complete local quality gate with:

```bash
scripts/check.sh
```

The script performs:

1. Ruff formatting verification.
2. Ruff linting.
3. Strict mypy type checking.
4. pytest automated tests.

The script stops at the first failing command.

The same script is used by GitHub Actions, keeping local and hosted checks aligned.

## Run checks individually

Formatting:

```bash
uv run ruff format --check .
```

Apply formatting:

```bash
uv run ruff format .
```

Linting:

```bash
uv run ruff check .
```

Apply safe automatic lint fixes where available:

```bash
uv run ruff check --fix .
```

Type checking:

```bash
uv run mypy
```

Tests:

```bash
uv run pytest
```

Use individual commands when diagnosing a failure. Use `scripts/check.sh` before committing or opening a pull request.

## Testing conventions

Tests should:

- be deterministic;
- avoid network access unless explicitly defined as integration tests;
- use temporary directories for filesystem operations;
- avoid modifying the active repository;
- clean up created resources;
- test observable behaviour;
- include type annotations where required by project configuration.

A simple test can be run with:

```bash
uv run pytest tests/test_package.py
```

A specific test function can be run with:

```bash
uv run pytest tests/test_package.py::test_package_is_importable
```

## Dependency management

Add a runtime dependency with:

```bash
uv add PACKAGE_NAME
```

Add a development dependency with:

```bash
uv add --dev PACKAGE_NAME
```

Remove a dependency with:

```bash
uv remove PACKAGE_NAME
```

After intentional dependency changes, commit both:

```text
pyproject.toml
uv.lock
```

Do not edit `uv.lock` manually.

Verify a reproducible environment with:

```bash
uv sync --locked
```

## Git staging

Inspect the working tree:

```bash
git status --short
```

Common status markers include:

```text
??  untracked
 M  modified but unstaged
M   staged modification
A   staged new file
D   staged deletion
AM  added and staged, then modified again
```

Stage only the files that belong to the current logical change:

```bash
git add path/to/file
```

Inspect staged content:

```bash
git diff --cached
```

Check for whitespace errors:

```bash
git diff --cached --check
```

## Commit messages

Use Conventional Commit-style messages:

```text
type: concise imperative description
```

Examples:

```text
feat: add workflow validation
fix: reject unsafe repository paths
docs: add development guide
test: cover bootstrap conflicts
refactor: separate execution policy
ci: update quality workflow
build: add development dependency
```

A commit should:

- represent one logical change;
- leave the repository in a valid state;
- use an imperative description;
- avoid unrelated edits.

## Push and open a pull request

Push a new branch and set its upstream:

```bash
git push -u origin feature/example
```

After the upstream is set, later updates can use:

```bash
git push
```

Create a pull request with GitHub CLI:

```bash
gh pr create \
    --base main \
    --head feature/example \
    --title "Describe the change" \
    --body "Summarise the purpose, implementation and verification."
```

Check pull-request status:

```bash
gh pr checks --watch
```

A pull request should not be merged while required checks are failing or pending.

## Merge workflow

LEA currently prefers merge commits so feature boundaries remain visible.

Merge through GitHub:

```bash
gh pr merge PR_NUMBER --merge --delete-branch
```

Then synchronise locally:

```bash
git switch main
git pull --ff-only
git fetch --prune
```

Delete the local feature branch after the merge:

```bash
git branch -d feature/example
```

## Tags and milestones

Annotated tags identify completed milestones:

```bash
git tag -a milestone-X.Y \
    -m "Milestone description"
```

Push a tag:

```bash
git push origin milestone-X.Y
```

Published tags should not be moved. If a correction is required after publication, create a new patch tag instead.

Example:

```text
milestone-0.3
milestone-0.3.1
```

## Local exclusions

Shared ignored files belong in:

```text
.gitignore
```

Personal exclusions that should not affect other contributors belong in:

```text
.git/info/exclude
```

For example:

```bash
printf '.roadmap\n' >> .git/info/exclude
```

## Secrets

Never commit:

- `.env`;
- access tokens;
- passwords;
- private keys;
- credentials;
- secret configuration;
- sensitive logs.

Before pushing, inspect staged changes carefully:

```bash
git diff --cached
```

If a secret is committed, changing the file afterwards is not sufficient because Git retains historical content. Revoke the secret immediately and rewrite history where necessary.

## Continuous integration

The workflow is defined in:

```text
.github/workflows/quality.yml
```

It runs on:

- pull requests;
- pushes to `main`.

Inspect workflow runs:

```bash
gh run list
```

Watch a running workflow:

```bash
gh run watch RUN_ID --compact --exit-status
```

Inspect failed logs:

```bash
gh run view RUN_ID --log-failed
```

Local checks passing does not guarantee the hosted workflow configuration is valid. Both local and GitHub-hosted verification are required for CI changes.

## Definition of done

A change is complete when:

- requirements are satisfied;
- implementation is complete;
- tests cover the intended behaviour;
- `scripts/check.sh` passes;
- documentation is updated;
- commits are atomic;
- the pull request is reviewed;
- continuous integration passes;
- the branch is merged;
- any required milestone tag is created.
