#!/usr/bin/env python3
"""Validate committed release-candidate acceptance assets safely."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

CLI_PATH = REPOSITORY_ROOT / "src/lea/release_candidate_acceptance_cli.py"
HARNESS_PATH = (
    REPOSITORY_ROOT / "src/lea/installers/release_candidate/acceptance_harness.py"
)
RECORD_PATH = (
    REPOSITORY_ROOT / "src/lea/installers/release_candidate/acceptance_record.py"
)
MAIN_PATH = REPOSITORY_ROOT / "src/lea/main.py"
DOCUMENTATION_PATH = (
    REPOSITORY_ROOT / "docs/development/RELEASE_CANDIDATE_ACCEPTANCE.md"
)


@dataclass(frozen=True, slots=True)
class AcceptanceValidationIssue:
    """One deterministic acceptance-asset validation issue."""

    code: str
    message: str
    path: Path

    def __post_init__(self) -> None:
        """Validate one issue."""
        if not self.code.strip():
            raise ValueError("Validation issue code must be non-empty.")
        if not self.message.strip():
            raise ValueError("Validation issue message must be non-empty.")
        if not self.path.is_absolute():
            raise ValueError("Validation issue path must be absolute.")


def validate_release_candidate_acceptance(
    *,
    cli_path: Path = CLI_PATH,
    harness_path: Path = HARNESS_PATH,
    record_path: Path = RECORD_PATH,
    main_path: Path = MAIN_PATH,
    documentation_path: Path = DOCUMENTATION_PATH,
    repository_root: Path = REPOSITORY_ROOT,
) -> tuple[AcceptanceValidationIssue, ...]:
    """Validate acceptance assets without running the acceptance harness."""
    issues: list[AcceptanceValidationIssue] = []

    cli = _read(cli_path, issues)
    harness = _read(harness_path, issues)
    record = _read(record_path, issues)
    main = _read(main_path, issues)
    documentation = _read(documentation_path, issues)

    if cli is not None:
        _require_parts(
            cli,
            path=cli_path,
            code="acceptance_cli_contract_missing",
            required=(
                'prog="lea accept-release-candidate"',
                '"--telegram"',
                '"--no-telegram"',
                "EXIT_ACCEPTANCE_FAILED = 1",
                "EXIT_USAGE_ERROR = 2",
                "EXIT_INTERNAL_ERROR = 70",
                "run_release_candidate_acceptance_harness",
            ),
            issues=issues,
        )

    if harness is not None:
        _require_parts(
            harness,
            path=harness_path,
            code="acceptance_harness_contract_missing",
            required=(
                "run_release_candidate_acceptance_harness",
                "create_release_candidate_acceptance_record",
                "write_release_candidate_acceptance_record",
                "ReleaseCandidateAcceptanceHarnessResult",
            ),
            issues=issues,
        )

    if record is not None:
        _require_parts(
            record,
            path=record_path,
            code="acceptance_record_contract_missing",
            required=(
                '"lea-release-candidate-acceptance"',
                "schema_version=1",
                "sort_keys=True",
                "os.replace",
                "mode: int = 0o640",
            ),
            issues=issues,
        )

        for forbidden in (
            "telegram_token",
            "authorised_user_id",
            "conversation_id",
            "environment_variables",
            "raw_exception",
        ):
            if forbidden in record:
                issues.append(
                    AcceptanceValidationIssue(
                        code="acceptance_record_sensitive_field_detected",
                        message=(
                            "The acceptance-record implementation contains a "
                            f"forbidden sensitive-field name: {forbidden}"
                        ),
                        path=record_path,
                    )
                )

    if main is not None:
        _require_parts(
            main,
            path=main_path,
            code="acceptance_dispatch_missing",
            required=(
                '"accept-release-candidate"',
                "execute_release_candidate_acceptance_cli",
                "release_candidate_acceptance_cli_runner",
            ),
            issues=issues,
        )

    if documentation is not None:
        _require_parts(
            documentation,
            path=documentation_path,
            code="acceptance_documentation_incomplete",
            required=(
                "uv run lea accept-release-candidate",
                "--telegram",
                "--no-telegram",
                "/var/lib/lea/acceptance/release-candidate.json",
                "Exit code",
                "Telegram bot tokens",
                "clean-room installation",
                "uv run python scripts/validate_release_candidate_acceptance.py",
            ),
            issues=issues,
        )

    _validate_help(
        repository_root,
        issues=issues,
    )

    return tuple(issues)


def main() -> int:
    """Validate committed release-candidate acceptance assets."""
    issues = validate_release_candidate_acceptance()

    if issues:
        print(
            "Release-candidate acceptance validation: FAILED",
            file=sys.stderr,
        )
        for issue in issues:
            try:
                displayed_path = issue.path.relative_to(REPOSITORY_ROOT)
            except ValueError:
                displayed_path = issue.path

            print(
                f"{issue.code}: {issue.message} | path={displayed_path}",
                file=sys.stderr,
            )
        return 1

    print("Release-candidate acceptance validation: PASSED")
    return 0


def _validate_help(
    repository_root: Path,
    *,
    issues: list[AcceptanceValidationIssue],
) -> None:
    """Validate public help without executing installed-system acceptance."""
    command = (
        "uv",
        "run",
        "lea",
        "accept-release-candidate",
        "--help",
    )

    try:
        result = subprocess.run(
            command,
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        issues.append(
            AcceptanceValidationIssue(
                code="acceptance_help_execution_failed",
                message="The acceptance command help could not be executed.",
                path=repository_root,
            )
        )
        return

    if result.returncode != 0:
        issues.append(
            AcceptanceValidationIssue(
                code="acceptance_help_failed",
                message="The acceptance command help returned a failure.",
                path=repository_root,
            )
        )
        return

    for required in (
        "usage: lea accept-release-candidate",
        "--telegram",
        "--no-telegram",
        "--configuration-root",
        "--state-root",
        "--record-file",
    ):
        if required not in result.stdout:
            issues.append(
                AcceptanceValidationIssue(
                    code="acceptance_help_content_missing",
                    message=(
                        "The acceptance command help is missing required "
                        f"content: {required}"
                    ),
                    path=repository_root,
                )
            )


def _require_parts(
    contents: str,
    *,
    path: Path,
    code: str,
    required: tuple[str, ...],
    issues: list[AcceptanceValidationIssue],
) -> None:
    """Require exact stable contract fragments."""
    for part in required:
        if part not in contents:
            issues.append(
                AcceptanceValidationIssue(
                    code=code,
                    message=f"Required acceptance content is missing: {part}",
                    path=path,
                )
            )


def _read(
    path: Path,
    issues: list[AcceptanceValidationIssue],
) -> str | None:
    """Read one required UTF-8 acceptance asset."""
    if not path.is_absolute():
        raise ValueError("Acceptance validation paths must be absolute.")

    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        issues.append(
            AcceptanceValidationIssue(
                code="acceptance_asset_missing",
                message="A required acceptance asset is missing.",
                path=path,
            )
        )
    except (OSError, UnicodeError):
        issues.append(
            AcceptanceValidationIssue(
                code="acceptance_asset_unreadable",
                message="A required acceptance asset could not be read.",
                path=path,
            )
        )

    return None


if __name__ == "__main__":
    raise SystemExit(main())
