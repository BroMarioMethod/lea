"""Tests for release-candidate acceptance asset validation."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, cast

_VALIDATOR_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "validate_release_candidate_acceptance.py"
)

AcceptanceValidator = Callable[..., tuple[Any, ...]]


def _load_validator_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "lea_validate_release_candidate_acceptance",
        _VALIDATOR_PATH,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            "Release-candidate acceptance validator could not be loaded."
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_validator = _load_validator_module()
validate_release_candidate_acceptance = cast(
    AcceptanceValidator,
    _validator.validate_release_candidate_acceptance,
)


def _write(
    path: Path,
    contents: str,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    return path.resolve()


def _valid_assets(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, Path]:
    cli = _write(
        tmp_path / "cli.py",
        """
prog="lea accept-release-candidate"
"--telegram"
"--no-telegram"
EXIT_ACCEPTANCE_FAILED = 1
EXIT_USAGE_ERROR = 2
EXIT_INTERNAL_ERROR = 70
run_release_candidate_acceptance_harness
""",
    )
    harness = _write(
        tmp_path / "harness.py",
        """
run_release_candidate_acceptance_harness
create_release_candidate_acceptance_record
write_release_candidate_acceptance_record
ReleaseCandidateAcceptanceHarnessResult
""",
    )
    record = _write(
        tmp_path / "record.py",
        """
"lea-release-candidate-acceptance"
schema_version=1
sort_keys=True
os.replace
mode: int = 0o640
""",
    )
    main = _write(
        tmp_path / "main.py",
        """
"accept-release-candidate"
execute_release_candidate_acceptance_cli
release_candidate_acceptance_cli_runner
""",
    )
    documentation = _write(
        tmp_path / "acceptance.md",
        """
uv run lea accept-release-candidate
--telegram
--no-telegram
/var/lib/lea/acceptance/release-candidate.json
Exit code
Telegram bot tokens
clean-room installation
uv run python scripts/validate_release_candidate_acceptance.py
""",
    )

    return cli, harness, record, main, documentation


def _valid_calendar_assets(
    tmp_path: Path,
) -> tuple[Path, Path, Path]:
    requirements_input = _write(
        tmp_path / "third_party/calendar/requirements.in",
        "khal==0.11.4\nvdirsyncer==0.19.3\n",
    )
    requirements_lock = _write(
        (tmp_path / "third_party/calendar/requirements-linux-aarch64-py313.txt"),
        r"""# Generated lock
--only-binary :all:

khal==0.11.4 \
    --hash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
vdirsyncer==0.19.3 \
    --hash=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
""",
    )
    digest = hashlib.sha256(requirements_lock.read_bytes()).hexdigest()
    sha256sums = _write(
        tmp_path / "third_party/calendar/SHA256SUMS",
        f"{digest}  {requirements_lock.name}\n",
    )
    return requirements_input, requirements_lock, sha256sums


def _validate_valid_assets(
    tmp_path: Path,
) -> tuple[Any, ...]:
    cli, harness, record, main, documentation = _valid_assets(tmp_path)
    requirements_input, requirements_lock, sha256sums = _valid_calendar_assets(tmp_path)

    return validate_release_candidate_acceptance(
        cli_path=cli,
        harness_path=harness,
        record_path=record,
        main_path=main,
        documentation_path=documentation,
        calendar_requirements_input_path=requirements_input,
        calendar_requirements_lock_path=requirements_lock,
        calendar_sha256sums_path=sha256sums,
        repository_root=tmp_path.resolve(),
    )


def test_valid_assets_pass(
    tmp_path: Path,
) -> None:
    issues = _validate_valid_assets(tmp_path)

    assert issues == ()


def test_calendar_lock_checksum_mismatch_is_reported(
    tmp_path: Path,
) -> None:
    cli, harness, record, main, documentation = _valid_assets(tmp_path)
    requirements_input, requirements_lock, sha256sums = _valid_calendar_assets(tmp_path)
    sha256sums.write_text(
        f"{'0' * 64}  {requirements_lock.name}\n",
        encoding="utf-8",
    )

    issues = validate_release_candidate_acceptance(
        cli_path=cli,
        harness_path=harness,
        record_path=record,
        main_path=main,
        documentation_path=documentation,
        calendar_requirements_input_path=requirements_input,
        calendar_requirements_lock_path=requirements_lock,
        calendar_sha256sums_path=sha256sums,
        repository_root=tmp_path.resolve(),
    )

    assert any(issue.code == "calendar_lock_checksum_mismatch" for issue in issues)


def test_unpinned_calendar_requirement_is_reported(
    tmp_path: Path,
) -> None:
    cli, harness, record, main, documentation = _valid_assets(tmp_path)
    requirements_input, requirements_lock, sha256sums = _valid_calendar_assets(tmp_path)
    requirements_lock.write_text(
        requirements_lock.read_text(encoding="utf-8") + "unexpected-package>=1\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(requirements_lock.read_bytes()).hexdigest()
    sha256sums.write_text(
        f"{digest}  {requirements_lock.name}\n",
        encoding="utf-8",
    )

    issues = validate_release_candidate_acceptance(
        cli_path=cli,
        harness_path=harness,
        record_path=record,
        main_path=main,
        documentation_path=documentation,
        calendar_requirements_input_path=requirements_input,
        calendar_requirements_lock_path=requirements_lock,
        calendar_sha256sums_path=sha256sums,
        repository_root=tmp_path.resolve(),
    )

    assert any(issue.code == "calendar_lock_unpinned_requirement" for issue in issues)


def test_missing_cli_contract_is_reported(
    tmp_path: Path,
) -> None:
    cli, harness, record, main, documentation = _valid_assets(tmp_path)
    cli.write_text(
        cli.read_text(encoding="utf-8").replace(
            '"--no-telegram"\n',
            "",
        ),
        encoding="utf-8",
    )

    issues = validate_release_candidate_acceptance(
        cli_path=cli,
        harness_path=harness,
        record_path=record,
        main_path=main,
        documentation_path=documentation,
        repository_root=tmp_path.resolve(),
    )

    assert any(issue.code == "acceptance_cli_contract_missing" for issue in issues)


def test_sensitive_record_field_is_reported(
    tmp_path: Path,
) -> None:
    cli, harness, record, main, documentation = _valid_assets(tmp_path)
    record.write_text(
        record.read_text(encoding="utf-8") + "\nconversation_id\n",
        encoding="utf-8",
    )

    issues = validate_release_candidate_acceptance(
        cli_path=cli,
        harness_path=harness,
        record_path=record,
        main_path=main,
        documentation_path=documentation,
        repository_root=tmp_path.resolve(),
    )

    assert any(
        issue.code == "acceptance_record_sensitive_field_detected" for issue in issues
    )


def test_missing_documentation_is_reported(
    tmp_path: Path,
) -> None:
    cli, harness, record, main, documentation = _valid_assets(tmp_path)
    documentation.unlink()

    issues = validate_release_candidate_acceptance(
        cli_path=cli,
        harness_path=harness,
        record_path=record,
        main_path=main,
        documentation_path=documentation,
        repository_root=tmp_path.resolve(),
    )

    assert any(issue.code == "acceptance_asset_missing" for issue in issues)
