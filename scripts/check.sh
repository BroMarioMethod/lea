#!/usr/bin/env bash

set -euo pipefail

printf 'Running Ruff formatting check...\n'
uv run ruff format --check .

printf '\nRunning Ruff linting...\n'
uv run ruff check .

printf '\nRunning mypy...\n'
uv run mypy

printf '\nRunning pytest...\n'
uv run pytest

printf '\nAll quality checks passed.\n'
