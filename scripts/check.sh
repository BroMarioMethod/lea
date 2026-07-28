#!/usr/bin/env bash

set -euo pipefail

printf 'Running Ruff formatting check...\n'
uv run ruff format --check .

printf '\nRunning Ruff linting...\n'
uv run ruff check .

printf '\nRunning mypy...\n'
uv run mypy

printf '\nValidating Telegram deployment assets...\n'
uv run python scripts/validate_telegram_deployment.py

printf '\nValidating release-candidate acceptance assets...\n'
uv run python scripts/validate_release_candidate_acceptance.py

printf '\nRunning pytest...\n'
uv run pytest

printf '\nAll quality checks passed.\n'
