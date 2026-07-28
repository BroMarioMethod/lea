#!/usr/bin/env bash

set -euo pipefail

printf 'Validating release-candidate wrapper syntax...\n'
bash -n install.sh uninstall.sh

printf '\nRunning Ruff formatting check...\n'
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
