# Milestone 2.7.1 Release Checklist

| Field | Value |
|---|---|
| Milestone | `2.7.1` |
| Package version | `0.2.1` |
| Base release | `milestone-2.7` / LEA `0.2.0` |
| Release type | Corrective patch release |
| Proposed tag | `milestone-2.7.1` |

## Release scope

This patch release corrects and hardens the Telegram task proposal lifecycle.

It includes:

- proposal-backed Telegram task creation, modification, completion and deletion;
- mandatory confirmation for interactive task mutations;
- separation of approval from deterministic execution;
- risk-specific execution capabilities;
- approved-proposal Execute and Cancel controls;
- exact Taskwarrior lookup across task statuses;
- durable Telegram update checkpointing before best-effort response delivery;
- non-fatal handling of post-checkpoint send, edit and callback-answer failures;
- role-scoped actors in user-facing channel responses while preserving accountable
  local audit identity;
- removal of deferred commands from the active Telegram command surface.

## Validation evidence

The following validation completed successfully before release preparation:

- the complete repository quality gate passed on merged `main`;
- the deployment-focused test-card suite passed with 97 tests;
- the live create, modify, complete and delete lifecycle passed;
- no provider mutation occurred before explicit execution;
- rejected and cancelled proposals did not mutate Taskwarrior;
- stale and duplicate requests failed safely;
- the Telegram worker remained active with zero systemd restarts;
- a live Telegram send failure was recorded as a non-fatal warning without
  replaying the committed update.

## Reliability boundary

Telegram response delivery remains best-effort after the update checkpoint has
been persisted.

A delivery failure may therefore cause a response not to reach Telegram, but it
must not replay an already committed application action or terminate the worker.
A durable outbound retry mechanism is outside this patch release.

## Release gate

- [x] `pyproject.toml` declares package version `0.2.1`.
- [x] `uv.lock` records package version `0.2.1`.
- [x] package-version tests expect `0.2.1`.
- [x] Ruff formatting and linting pass.
- [x] mypy passes.
- [x] the complete pytest suite passes.
- [x] the repository quality gate passes.
- [x] the release branch is ready to merge into `main`.
- [x] annotated tag `milestone-2.7.1` is ready to be created from merged `main`.
